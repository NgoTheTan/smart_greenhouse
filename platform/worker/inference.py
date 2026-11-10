"""AI inference runtime: nạp model active, suy luận 60 s, sinh dự báo & cảnh báo (spec 8.3)."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.crop_templates import DEFAULT_DEMO_PARAMS
from core.models import Alert, CropProfile, Greenhouse, MlModel, Prediction, Reading, Zone
from core.pubsub import CHANNEL_WS, pg_notify
from worker.alerts import raise_alert, resolve_alert

log = logging.getLogger("worker.inference")


class InferenceService:
    """Quản lý nạp model ML và chạy chu kỳ suy luận thời gian thực cho worker."""

    def __init__(self) -> None:
        self._models: dict[tuple[uuid.UUID | None, str], Any] = {}
        self._meta: dict[tuple[uuid.UUID | None, str], MlModel] = {}
        self._lock = asyncio.Lock()

    async def load_active_models(self, session: AsyncSession) -> None:
        """Nạp toàn bộ mô hình có is_active = True vào bộ nhớ cache."""
        s = get_settings()
        stmt = select(MlModel).where(MlModel.is_active.is_(True)).order_by(desc(MlModel.trained_at))
        active_models = list((await session.execute(stmt)).scalars().all())

        new_models: dict[tuple[uuid.UUID | None, str], Any] = {}
        new_meta: dict[tuple[uuid.UUID | None, str], MlModel] = {}

        for m in active_models:
            key = (m.zone_id, m.task)
            if key in new_models:
                continue  # Đã lấy model mới nhất

            loaded_obj = None
            art_path = Path(m.artifact_path)
            if not art_path.is_absolute():
                art_path = s.models_dir / art_path

            if art_path.exists():
                try:
                    import joblib  # Chỉ worker/ml import joblib

                    loaded_obj = await asyncio.to_thread(joblib.load, art_path)
                    log.info(
                        "Nạp artifact thành công cho %s (ver %d): %s", key, m.version, art_path
                    )
                except Exception:
                    log.exception("Lỗi khi nạp artifact joblib từ %s", art_path)

            new_models[key] = loaded_obj
            new_meta[key] = m

        async with self._lock:
            self._models = new_models
            self._meta = new_meta
        log.info("Đã nạp %d mô hình active vào InferenceService", len(new_meta))

    def get_pump_gain(self, zone_id: uuid.UUID) -> tuple[float, int] | None:
        """Lấy đặc tính phản ứng bơm (gain_pct_per_s, n_samples) cho RuleEngine."""
        key = (zone_id, "pump_response")
        meta = self._meta.get(key) or self._meta.get((None, "pump_response"))
        if meta and meta.metrics:
            gain = float(meta.metrics.get("pump_gain_pct_per_s", 0.0))
            n = meta.n_samples or 0
            if gain > 0:
                return gain, n
        return None

    def get_fan_rate(self, zone_id: uuid.UUID) -> tuple[float, int] | None:
        """Lấy đặc tính phản ứng quạt (fan_vpd_rate_kpa_per_s, n_samples) cho RuleEngine."""
        key = (zone_id, "fan_response")
        meta = self._meta.get(key) or self._meta.get((None, "fan_response"))
        if meta and meta.metrics:
            rate = float(meta.metrics.get("fan_vpd_rate_kpa_per_s", 0.0))
            n = meta.n_samples or 0
            if rate > 0:
                return rate, n
        return None

    async def run_cycle(self, session: AsyncSession, now: datetime | None = None) -> None:
        """Chu kỳ suy luận 60 giây: chạy risk_forecast và irrigation_eta cho các zone."""
        now = now or datetime.now(UTC)
        ts_minute = now.replace(second=0, microsecond=0)
        s = get_settings()

        # Lấy tất cả zone kèm nhà kính
        stmt = (
            select(Zone, Greenhouse)
            .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
            .order_by(Zone.greenhouse_id, Zone.zone_index)
        )
        zone_rows = (await session.execute(stmt)).all()

        for zone, gh in zone_rows:
            # Đọc readings gần nhất trong 60 phút
            window_start = now - timedelta(minutes=60)
            r_stmt = (
                select(Reading)
                .where(
                    Reading.zone_id == zone.id,
                    Reading.quality == "ok",
                    Reading.ts >= window_start,
                )
                .order_by(Reading.ts.asc())
            )
            readings = list((await session.execute(r_stmt)).scalars().all())
            if not readings:
                continue

            latest = readings[-1]
            # Nếu bản ghi gần nhất quá 15 phút (mất kết nối), bỏ qua suy luận chu kỳ này
            if (now - latest.ts).total_seconds() > 900:
                continue

            # Đọc crop parameters
            from core.crop_templates import CropParameters

            crop_params = CropParameters.model_validate(DEFAULT_DEMO_PARAMS)
            if zone.crop_profile_id is not None:
                cp = await session.get(CropProfile, zone.crop_profile_id)
                if cp and cp.parameters_json:
                    try:
                        crop_params = CropParameters.model_validate(cp.parameters_json)
                    except Exception:
                        pass

            # ------------------------------------------------------------------
            # 1. Task risk_forecast (A3)
            # ------------------------------------------------------------------
            rf_key = (zone.id, "risk_forecast")
            rf_meta = self._meta.get(rf_key) or self._meta.get((None, "risk_forecast"))
            rf_model = self._models.get(rf_key) or self._models.get((None, "risk_forecast"))

            score: float = 0.0
            if rf_model is not None and hasattr(rf_model, "predict_proba"):
                try:
                    # Trích xuất đặc trưng đơn giản hoặc gọi model
                    feats = [[
                        latest.air_temp or 25.0,
                        latest.air_rh or 70.0,
                        latest.vpd or 1.0,
                    ]]
                    probs = rf_model.predict_proba(feats)
                    score = float(probs[0][1]) if len(probs[0]) > 1 else float(probs[0][0])
                except Exception:
                    log.exception("Lỗi predict model risk_forecast cho zone %s", zone.id)
                    score = self._calc_baseline_risk_score(readings, crop_params)
            else:
                score = self._calc_baseline_risk_score(readings, crop_params)

            score = round(max(0.0, min(1.0, score)), 4)
            rf_details = {
                "baseline": rf_model is None,
                "vpd": latest.vpd,
                "air_rh": latest.air_rh,
            }

            # Upsert vào bảng predictions
            await self._upsert_prediction(
                session=session,
                zone_id=zone.id,
                task="risk_forecast",
                ts=ts_minute,
                model_id=rf_meta.id if rf_meta else None,
                horizon_min=15,
                score=score,
                value=None,
                details=rf_details,
            )

            # Phát WebSocket thông điệp prediction
            await pg_notify(
                session,
                CHANNEL_WS,
                {
                    "farm_id": str(gh.farm_id),
                    "type": "prediction",
                    "data": {
                        "zone_id": str(zone.id),
                        "ts": ts_minute.isoformat(),
                        "task": "risk_forecast",
                        "horizon_min": 15,
                        "score": score,
                        "value": None,
                        "details": rf_details,
                    },
                },
            )

            # Đánh giá cảnh báo sớm DISEASE_RISK_FORECAST (Kịch bản A)
            threshold = s.risk_forecast_threshold
            if score >= threshold:
                # Kiểm tra xem zone đã có cảnh báo DISEASE_RISK thật chưa
                active_real_alert = (
                    await session.execute(
                        select(Alert).where(
                            Alert.zone_id == zone.id,
                            Alert.alert_type == "DISEASE_RISK",
                            Alert.state != "resolved",
                        )
                    )
                ).scalar_one_or_none()

                if active_real_alert is None:
                    pct = int(score * 100)
                    body_msg = (
                        f"Dự báo vi khí hậu cho thấy nguy cơ nấm bệnh cao trong 15 phút tới "
                        f"(xác suất {pct}%, VPD={latest.vpd:.2f} kPa, RH={latest.air_rh:.1f}%)."
                    )
                    await raise_alert(
                        session=session,
                        greenhouse_id=gh.id,
                        alert_type="DISEASE_RISK_FORECAST",
                        severity="warning",
                        dedupe_key=f"DISEASE_RISK_FORECAST:{zone.id}",
                        zone_id=zone.id,
                        payload={
                            "title": "DỰ BÁO: Rủi ro nấm bệnh",
                            "body": body_msg,
                            "score": score,
                            "horizon_min": 15,
                            "vpd": latest.vpd,
                            "air_rh": latest.air_rh,
                        },
                        now=now,
                    )
            elif score < (threshold - 0.15):
                # Hysteresis resolve cảnh báo dự báo khi rủi ro đã hạ
                await resolve_alert(
                    session=session,
                    dedupe_key=f"DISEASE_RISK_FORECAST:{zone.id}",
                    now=now,
                )

            # ------------------------------------------------------------------
            # 2. Task irrigation_eta (A2)
            # ------------------------------------------------------------------
            eta_key = (zone.id, "irrigation_eta")
            eta_meta = self._meta.get(eta_key) or self._meta.get((None, "irrigation_eta"))
            eta_model = self._models.get(eta_key) or self._models.get((None, "irrigation_eta"))

            eta_val: float | None = None
            soil_now = latest.soil_moisture
            soil_min = float(crop_params.soil_moisture_pct.min)

            if eta_model is not None and hasattr(eta_model, "predict"):
                try:
                    preds = eta_model.predict([[soil_now or 50.0]])
                    eta_val = max(0.0, float(preds[0]))
                except Exception:
                    log.exception("Lỗi predict model irrigation_eta cho zone %s", zone.id)
                    eta_val = self._calc_baseline_irrigation_eta(readings, soil_min)
            else:
                eta_val = self._calc_baseline_irrigation_eta(readings, soil_min)

            eta_details = {
                "baseline": eta_model is None,
                "soil_moisture": soil_now,
                "soil_min": soil_min,
            }

            await self._upsert_prediction(
                session=session,
                zone_id=zone.id,
                task="irrigation_eta",
                ts=ts_minute,
                model_id=eta_meta.id if eta_meta else None,
                horizon_min=None,
                score=None,
                value=eta_val,
                details=eta_details,
            )

            await pg_notify(
                session,
                CHANNEL_WS,
                {
                    "farm_id": str(gh.farm_id),
                    "type": "prediction",
                    "data": {
                        "zone_id": str(zone.id),
                        "ts": ts_minute.isoformat(),
                        "task": "irrigation_eta",
                        "horizon_min": None,
                        "score": None,
                        "value": eta_val,
                        "details": eta_details,
                    },
                },
            )

    @staticmethod
    def _calc_baseline_risk_score(readings: list[Reading], crop_params: Any) -> float:
        """Tính rủi ro nấm bệnh ngoại suy tuyến tính khi chưa có mô hình ML offline."""
        latest = readings[-1]
        vpd = latest.vpd if latest.vpd is not None else 1.0
        rh = latest.air_rh if latest.air_rh is not None else 70.0

        # Đo tốc độ giảm VPD qua các mẫu gần nhất
        dt_min = (latest.ts - readings[0].ts).total_seconds() / 60.0
        slope_vpd = 0.0
        if dt_min >= 2.0 and readings[0].vpd is not None and latest.vpd is not None:
            slope_vpd = (latest.vpd - readings[0].vpd) / dt_min

        # Điểm cơ sở theo RH và VPD
        rh_factor = max(0.0, min(1.0, (rh - 80.0) / 15.0))
        vpd_factor = max(0.0, min(1.0, (0.8 - vpd) / 0.6))
        slope_factor = max(0.0, min(1.0, -slope_vpd * 15.0)) if slope_vpd < 0 else 0.0

        score = 0.45 * rh_factor + 0.45 * vpd_factor + 0.10 * slope_factor
        return score

    @staticmethod
    def _calc_baseline_irrigation_eta(readings: list[Reading], soil_min: float) -> float | None:
        """Ước lượng thời gian còn lại (phút) tới khi đất khô dưới ngưỡng soil_min."""
        latest = readings[-1]
        if latest.soil_moisture is None:
            return None

        soil_now = latest.soil_moisture
        if soil_now <= soil_min:
            return 0.0

        if len(readings) < 2:
            return None

        dt_min = (latest.ts - readings[0].ts).total_seconds() / 60.0
        if dt_min < 3.0:
            return None

        first_soil = readings[0].soil_moisture
        if first_soil is None:
            return None

        d_soil = first_soil - soil_now
        if d_soil <= 0.01:
            # Đất đang ẩm lên hoặc ổn định
            return None

        drying_rate = d_soil / dt_min  # % mỗi phút
        eta_minutes = (soil_now - soil_min) / drying_rate
        return round(max(0.0, min(1440.0, eta_minutes)), 1)

    @staticmethod
    async def _upsert_prediction(
        session: AsyncSession,
        zone_id: uuid.UUID,
        task: str,
        ts: datetime,
        model_id: uuid.UUID | None,
        horizon_min: int | None,
        score: float | None,
        value: float | None,
        details: dict[str, Any] | None,
    ) -> None:
        pred = await session.get(Prediction, (zone_id, task, ts))
        if pred is None:
            pred = Prediction(
                zone_id=zone_id,
                task=task,
                ts=ts,
                model_id=model_id,
                horizon_min=horizon_min,
                score=score,
                value=value,
                details=details,
            )
            session.add(pred)
        else:
            pred.model_id = model_id
            pred.horizon_min = horizon_min
            pred.score = score
            pred.value = value
            pred.details = details
