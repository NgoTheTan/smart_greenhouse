"""AI inference runtime: nạp model yield toàn cục, yield_samples, dự báo & gợi ý cây (spec 7, 8)."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.climate_features import (
    FEATURE_VERSION,
    ClimateBucket,
    check_ood_features,
    compute_climate_features,
    merge_greenhouse_buckets,
)
from core.config import get_settings
from core.crop_templates import DEFAULT_DEMO_PARAMS, CropParameters, get_system_crop_catalog
from core.models import (
    CropCycle,
    CropProfile,
    Gateway,
    Greenhouse,
    MlModel,
    Prediction,
    YieldSample,
    Zone,
)
from core.pubsub import CHANNEL_WS, pg_notify
from worker.alerts import raise_alert, resolve_alert

log = logging.getLogger("worker.inference")


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_crop_params(raw: dict[str, Any] | None) -> CropParameters:
    if raw:
        try:
            return CropParameters.model_validate(raw)
        except Exception:
            pass
    return CropParameters.model_validate(DEFAULT_DEMO_PARAMS)


def build_recommendation_reasons(
    features: dict[str, float | None],
    template: dict[str, Any] | None,
) -> list[str]:
    """Sinh tối đa 3 lý do tiếng Việt giải thích độ phù hợp khí hậu với cây ứng viên."""
    if not template or not isinstance(template.get("parameters_json"), dict):
        return []
    params = template["parameters_json"]
    mismatches: list[str] = []
    matches: list[str] = []

    t_mean = features.get("t_mean")
    t_opt = (params.get("temp_c") or {}).get("optimal")
    if isinstance(t_mean, int | float) and isinstance(t_opt, list) and len(t_opt) == 2:
        lo, hi = float(t_opt[0]), float(t_opt[1])
        if t_mean < lo:
            mismatches.append(
                f"Nhiệt độ TB {t_mean:.1f} °C thấp hơn khoảng tối ưu {lo:g}–{hi:g} °C"
            )
        elif t_mean > hi:
            mismatches.append(
                f"Nhiệt độ TB {t_mean:.1f} °C cao hơn khoảng tối ưu {lo:g}–{hi:g} °C"
            )
        else:
            matches.append(
                f"Nhiệt độ TB {t_mean:.1f} °C nằm trong khoảng tối ưu {lo:g}–{hi:g} °C"
            )

    vpd_mean = features.get("vpd_mean")
    vpd_opt = (params.get("vpd") or {}).get("optimal")
    if isinstance(vpd_mean, int | float) and isinstance(vpd_opt, list) and len(vpd_opt) == 2:
        lo, hi = float(vpd_opt[0]), float(vpd_opt[1])
        if vpd_mean < lo:
            mismatches.append(
                f"VPD TB {vpd_mean:.2f} kPa thấp hơn khoảng tối ưu {lo:g}–{hi:g} kPa"
            )
        elif vpd_mean > hi:
            mismatches.append(
                f"VPD TB {vpd_mean:.2f} kPa cao hơn khoảng tối ưu {lo:g}–{hi:g} kPa"
            )
        else:
            matches.append(
                f"VPD TB {vpd_mean:.2f} kPa nằm trong khoảng tối ưu {lo:g}–{hi:g} kPa"
            )

    dli_mean = features.get("dli_mean")
    dli_opt = (params.get("light") or {}).get("dli_optimal")
    if isinstance(dli_mean, int | float) and isinstance(dli_opt, list) and len(dli_opt) == 2:
        lo, hi = float(dli_opt[0]), float(dli_opt[1])
        if dli_mean < lo:
            mismatches.append(
                f"DLI TB {dli_mean:.1f} mol/m²/ngày thấp hơn khoảng tối ưu {lo:g}–{hi:g}"
            )
        elif dli_mean > hi:
            mismatches.append(
                f"DLI TB {dli_mean:.1f} mol/m²/ngày cao hơn khoảng tối ưu {lo:g}–{hi:g}"
            )
        else:
            matches.append(
                f"DLI TB {dli_mean:.1f} mol/m²/ngày nằm trong khoảng tối ưu {lo:g}–{hi:g}"
            )

    return (mismatches + matches)[:3]


def _predict_rows_sync(bundle: dict[str, Any], rows: list[dict[str, Any]]) -> list[float]:
    """Chạy predict đồng bộ trên pandas DataFrame (gọi qua asyncio.to_thread)."""
    import pandas as pd

    estimator = bundle["estimator"]
    feature_names: list[str] = list(bundle["feature_names"])
    df = pd.DataFrame(rows, columns=feature_names)

    if "crop_code" in df.columns:
        cats: list[str] = list(bundle.get("crop_categories") or [])
        if cats and all(c in cats for c in df["crop_code"].tolist()):
            df["crop_code"] = pd.Categorical(df["crop_code"], categories=cats)
        else:
            df["crop_code"] = pd.Categorical(df["crop_code"])

    preds = estimator.predict(df)
    return [max(0.0, float(v)) for v in preds]


class InferenceService:
    """Quản lý mô hình `yield` toàn cục, sinh `yield_samples`, dự báo & gợi ý cây trồng."""

    def __init__(self) -> None:
        self._bundle: dict[str, Any] | None = None
        self._meta: MlModel | None = None
        self._lock = asyncio.Lock()
        self._last_yield_forecast_at: dict[uuid.UUID, datetime] = {}
        self._last_recommend_at: dict[uuid.UUID, datetime] = {}

    @property
    def has_active_model(self) -> bool:
        return self._bundle is not None and self._meta is not None

    @property
    def active_model_meta(self) -> MlModel | None:
        return self._meta

    @staticmethod
    def _parse_bundle_dict(
        raw_bundle: dict[str, Any], model_meta: MlModel
    ) -> dict[str, Any] | None:
        fv = int(raw_bundle.get("feature_version", model_meta.feature_version or 1))
        if fv != FEATURE_VERSION:
            log.error(
                "feature_version=%d của model %s v%d không khớp runtime (%d)",
                fv,
                model_meta.id,
                model_meta.version,
                FEATURE_VERSION,
            )
            return None

        estimator = raw_bundle.get("model")
        if estimator is None or not hasattr(estimator, "predict"):
            log.error("Bundle model v%d thiếu estimator hợp lệ", model_meta.version)
            return None

        if hasattr(estimator, "set_params"):
            try:
                estimator.set_params(n_jobs=1)
            except Exception:
                pass

        crops_ref: dict[str, float] = {}
        crop_categories: list[str] = list(raw_bundle.get("crop_categories") or [])
        crops_source = raw_bundle.get("crops") or model_meta.crops or []
        if isinstance(crops_source, dict):
            for code, ref in crops_source.items():
                crops_ref[str(code)] = float(ref)
        elif isinstance(crops_source, list):
            for entry in crops_source:
                if isinstance(entry, dict) and entry.get("crop_code"):
                    code = str(entry["crop_code"])
                    crops_ref[code] = float(entry.get("reference_kg_m2", 1.0))

        if not crop_categories and crops_ref:
            crop_categories = list(crops_ref.keys())

        feature_names = list(raw_bundle.get("feature_names") or [])
        quantiles = raw_bundle.get("residual_quantiles") or {}
        bounds = raw_bundle.get("train_feature_bounds") or {}
        stats = raw_bundle.get("train_stats") or {}

        return {
            "estimator": estimator,
            "feature_version": fv,
            "feature_names": feature_names,
            "crop_categories": crop_categories,
            "crops_ref": crops_ref,
            "residual_quantiles": {
                "p10": float(quantiles.get("p10", 0.0)),
                "p90": float(quantiles.get("p90", 0.0)),
            },
            "train_feature_bounds": bounds,
            "train_stats": stats,
        }

    async def load_active_model(self, session: AsyncSession) -> bool:
        """Nạp hoặc hot-reload mô hình `task='yield'` đang `is_active = True`."""
        s = get_settings()
        stmt = (
            select(MlModel)
            .where(MlModel.task == "yield", MlModel.is_active.is_(True))
            .order_by(desc(MlModel.version))
            .limit(1)
        )
        model = (await session.execute(stmt)).scalar_one_or_none()
        if model is None:
            async with self._lock:
                self._bundle = None
                self._meta = None
            log.info("Chưa có mô hình `yield` active trong DB — bỏ qua suy luận AI")
            return False

        if self._meta is not None and self._meta.id == model.id and self._bundle is not None:
            return True

        art_path = Path(model.artifact_path)
        if not art_path.is_absolute():
            art_path = s.models_dir / art_path

        if not art_path.exists():
            log.warning(
                "Không tìm thấy artifact mô hình v%d tại %s", model.version, art_path
            )
            async with self._lock:
                self._bundle = None
                self._meta = None
            return False

        try:
            import joblib  # Chỉ worker/ml import joblib

            raw_bundle = await asyncio.to_thread(joblib.load, art_path)
        except Exception:
            log.exception("Lỗi khi nạp artifact joblib từ %s", art_path)
            return False

        if not isinstance(raw_bundle, dict):
            log.error("Artifact %s không phải dict hợp lệ", art_path)
            return False

        parsed = self._parse_bundle_dict(raw_bundle, model)
        if parsed is None:
            return False

        async with self._lock:
            self._bundle = parsed
            self._meta = model
        log.info(
            "Đã nạp mô hình yield v%d (%d cây trồng) từ %s",
            model.version,
            len(parsed["crops_ref"]),
            art_path,
        )
        return True

    async def check_and_reload_active_model(self, session: AsyncSession) -> None:
        """Job 10 phút: kiểm tra reload model active và quét bù vụ thu hoạch bị lỡ."""
        await self.load_active_model(session)

        existing_subq = select(YieldSample.crop_cycle_id).where(
            YieldSample.crop_cycle_id.is_not(None)
        )
        stmt = (
            select(CropCycle.id)
            .where(
                CropCycle.status == "harvested",
                CropCycle.harvested_at.is_not(None),
                CropCycle.yield_kg.is_not(None),
                ~CropCycle.id.in_(existing_subq),
                or_(
                    CropCycle.notes.is_(None),
                    ~CropCycle.notes.contains("Không tạo mẫu yield_samples:"),
                ),
            )
            .order_by(CropCycle.harvested_at.asc())
            .limit(50)
        )
        missed_ids = list((await session.execute(stmt)).scalars().all())
        for cid in missed_ids:
            try:
                await self.handle_cycle_harvested(session, cid)
            except Exception:
                log.exception("Lỗi khi quét bù yield_sample cho cycle %s", cid)

    async def _fetch_zone_buckets(
        self,
        session: AsyncSession,
        zone_id: uuid.UUID,
        greenhouse_id: uuid.UUID,
        window_start: datetime,
        window_end: datetime,
        *,
        use_1m: bool,
    ) -> tuple[list[ClimateBucket], dict[datetime, float]]:
        """Đọc chuỗi bucket của zone và lux của các zone anh em trong cùng nhà kính."""
        table_name = "readings_1m" if use_1m else "readings_1h"
        sql = text(
            f"SELECT bucket, zone_id, air_temp, air_rh, vpd, soil_moisture, lux "  # noqa: S608
            f"FROM {table_name} "
            f"WHERE zone_id IN (SELECT id FROM zones WHERE greenhouse_id = :gh_id) "
            f"AND bucket >= :start_ts AND bucket <= :end_ts "
            f"ORDER BY bucket ASC"
        )
        result = await session.execute(
            sql,
            {
                "gh_id": greenhouse_id,
                "start_ts": window_start,
                "end_ts": window_end,
            },
        )

        zone_buckets: list[ClimateBucket] = []
        sibling_lux_accum: dict[datetime, list[float]] = {}
        for row in result.mappings().all():
            ts = _normalize_utc(row["bucket"])
            row_zone_id = row["zone_id"]
            lux_val = float(row["lux"]) if row["lux"] is not None else None
            if row_zone_id == zone_id:
                zone_buckets.append(
                    ClimateBucket(
                        ts=ts,
                        air_temp=float(row["air_temp"]) if row["air_temp"] is not None else None,
                        air_rh=float(row["air_rh"]) if row["air_rh"] is not None else None,
                        vpd=float(row["vpd"]) if row["vpd"] is not None else None,
                        soil_moisture=(
                            float(row["soil_moisture"])
                            if row["soil_moisture"] is not None
                            else None
                        ),
                        lux=lux_val,
                    )
                )
            elif lux_val is not None and lux_val >= 0.0:
                sibling_lux_accum.setdefault(ts, []).append(lux_val)

        sibling_lux_by_ts = {
            ts: sum(vals) / len(vals) for ts, vals in sibling_lux_accum.items() if vals
        }
        return zone_buckets, sibling_lux_by_ts

    async def _fetch_greenhouse_buckets(
        self,
        session: AsyncSession,
        greenhouse_id: uuid.UUID,
        window_start: datetime,
        window_end: datetime,
        *,
        use_1m: bool,
    ) -> list[ClimateBucket]:
        """Đọc toàn bộ bucket của mọi zone thuộc nhà kính trong khoảng thời gian."""
        table_name = "readings_1m" if use_1m else "readings_1h"
        sql = text(
            f"SELECT bucket, air_temp, air_rh, vpd, soil_moisture, lux "  # noqa: S608
            f"FROM {table_name} "
            f"WHERE zone_id IN (SELECT id FROM zones WHERE greenhouse_id = :gh_id) "
            f"AND bucket >= :start_ts AND bucket <= :end_ts "
            f"ORDER BY bucket ASC"
        )
        result = await session.execute(
            sql,
            {
                "gh_id": greenhouse_id,
                "start_ts": window_start,
                "end_ts": window_end,
            },
        )
        buckets: list[ClimateBucket] = []
        for row in result.mappings().all():
            buckets.append(
                ClimateBucket(
                    ts=_normalize_utc(row["bucket"]),
                    air_temp=float(row["air_temp"]) if row["air_temp"] is not None else None,
                    air_rh=float(row["air_rh"]) if row["air_rh"] is not None else None,
                    vpd=float(row["vpd"]) if row["vpd"] is not None else None,
                    soil_moisture=(
                        float(row["soil_moisture"])
                        if row["soil_moisture"] is not None
                        else None
                    ),
                    lux=float(row["lux"]) if row["lux"] is not None else None,
                )
            )
        return buckets

    async def _load_crop_catalog(self, session: AsyncSession) -> dict[str, dict[str, Any]]:
        """Tải template hệ thống theo `crop_code` (ưu tiên DB, fallback `crop_templates`)."""
        catalog = dict(get_system_crop_catalog())
        stmt = select(CropProfile).where(CropProfile.farm_id.is_(None))
        db_profiles = list((await session.execute(stmt)).scalars().all())
        for cp in db_profiles:
            entry = {
                "id": str(cp.id),
                "crop_code": cp.crop_code,
                "crop_name": cp.crop_name,
                "variety": cp.variety or "real",
                "schema_version": cp.schema_version,
                "parameters_json": cp.parameters_json,
            }
            if cp.variety == "real" or cp.crop_code not in catalog:
                catalog[cp.crop_code] = entry
        return catalog

    async def handle_cycle_harvested(
        self, session: AsyncSession, cycle_id: uuid.UUID
    ) -> YieldSample | None:
        """Tổng hợp đặc trưng khí hậu cả vụ khi thu hoạch và chèn `yield_samples`."""
        stmt = (
            select(CropCycle, Zone, Greenhouse, Gateway, CropProfile)
            .join(Zone, CropCycle.zone_id == Zone.id)
            .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
            .outerjoin(Gateway, Gateway.greenhouse_id == Greenhouse.id)
            .join(CropProfile, CropCycle.crop_profile_id == CropProfile.id)
            .where(CropCycle.id == cycle_id)
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            log.warning("Không tìm thấy CropCycle %s khi xử lý cycle_harvested", cycle_id)
            return None

        cycle, zone, gh, gw, profile = row
        if (
            cycle.status != "harvested"
            or cycle.harvested_at is None
            or cycle.yield_kg is None
            or cycle.area_m2 <= 0
        ):
            return None

        # Idempotent: không tạo trùng nếu đã có mẫu cho cycle_id này
        existing = (
            await session.execute(
                select(YieldSample).where(YieldSample.crop_cycle_id == cycle.id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        # Đóng cảnh báo năng suất thấp (nếu có) vì vụ đã thu hoạch
        await resolve_alert(session, dedupe_key=f"YIELD_FORECAST_LOW:{zone.id}")

        started_at = _normalize_utc(cycle.started_at)
        harvested_at = _normalize_utc(cycle.harvested_at)
        duration_h = max(0.0, (harvested_at - started_at).total_seconds() / 3600.0)
        use_1m = duration_h < 6.0

        buckets, sibling_lux = await self._fetch_zone_buckets(
            session,
            zone.id,
            gh.id,
            started_at,
            harvested_at,
            use_1m=use_1m,
        )

        s = get_settings()
        feat_res = compute_climate_features(
            buckets,
            started_at,
            harvested_at,
            bucket_seconds=60 if use_1m else 3600,
            sibling_lux_by_ts=sibling_lux,
            tz_name=s.tz,
        )
        params = _parse_crop_params(profile.parameters_json)
        min_cov = float(params.ai.min_coverage)

        if feat_res.coverage < min_cov:
            msg = (
                f"Không tạo mẫu yield_samples: độ phủ dữ liệu {feat_res.coverage:.2f} "
                f"< ngưỡng {min_cov:.2f}"
            )
            if cycle.notes:
                if "Không tạo mẫu yield_samples:" not in cycle.notes:
                    cycle.notes = f"{cycle.notes}\n{msg}"
            else:
                cycle.notes = msg
            log.info("Bỏ qua yield_sample cho cycle %s: %s", cycle.id, msg)
            return None

        source = "sim" if (gw is not None and gw.is_simulated) else "real"
        yield_kg_m2 = round(float(cycle.yield_kg) / float(cycle.area_m2), 4)
        sample = YieldSample(
            id=uuid.uuid4(),
            source=source,
            greenhouse_key=str(gh.id),
            farm_id=gh.farm_id,
            crop_cycle_id=cycle.id,
            crop_code=profile.crop_code,
            started_at=started_at,
            ended_at=harvested_at,
            cycle_days=round(duration_h / 24.0, 4),
            feature_version=feat_res.feature_version,
            features=feat_res.features,
            coverage=feat_res.coverage,
            yield_kg_m2=yield_kg_m2,
            meta={"zone_id": str(zone.id), "crop_profile_id": str(profile.id)},
        )
        session.add(sample)
        await session.flush()
        log.info(
            "Đã tạo yield_sample %s (source=%s, crop=%s, kg/m2=%.3f, cov=%.2f)",
            sample.id,
            source,
            profile.crop_code,
            yield_kg_m2,
            feat_res.coverage,
        )
        return sample

    async def run_yield_forecast_for_cycle(
        self,
        session: AsyncSession,
        cycle: CropCycle,
        zone: Zone,
        gh: Greenhouse,
        profile: CropProfile,
        *,
        now: datetime | None = None,
    ) -> Prediction | None:
        """Dự báo năng suất vụ đang trồng (`yield_forecast`) cho 1 zone."""
        bundle = self._bundle
        meta = self._meta
        if bundle is None or meta is None:
            return None

        now = _normalize_utc(now or datetime.now(UTC))
        s = get_settings()
        params = _parse_crop_params(profile.parameters_json)

        started_at = _normalize_utc(cycle.started_at)
        elapsed_h = (now - started_at).total_seconds() / 3600.0
        if elapsed_h < params.ai.min_cycle_hours:
            return None

        crops_ref: dict[str, float] = bundle["crops_ref"]
        if profile.crop_code not in crops_ref:
            log.debug("crop_code %s chưa có trong model active — bỏ qua", profile.crop_code)
            return None

        use_1m = elapsed_h < 6.0
        buckets, sibling_lux = await self._fetch_zone_buckets(
            session,
            zone.id,
            gh.id,
            started_at,
            now,
            use_1m=use_1m,
        )
        feat_res = compute_climate_features(
            buckets,
            started_at,
            now,
            bucket_seconds=60 if use_1m else 3600,
            sibling_lux_by_ts=sibling_lux,
            tz_name=s.tz,
        )
        if feat_res.valid_buckets == 0 or feat_res.coverage < params.ai.min_coverage:
            return None

        row = {**feat_res.features, "crop_code": profile.crop_code}
        preds = await asyncio.to_thread(_predict_rows_sync, bundle, [row])
        rel_yield = round(preds[0], 4)

        ref_kg_m2 = float(crops_ref[profile.crop_code])
        q10 = float(bundle["residual_quantiles"]["p10"])
        q90 = float(bundle["residual_quantiles"]["p90"])
        low_rel = max(0.0, rel_yield + q10)
        high_rel = max(0.0, rel_yield + q90)
        expected_kg_m2 = round(rel_yield * ref_kg_m2, 4)
        interval = [round(low_rel * ref_kg_m2, 4), round(high_rel * ref_kg_m2, 4)]
        interval_rel = [round(low_rel, 4), round(high_rel, 4)]

        ood = check_ood_features(feat_res.features, bundle.get("train_feature_bounds"))
        low_confidence = (elapsed_h < 24.0) or bool(ood)

        details: dict[str, Any] = {
            "crop_code": profile.crop_code,
            "reference_kg_m2": ref_kg_m2,
            "cycle_days_elapsed": round(elapsed_h / 24.0, 2),
            "window_hours": round(elapsed_h, 2),
            "interval": interval,
            "interval_relative": interval_rel,
            "coverage": feat_res.coverage,
            "low_confidence": low_confidence,
            "ood_features": ood,
            "features": feat_res.features,
        }

        pred = Prediction(
            id=uuid.uuid4(),
            ts=now,
            task="yield_forecast",
            greenhouse_id=gh.id,
            zone_id=zone.id,
            crop_cycle_id=cycle.id,
            model_id=meta.id,
            value=expected_kg_m2,
            score=rel_yield,
            details=details,
        )
        session.add(pred)
        await session.flush()

        await pg_notify(
            session,
            CHANNEL_WS,
            {
                "farm_id": str(gh.farm_id),
                "type": "prediction",
                "data": {
                    "id": str(pred.id),
                    "task": "yield_forecast",
                    "greenhouse_id": str(gh.id),
                    "zone_id": str(zone.id),
                    "crop_cycle_id": str(cycle.id),
                    "ts": now.isoformat(),
                    "value": expected_kg_m2,
                    "score": rel_yield,
                    "details": details,
                },
            },
        )

        dedupe_key = f"YIELD_FORECAST_LOW:{zone.id}"
        if rel_yield < s.yield_low_threshold and not low_confidence:
            pct = int(round(rel_yield * 100))
            await raise_alert(
                session,
                greenhouse_id=gh.id,
                alert_type="YIELD_FORECAST_LOW",
                severity="info",
                dedupe_key=dedupe_key,
                zone_id=zone.id,
                payload={
                    "title": "THÔNG BÁO: Năng suất dự kiến thấp",
                    "body": (
                        f"Zone {zone.name or zone.zone_index} dự kiến đạt "
                        f"{expected_kg_m2:.2f} kg/m² ({pct}% mức tham chiếu) "
                        f"cho {profile.crop_name}."
                    ),
                    "value": expected_kg_m2,
                    "score": rel_yield,
                    "relative_yield": rel_yield,
                    "expected_kg_m2": expected_kg_m2,
                    "crop_code": profile.crop_code,
                },
                now=now,
            )
        elif rel_yield >= s.yield_low_threshold:
            await resolve_alert(session, dedupe_key=dedupe_key, now=now)

        self._last_yield_forecast_at[zone.id] = now
        return pred

    async def run_recommendation_for_greenhouse(
        self,
        session: AsyncSession,
        greenhouse_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> Prediction | None:
        """Gợi ý cây nên trồng (`crop_recommendation`) dựa trên khí hậu hiện tại của nhà kính."""
        bundle = self._bundle
        meta = self._meta
        if bundle is None or meta is None:
            return None

        gh = await session.get(Greenhouse, greenhouse_id)
        if gh is None:
            return None

        zone_stmt = (
            select(Zone, CropProfile)
            .outerjoin(CropProfile, Zone.crop_profile_id == CropProfile.id)
            .where(Zone.greenhouse_id == greenhouse_id)
        )
        zone_rows = (await session.execute(zone_stmt)).all()
        if not zone_rows:
            return None

        windows: list[int] = []
        coverages: list[float] = []
        for _zone, cp in zone_rows:
            if cp and cp.parameters_json:
                p = _parse_crop_params(cp.parameters_json)
                windows.append(int(p.ai.recommend_window_h))
                coverages.append(float(p.ai.min_coverage))

        recommend_window_h = min(windows) if windows else 336
        min_cov = min(coverages) if coverages else 0.7

        now = _normalize_utc(now or datetime.now(UTC))
        window_start = now - timedelta(hours=recommend_window_h)
        use_1m = recommend_window_h < 6.0

        raw_buckets = await self._fetch_greenhouse_buckets(
            session,
            greenhouse_id,
            window_start,
            now,
            use_1m=use_1m,
        )
        if not raw_buckets:
            return None

        s = get_settings()
        merged = merge_greenhouse_buckets(raw_buckets)
        feat_res = compute_climate_features(
            merged,
            window_start,
            now,
            bucket_seconds=60 if use_1m else 3600,
            tz_name=s.tz,
        )
        if feat_res.valid_buckets == 0 or feat_res.coverage < min_cov:
            log.debug(
                "Bỏ qua crop_recommendation cho greenhouse %s: coverage %.2f < %.2f",
                greenhouse_id,
                feat_res.coverage,
                min_cov,
            )
            return None

        crops_ref: dict[str, float] = bundle["crops_ref"]
        if not crops_ref:
            return None

        bounds = bundle.get("train_feature_bounds") or {}
        ood = check_ood_features(
            feat_res.features,
            bounds,
            ignore_keys={"soil_mean", "soil_std"},
        )
        low_confidence = (recommend_window_h < 24.0) or bool(ood)

        catalog = await self._load_crop_catalog(session)
        default_soil_std = float((bounds.get("soil_std") or {}).get("median", 5.0))
        q10 = float(bundle["residual_quantiles"]["p10"])
        q90 = float(bundle["residual_quantiles"]["p90"])

        candidate_codes = list(crops_ref.keys())
        rows_for_model: list[dict[str, Any]] = []
        for code in candidate_codes:
            tpl = catalog.get(code)
            soil_mean_cand = 65.0
            if tpl and isinstance(tpl.get("parameters_json"), dict):
                sm = tpl["parameters_json"].get("soil_moisture_pct") or {}
                if "min" in sm and "max" in sm:
                    soil_mean_cand = round((float(sm["min"]) + float(sm["max"])) / 2.0, 2)
            row = dict(feat_res.features)
            row["soil_mean"] = soil_mean_cand
            row["soil_std"] = default_soil_std
            row["crop_code"] = code
            rows_for_model.append(row)

        rel_preds = await asyncio.to_thread(_predict_rows_sync, bundle, rows_for_model)

        ranking: list[dict[str, Any]] = []
        for code, rel_val in zip(candidate_codes, rel_preds, strict=True):
            ref = float(crops_ref[code])
            rel_rounded = round(rel_val, 4)
            expected_kg_m2 = round(rel_val * ref, 4)
            low_kg = round(max(0.0, rel_val + q10) * ref, 4)
            high_kg = round(max(0.0, rel_val + q90) * ref, 4)
            tpl = catalog.get(code)
            crop_name = str(tpl["crop_name"]) if tpl else code
            reasons = build_recommendation_reasons(feat_res.features, tpl)
            ranking.append(
                {
                    "crop_code": code,
                    "crop_name": crop_name,
                    "relative_yield": rel_rounded,
                    "expected_kg_m2": expected_kg_m2,
                    "interval": [low_kg, high_kg],
                    "reasons": reasons,
                }
            )

        ranking.sort(key=lambda item: item["relative_yield"], reverse=True)
        top_score = ranking[0]["relative_yield"] if ranking else None

        features_stored = dict(feat_res.features)
        features_stored["soil_mean"] = None
        features_stored["soil_std"] = None

        climate_summary = {
            "t_mean": feat_res.features.get("t_mean"),
            "t_day_mean": feat_res.features.get("t_day_mean"),
            "t_night_mean": feat_res.features.get("t_night_mean"),
            "rh_mean": feat_res.features.get("rh_mean"),
            "vpd_mean": feat_res.features.get("vpd_mean"),
            "dli_mean": feat_res.features.get("dli_mean"),
        }

        details: dict[str, Any] = {
            "window_h": recommend_window_h,
            "coverage": feat_res.coverage,
            "low_confidence": low_confidence,
            "ood_features": ood,
            "climate_summary": climate_summary,
            "features": features_stored,
            "ranking": ranking,
        }

        pred = Prediction(
            id=uuid.uuid4(),
            ts=now,
            task="crop_recommendation",
            greenhouse_id=gh.id,
            zone_id=None,
            crop_cycle_id=None,
            model_id=meta.id,
            value=None,
            score=top_score,
            details=details,
        )
        session.add(pred)
        await session.flush()

        # Giữ payload pg_notify gọn dưới 8000 bytes (top-3 + tóm tắt khí hậu)
        ws_details = {
            "window_h": recommend_window_h,
            "coverage": feat_res.coverage,
            "low_confidence": low_confidence,
            "ood_features": ood,
            "climate_summary": climate_summary,
            "ranking": ranking[:3],
        }
        await pg_notify(
            session,
            CHANNEL_WS,
            {
                "farm_id": str(gh.farm_id),
                "type": "prediction",
                "data": {
                    "id": str(pred.id),
                    "task": "crop_recommendation",
                    "greenhouse_id": str(gh.id),
                    "ts": now.isoformat(),
                    "score": top_score,
                    "details": ws_details,
                },
            },
        )

        self._last_recommend_at[greenhouse_id] = now
        return pred

    async def run_cycle(self, session: AsyncSession, now: datetime | None = None) -> None:
        """Chu kỳ kiểm tra 60s: chạy yield_forecast & crop_recommendation theo interval."""
        if not self.has_active_model:
            return

        now = _normalize_utc(now or datetime.now(UTC))

        # 1. Dự báo năng suất cho các zone đang có vụ active
        cycle_stmt = (
            select(CropCycle, Zone, Greenhouse, CropProfile)
            .join(Zone, CropCycle.zone_id == Zone.id)
            .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
            .join(CropProfile, CropCycle.crop_profile_id == CropProfile.id)
            .where(CropCycle.status == "active")
            .order_by(Zone.greenhouse_id, Zone.zone_index)
        )
        active_cycles = (await session.execute(cycle_stmt)).all()
        for cycle, zone, gh, profile in active_cycles:
            params = _parse_crop_params(profile.parameters_json)
            last_ts = self._last_yield_forecast_at.get(zone.id)
            if (
                last_ts is not None
                and (now - last_ts).total_seconds() < params.ai.inference_interval_s
            ):
                continue
            try:
                await self.run_yield_forecast_for_cycle(
                    session, cycle, zone, gh, profile, now=now
                )
            except Exception:
                log.exception("Lỗi suy luận yield_forecast cho zone %s", zone.id)

        # 2. Gợi ý cây trồng theo chu kỳ từng nhà kính
        gh_stmt = (
            select(Greenhouse, Zone, CropProfile)
            .outerjoin(Zone, Zone.greenhouse_id == Greenhouse.id)
            .outerjoin(CropProfile, Zone.crop_profile_id == CropProfile.id)
            .order_by(Greenhouse.id)
        )
        gh_rows = (await session.execute(gh_stmt)).all()
        gh_intervals: dict[uuid.UUID, int] = {}
        for gh, _zone, cp in gh_rows:
            interval = 3600
            if cp and cp.parameters_json:
                interval = int(_parse_crop_params(cp.parameters_json).ai.inference_interval_s)
            if gh.id not in gh_intervals or interval < gh_intervals[gh.id]:
                gh_intervals[gh.id] = interval

        for gh_id, interval_s in gh_intervals.items():
            last_rec = self._last_recommend_at.get(gh_id)
            if last_rec is not None and (now - last_rec).total_seconds() < interval_s:
                continue
            try:
                await self.run_recommendation_for_greenhouse(session, gh_id, now=now)
            except Exception:
                log.exception("Lỗi suy luận crop_recommendation cho greenhouse %s", gh_id)
