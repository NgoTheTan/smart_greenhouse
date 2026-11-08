"""Rule & Control Engine: hysteresis, rủi ro nấm, interlock, auto/manual, fixed/adaptive."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import aiomqtt
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.crop_templates import DEFAULT_DEMO_PARAMS
from core.models import (
    ActuatorLog,
    Alert,
    Command,
    CropProfile,
    Gateway,
    Greenhouse,
    MlModel,
    Reading,
    Zone,
)
from core.pubsub import CHANNEL_WORKER, pg_notify
from core.vpd import calc_risk_heat, calc_risk_vpd_low
from worker.alerts import raise_alert, resolve_alert
from worker.commands import dispatch_pending_commands
from worker.shadow import ensure_device_state

log = logging.getLogger("worker.rules")


@dataclass
class ZoneRuleState:
    fungal_minutes: float = 0.0
    vpd_low_streak_s: float = 0.0
    soil_low_streak_s: float = 0.0
    last_sample_epoch: float | None = None
    consecutive_ok_samples: int = 0
    last_valid_temp: float | None = None
    last_valid_rh: float | None = None
    last_valid_vpd: float | None = None
    last_valid_ts: datetime | None = None


@dataclass
class GreenhouseRuleState:
    fan_on_since: datetime | None = None
    fan_auto_reason: str | None = None
    mist_lockout_until: datetime | None = None
    last_mist_end_at: datetime | None = None
    last_pump_end_at: dict[str, datetime] = field(default_factory=dict)
    pump_hourly_runs: dict[str, list[tuple[datetime, int]]] = field(default_factory=dict)
    soil_settle_until: dict[str, datetime] = field(default_factory=dict)


def _sum_recent_duration(
    runs: list[tuple[datetime, int]],
    now: datetime,
    window_s: int = 3600,
) -> int:
    cutoff = now - timedelta(seconds=window_s)
    return sum(d for end_t, d in runs if end_t >= cutoff)


class RuleEngine:
    def __init__(self) -> None:
        self._zone_states: dict[uuid.UUID, ZoneRuleState] = {}
        self._gh_states: dict[uuid.UUID, GreenhouseRuleState] = {}

    def get_zone_state(self, zone_id: uuid.UUID) -> ZoneRuleState:
        st = self._zone_states.get(zone_id)
        if st is None:
            st = ZoneRuleState()
            self._zone_states[zone_id] = st
        return st

    def get_gh_state(self, gh_id: uuid.UUID) -> GreenhouseRuleState:
        st = self._gh_states.get(gh_id)
        if st is None:
            st = GreenhouseRuleState()
            self._gh_states[gh_id] = st
        return st

    async def warm_up(self, session: AsyncSession, window_minutes: int = 60) -> None:
        """Dựng lại trạng thái tích luỹ rủi ro và lịch sử bật actuator từ DB (spec 3.2)."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=window_minutes)

        zones = (await session.execute(select(Zone))).scalars().all()
        for z in zones:
            z_state = self.get_zone_state(z.id)
            readings = (
                await session.execute(
                    select(Reading)
                    .where(Reading.zone_id == z.id, Reading.ts >= cutoff)
                    .order_by(Reading.ts.asc())
                )
            ).scalars().all()

            for r in readings:
                if r.quality == "ok":
                    z_state.last_valid_temp = r.air_temp
                    z_state.last_valid_rh = r.air_rh
                    z_state.last_valid_vpd = r.vpd
                    z_state.last_valid_ts = r.ts
                    z_state.consecutive_ok_samples += 1
                else:
                    z_state.consecutive_ok_samples = 0

        # Lấy lịch sử actuator gần đây
        ghs = (await session.execute(select(Greenhouse))).scalars().all()
        for gh in ghs:
            gh_state = self.get_gh_state(gh.id)
            logs = (
                await session.execute(
                    select(ActuatorLog)
                    .where(ActuatorLog.greenhouse_id == gh.id, ActuatorLog.created_at >= cutoff)
                    .order_by(ActuatorLog.created_at.asc())
                )
            ).scalars().all()

            for log_entry in logs:
                act = log_entry.actuator
                dur = log_entry.duration_s or 0
                end_t = log_entry.created_at + timedelta(seconds=dur)
                if act.startswith("pump_"):
                    gh_state.last_pump_end_at[act] = end_t
                    gh_state.pump_hourly_runs.setdefault(act, []).append((end_t, dur))
                elif act == "mist":
                    gh_state.last_mist_end_at = end_t
                elif act == "fan" and log_entry.action == "on":
                    gh_state.fan_on_since = log_entry.created_at

        log.info("Warmed up RuleEngine for %d zones, %d greenhouses", len(zones), len(ghs))

    async def _has_pending_command(
        self,
        session: AsyncSession,
        greenhouse_id: uuid.UUID,
        actuator: str,
    ) -> bool:
        stmt = (
            select(Command.id)
            .where(
                Command.greenhouse_id == greenhouse_id,
                Command.actuator == actuator,
                Command.status.in_(["pending", "sent"]),
            )
            .limit(1)
        )
        return (await session.execute(stmt)).first() is not None

    async def _create_command(
        self,
        session: AsyncSession,
        client: aiomqtt.Client | None,
        greenhouse_id: uuid.UUID,
        actuator: str,
        action: str,
        duration_s: int | None,
        reason: str,
        now: datetime,
        source: str = "auto",
    ) -> Command:
        ttl = (duration_s or 10) + 15
        cmd = Command(
            id=uuid.uuid4(),
            greenhouse_id=greenhouse_id,
            actuator=actuator,
            action=action,
            duration_s=duration_s,
            source=source,
            reason=reason,
            status="pending",
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        session.add(cmd)
        await session.flush()

        log.info(
            "Created auto command %s for gh %s: %s %s (dur=%ss, reason=%s)",
            cmd.id,
            greenhouse_id,
            actuator,
            action,
            duration_s,
            reason,
        )

        await pg_notify(
            session,
            CHANNEL_WORKER,
            {"type": "command_created", "cmd_id": str(cmd.id)},
        )

        if client is not None:
            try:
                await dispatch_pending_commands(client, session, command_id=cmd.id)
            except Exception:  # noqa: BLE001
                log.exception("Lỗi dispatch command ngay lập tức qua MQTT: %s", cmd.id)

        return cmd

    async def evaluate_zone_telemetry(
        self,
        session: AsyncSession,
        zone_id: uuid.UUID,
        greenhouse_id: uuid.UUID,
        farm_id: uuid.UUID,
        reading: Reading,
        client: aiomqtt.Client | None = None,
        now: datetime | None = None,
    ) -> None:
        """Đánh giá toàn bộ tập luật khi nhận một bản tin telemetry mới từ một zone (spec 6.4)."""
        now = now or datetime.now(UTC)
        z_state = self.get_zone_state(zone_id)
        gh_state = self.get_gh_state(greenhouse_id)

        # Lấy Zone, Greenhouse, Gateway, CropProfile
        row = (
            await session.execute(
                select(Zone, Greenhouse, Gateway, CropProfile)
                .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
                .outerjoin(Gateway, Gateway.greenhouse_id == Greenhouse.id)
                .outerjoin(CropProfile, Zone.crop_profile_id == CropProfile.id)
                .where(Zone.id == zone_id)
            )
        ).first()
        if row is None:
            return

        zone, _gh, gw, profile = row
        params = profile.parameters_json if profile is not None else DEFAULT_DEMO_PARAMS
        sample_interval_s = float(params.get("sample_interval_s", 60))

        # 1. Xử lý dữ liệu lỗi A1 & Mất cảm biến (spec mục 4)
        if reading.quality != "ok":
            z_state.consecutive_ok_samples = 0
            fault_payload = {
                "quality": reading.quality,
                "soil_raw": reading.soil_raw,
                "air_temp": reading.air_temp,
                "air_rh": reading.air_rh,
            }
            await raise_alert(
                session=session,
                greenhouse_id=greenhouse_id,
                zone_id=zone_id,
                alert_type="SENSOR_FAULT",
                severity="warning",
                dedupe_key=f"SENSOR_FAULT:{zone_id}",
                payload=fault_payload,
                now=now,
            )
            log.warning(
                "Zone %s có quality=%s -> bỏ qua điều khiển tưới cho zone",
                zone_id,
                reading.quality,
            )
            # Nếu cảm biến khí lỗi, thử fallback sang zone lân cận để đánh giá quạt/ẩm
            await self._evaluate_greenhouse_climate(
                session, greenhouse_id, client, now=now
            )
            return

        # Dữ liệu chất lượng OK
        z_state.consecutive_ok_samples += 1
        z_state.last_valid_temp = reading.air_temp
        z_state.last_valid_rh = reading.air_rh
        z_state.last_valid_vpd = reading.vpd
        z_state.last_valid_ts = reading.ts

        # Nếu đang có alert SENSOR_FAULT mở và đã nhận >= 2 mẫu ok liên tiếp -> auto resolve
        if z_state.consecutive_ok_samples >= 2:
            await resolve_alert(session, f"SENSOR_FAULT:{zone_id}", now=now)

        # 2. Tích luỹ fungal_minutes và vpd_low_streak_s
        cur_epoch = reading.ts.timestamp()
        if z_state.last_sample_epoch is not None:
            dt_s = max(0.0, cur_epoch - z_state.last_sample_epoch)
        else:
            dt_s = sample_interval_s
        z_state.last_sample_epoch = cur_epoch

        dt_min = min(dt_s, 3.0 * sample_interval_s) / 60.0

        disease_cfg = params.get("disease", {})
        risk_cfg = params.get("risk", {})
        vpd_cfg = params.get("vpd", {})
        failsafe_cfg = params.get("failsafe", {})
        soil_pct_cfg = params.get("soil_moisture_pct", {})

        # Tích luỹ điều kiện nấm
        temp_range = disease_cfg.get("temp_range_c", [18.0, 26.0])
        rh_gt = float(disease_cfg.get("rh_gt", 90.0))
        air_t = reading.air_temp if reading.air_temp is not None else 25.0
        air_rh = reading.air_rh if reading.air_rh is not None else 70.0
        vpd_val = reading.vpd if reading.vpd is not None else 1.0

        if air_rh >= rh_gt and temp_range[0] <= air_t <= temp_range[1]:
            z_state.fungal_minutes += dt_min
        else:
            z_state.fungal_minutes = max(0.0, z_state.fungal_minutes - 2.0 * dt_min)

        # Tích luỹ vpd_low_streak_s
        vpd_low_crit = float(vpd_cfg.get("low_crit", 0.4))
        vpd_low_off = float(vpd_cfg.get("low_off", 0.6))
        if vpd_val < vpd_low_crit:
            z_state.vpd_low_streak_s += dt_s
        else:
            z_state.vpd_low_streak_s = 0.0

        # Cảnh báo DISEASE_RISK
        fungal_alert_threshold = float(disease_cfg.get("fungal_minutes_alert", 45.0))
        vpd_low_dur_s = float(risk_cfg.get("vpd_low_duration_min", 30.0)) * 60.0

        disease_triggered = (
            z_state.fungal_minutes >= fungal_alert_threshold
            or z_state.vpd_low_streak_s >= vpd_low_dur_s
        )
        if disease_triggered:
            await raise_alert(
                session=session,
                greenhouse_id=greenhouse_id,
                zone_id=zone_id,
                alert_type="DISEASE_RISK",
                severity="critical",
                dedupe_key=f"DISEASE_RISK:{zone_id}",
                payload={
                    "vpd": vpd_val,
                    "air_rh": air_rh,
                    "air_temp": air_t,
                    "fungal_minutes": round(z_state.fungal_minutes, 1),
                    "vpd_low_streak_s": round(z_state.vpd_low_streak_s, 0),
                },
                now=now,
            )
        elif vpd_val >= vpd_low_off and z_state.fungal_minutes < fungal_alert_threshold * 0.5:
            await resolve_alert(session, f"DISEASE_RISK:{zone_id}", now=now)

        # Cảnh báo HEAT_STRESS
        temp_crit_high = float(failsafe_cfg.get("temp_critical_high_c", 38.0))
        if air_t >= temp_crit_high:
            await raise_alert(
                session=session,
                greenhouse_id=greenhouse_id,
                zone_id=zone_id,
                alert_type="HEAT_STRESS",
                severity="critical",
                dedupe_key=f"HEAT_STRESS:{zone_id}",
                payload={"air_temp": air_t, "threshold": temp_crit_high},
                now=now,
            )
        elif air_t <= temp_crit_high - 2.0:
            await resolve_alert(session, f"HEAT_STRESS:{zone_id}", now=now)

        # Cảnh báo SOIL_DRY
        soil_crit_low = float(failsafe_cfg.get("soil_moisture_critical_low_pct", 30.0))
        soil_min = float(soil_pct_cfg.get("min", 55.0))
        soil_m = reading.soil_moisture

        if soil_m is not None:
            if soil_m < soil_crit_low:
                z_state.soil_low_streak_s += dt_s
                if z_state.soil_low_streak_s >= 3.0 * sample_interval_s:
                    await raise_alert(
                        session=session,
                        greenhouse_id=greenhouse_id,
                        zone_id=zone_id,
                        alert_type="SOIL_DRY",
                        severity="warning",
                        dedupe_key=f"SOIL_DRY:{zone_id}",
                        payload={"soil_moisture": soil_m, "threshold": soil_crit_low},
                        now=now,
                    )
            else:
                z_state.soil_low_streak_s = 0.0

            if soil_m >= soil_min:
                await resolve_alert(session, f"SOIL_DRY:{zone_id}", now=now)

        # 3. Đánh giá tưới nước cho Zone (nếu Gateway online)
        dev_state = await ensure_device_state(session, greenhouse_id)
        gw_online = gw.online if gw is not None else False
        if gw_online:
            await self._evaluate_irrigation(
                session=session,
                client=client,
                zone=zone,
                greenhouse_id=greenhouse_id,
                reading=reading,
                params=params,
                dev_state=dev_state,
                gh_state=gh_state,
                now=now,
            )

        # 4. Đánh giá Quạt và Máy tạo ẩm chung cho cả Nhà kính
        if gw_online:
            await self._evaluate_greenhouse_climate(
                session=session,
                greenhouse_id=greenhouse_id,
                client=client,
                now=now,
            )

    async def _evaluate_irrigation(
        self,
        session: AsyncSession,
        client: aiomqtt.Client | None,
        zone: Zone,
        greenhouse_id: uuid.UUID,
        reading: Reading,
        params: dict[str, Any],
        dev_state: Any,
        gh_state: GreenhouseRuleState,
        now: datetime,
    ) -> None:
        """Đánh giá luật tưới nước cho từng zone (spec 5.1)."""
        soil_m = reading.soil_moisture
        if soil_m is None:
            return

        channel = zone.pump_channel or zone.zone_index
        pump_actuator = f"pump_{channel}"

        # Kiểm tra chế độ điều khiển
        modes = dev_state.desired.get("modes", {})
        if modes.get(pump_actuator, "auto") != "auto":
            return

        # Kiểm tra nếu đang có lệnh pending/sent cho bơm này
        if await self._has_pending_command(session, greenhouse_id, pump_actuator):
            return

        soil_pct_cfg = params.get("soil_moisture_pct", {})
        irr_cfg = params.get("irrigation", {})
        soil_min = float(soil_pct_cfg.get("min", 55.0))
        soil_max = float(soil_pct_cfg.get("max", 75.0))
        max_run_s = int(irr_cfg.get("max_run_s", 60))
        min_gap_s = int(irr_cfg.get("min_gap_s", 300))
        soil_settle_s = int(irr_cfg.get("soil_settle_s", 180))
        max_total_s_per_hour = int(irr_cfg.get("max_total_s_per_hour", 300))

        reported_acts = dev_state.reported.get("actuators", {})
        cur_status = reported_acts.get(pump_actuator, "off")

        # Hysteresis TẮT SỚM: đang on và ẩm đất đã đạt >= soil_max
        if cur_status == "on":
            if soil_m >= soil_max:
                await self._create_command(
                    session=session,
                    client=client,
                    greenhouse_id=greenhouse_id,
                    actuator=pump_actuator,
                    action="off",
                    duration_s=None,
                    reason=f"soil_reached_max:{soil_m:.1f}>={soil_max}",
                    now=now,
                )
            return

        # Điều kiện BẬT: soil_m < soil_min và đang off
        if soil_m < soil_min and cur_status == "off":
            # Kiểm tra thời gian chờ đất thấm (soil settle)
            settle_until = gh_state.soil_settle_until.get(pump_actuator)
            if settle_until and now < settle_until:
                log.debug("Bỏ qua tưới %s do đang trong thời gian soil_settle_s", pump_actuator)
                return

            # Kiểm tra khoảng nghỉ tối thiểu (min gap)
            last_end = gh_state.last_pump_end_at.get(pump_actuator)
            if last_end and now < last_end + timedelta(seconds=min_gap_s):
                log.debug("Bỏ qua tưới %s do chưa qua min_gap_s", pump_actuator)
                return

            # Kiểm tra tổng thời gian chạy trong 1 giờ
            runs = gh_state.pump_hourly_runs.get(pump_actuator, [])
            used_s = _sum_recent_duration(runs, now, 3600)
            if used_s + max_run_s > max_total_s_per_hour:
                log.warning(
                    "Bỏ qua tưới %s: đã dùng %ss/h, vượt max_total_s_per_hour=%ss",
                    pump_actuator,
                    used_s,
                    max_total_s_per_hour,
                )
                return

            # Tính duration_s: Fixed vs Adaptive
            strategy = zone.control_strategy
            duration_s = max_run_s
            reason = f"fixed_soil_low:{soil_m:.1f}<{soil_min}"

            if strategy == "adaptive":
                model_stmt = (
                    select(MlModel)
                    .where(
                        MlModel.zone_id == zone.id,
                        MlModel.task == "pump_response",
                        MlModel.is_active.is_(True),
                    )
                    .order_by(desc(MlModel.trained_at))
                    .limit(1)
                )
                model = (await session.execute(model_stmt)).scalar_one_or_none()

                gain = 0.0
                if model and model.metrics:
                    gain = float(model.metrics.get("pump_gain_pct_per_s", 0.0))

                if model is None or model.n_samples < 5 or gain <= 0.0:
                    duration_s = max_run_s
                    reason = f"adaptive_fallback_fixed:{soil_m:.1f}<{soil_min}"
                else:
                    target_soil = (soil_min + soil_max) / 2.0
                    raw_d = (target_soil - soil_m) / gain
                    duration_s = int(round(max(3, min(raw_d, max_run_s))))
                    reason = f"adaptive_gain:{gain:.3f}_target:{target_soil:.1f}"

            await self._create_command(
                session=session,
                client=client,
                greenhouse_id=greenhouse_id,
                actuator=pump_actuator,
                action="on",
                duration_s=duration_s,
                reason=reason,
                now=now,
            )

            # Cập nhật state dự kiến
            end_est = now + timedelta(seconds=duration_s)
            gh_state.last_pump_end_at[pump_actuator] = end_est
            gh_state.soil_settle_until[pump_actuator] = end_est + timedelta(
                seconds=soil_settle_s
            )
            gh_state.pump_hourly_runs.setdefault(pump_actuator, []).append(
                (end_est, duration_s)
            )

    async def _evaluate_greenhouse_climate(
        self,
        session: AsyncSession,
        greenhouse_id: uuid.UUID,
        client: aiomqtt.Client | None,
        now: datetime,
    ) -> None:
        """Đánh giá Quạt thông gió và Máy tạo ẩm trên toàn bộ nhà kính (spec 5.2, 5.3)."""
        gh_state = self.get_gh_state(greenhouse_id)
        dev_state = await ensure_device_state(session, greenhouse_id)
        modes = dev_state.desired.get("modes", {})
        reported_acts = dev_state.reported.get("actuators", {})
        cur_fan = reported_acts.get("fan", "off")
        cur_mist = reported_acts.get("mist", "off")

        # Lấy tất cả các zone của nhà kính
        zones = (
            await session.execute(
                select(Zone, CropProfile)
                .outerjoin(CropProfile, Zone.crop_profile_id == CropProfile.id)
                .where(Zone.greenhouse_id == greenhouse_id)
            )
        ).all()
        if not zones:
            return

        # Lấy alert DISEASE_RISK đang mở của các zone thuộc greenhouse này
        open_disease_alerts = (
            await session.execute(
                select(Alert.zone_id).where(
                    Alert.greenhouse_id == greenhouse_id,
                    Alert.alert_type == "DISEASE_RISK",
                    Alert.state != "resolved",
                )
            )
        ).scalars().all()
        disease_alert_zone_ids = set(open_disease_alerts)

        should_turn_on_fan = False
        fan_trigger_reason = ""
        dangerous_zone: Zone | None = None
        dangerous_params: dict[str, Any] = DEFAULT_DEMO_PARAMS
        max_risk_score = -1.0

        for z, profile in zones:
            z_state = self.get_zone_state(z.id)
            params = (
                profile.parameters_json if profile is not None else DEFAULT_DEMO_PARAMS
            )

            # Lấy dữ liệu khí hợp lệ gần nhất
            air_t = z_state.last_valid_temp
            air_rh = z_state.last_valid_rh
            vpd_val = z_state.last_valid_vpd
            if air_t is None or air_rh is None or vpd_val is None:
                continue

            vpd_cfg = params.get("vpd", {})
            temp_c_cfg = params.get("temp_c", {})
            risk_cfg = params.get("risk", {})
            vpd_low_crit = float(vpd_cfg.get("low_crit", 0.4))
            vpd_high_crit = float(vpd_cfg.get("high_crit", 1.4))
            vpd_opt = vpd_cfg.get("optimal", [0.8, 1.2])
            temp_opt = temp_c_cfg.get("optimal", [20.0, 26.0])
            temp_max_opt = float(temp_opt[1])
            vpd_low_dur_s = float(risk_cfg.get("vpd_low_duration_min", 30.0)) * 60.0

            # Tính điểm rủi ro chuẩn hoá theo Phụ lục B
            r_vpd = calc_risk_vpd_low(vpd_val, vpd_opt[0], vpd_low_crit)
            r_heat = calc_risk_heat(air_t, temp_max_opt, 38.0)
            risk_score = max(r_vpd, r_heat)
            if risk_score > max_risk_score:
                max_risk_score = risk_score
                dangerous_zone = z
                dangerous_params = params

            # Điều kiện bật quạt:
            # 1. vpd < low_crit kéo dài
            # 2. Hoặc đang có alert DISEASE_RISK mở
            # 3. Hoặc nhiệt độ > optimal max
            c1 = z_state.vpd_low_streak_s >= vpd_low_dur_s
            c2 = z.id in disease_alert_zone_ids
            c3 = air_t > temp_max_opt

            if (c1 or c2 or c3):
                # Side-effect guard: không bật quạt nếu VPD của zone đang > high_crit
                if vpd_val <= vpd_high_crit:
                    should_turn_on_fan = True
                    if c2:
                        fan_trigger_reason = f"disease_risk_alert_zone_{z.zone_index}"
                    elif c1:
                        fan_trigger_reason = f"vpd_low_streak:{z_state.vpd_low_streak_s:.0f}s"
                    else:
                        fan_trigger_reason = f"heat_stress:{air_t:.1f}>{temp_max_opt}"

        fan_cfg = dangerous_params.get("fan", {})
        mist_cfg = dangerous_params.get("mist", {})
        fan_min_on_s = int(fan_cfg.get("min_on_s", 180))
        fan_max_on_s = int(fan_cfg.get("max_on_s", 600))
        mist_lockout_s = int(mist_cfg.get("lockout_s", 300))
        mist_max_on_s = int(mist_cfg.get("max_on_s", 120))

        # --- INTERLOCK AN TOÀN: Ép tắt Mist khi Quạt chuẩn bị bật vì rủi ro (Kịch bản A) ---
        if should_turn_on_fan and cur_mist == "on":
            gh_state.mist_lockout_until = now + timedelta(seconds=mist_lockout_s)
            log.warning(
                "INTERLOCK: Quạt tự bật vì rủi ro -> Ép tắt máy tạo ẩm (kể cả manual) cho gh %s",
                greenhouse_id,
            )
            # Không kiểm tra has_pending_command cho mist off để đảm bảo lệnh an toàn được ưu tiên
            await self._create_command(
                session=session,
                client=client,
                greenhouse_id=greenhouse_id,
                actuator="mist",
                action="off",
                duration_s=None,
                reason=f"interlock_fan_on_lockout_{mist_lockout_s}s",
                now=now,
                source="auto",
            )

        # --- ĐIỀU KHIỂN QUẠT (FAN) ---
        fan_mode = modes.get("fan", "auto")
        if fan_mode == "auto":
            has_fan_cmd = await self._has_pending_command(session, greenhouse_id, "fan")
            if not has_fan_cmd:
                if should_turn_on_fan and cur_fan == "off":
                    # BẬT QUẠT
                    duration_s = fan_min_on_s
                    reason = f"auto_fan_on:{fan_trigger_reason}"

                    if dangerous_zone and dangerous_zone.control_strategy == "adaptive":
                        model_stmt = (
                            select(MlModel)
                            .where(
                                MlModel.zone_id == dangerous_zone.id,
                                MlModel.task == "fan_response",
                                MlModel.is_active.is_(True),
                            )
                            .order_by(desc(MlModel.trained_at))
                            .limit(1)
                        )
                        model = (await session.execute(model_stmt)).scalar_one_or_none()
                        rate = 0.0
                        if model and model.metrics:
                            rate = float(model.metrics.get("fan_vpd_rate_kpa_per_s", 0.0))

                        if model and model.n_samples >= 5 and rate > 0.0:
                            z_st = self.get_zone_state(dangerous_zone.id)
                            vpd_curr = z_st.last_valid_vpd or 0.4
                            vpd_low_off = float(
                                dangerous_params.get("vpd", {}).get("low_off", 0.6)
                            )
                            raw_dur = (vpd_low_off - vpd_curr) / rate
                            duration_s = int(
                                round(max(fan_min_on_s, min(raw_dur, fan_max_on_s)))
                            )
                            reason = f"adaptive_rate:{rate:.4f}"

                    await self._create_command(
                        session=session,
                        client=client,
                        greenhouse_id=greenhouse_id,
                        actuator="fan",
                        action="on",
                        duration_s=duration_s,
                        reason=reason,
                        now=now,
                    )
                    gh_state.fan_on_since = now
                    gh_state.fan_auto_reason = fan_trigger_reason

                elif cur_fan == "on" and not should_turn_on_fan:
                    # Kiểm tra hysteresis TẮT QUẠT:
                    # Đã chạy >= fan_min_on_s và mọi zone đều đạt điều kiện ổn định
                    can_turn_off = True
                    if gh_state.fan_on_since is not None:
                        if now - gh_state.fan_on_since < timedelta(seconds=fan_min_on_s):
                            can_turn_off = False

                    if can_turn_off and not disease_alert_zone_ids:
                        # Kiểm tra mọi zone vpd >= low_off và air_temp <= temp_max_opt
                        for z, prof in zones:
                            z_st = self.get_zone_state(z.id)
                            p = (
                                prof.parameters_json
                                if prof is not None
                                else DEFAULT_DEMO_PARAMS
                            )
                            l_off = float(p.get("vpd", {}).get("low_off", 0.6))
                            t_max = float(p.get("temp_c", {}).get("optimal", [20, 26])[1])
                            if z_st.last_valid_vpd is not None and z_st.last_valid_vpd < l_off:
                                can_turn_off = False
                                break
                            if z_st.last_valid_temp is not None and z_st.last_valid_temp > t_max:
                                can_turn_off = False
                                break

                        if can_turn_off:
                            await self._create_command(
                                session=session,
                                client=client,
                                greenhouse_id=greenhouse_id,
                                actuator="fan",
                                action="off",
                                duration_s=None,
                                reason="climate_stabilized",
                                now=now,
                            )
                            gh_state.fan_on_since = None
                            gh_state.fan_auto_reason = None

        # --- ĐIỀU KHIỂN MÁY TẠO ẨM (MIST) ---
        mist_mode = modes.get("mist", "auto")
        if mist_mode == "auto":
            has_mist_cmd = await self._has_pending_command(session, greenhouse_id, "mist")
            if not has_mist_cmd:
                # Kiểm tra có zone nào quá khô (VPD > high_crit)
                any_zone_dry = False
                for z, prof in zones:
                    z_st = self.get_zone_state(z.id)
                    p = prof.parameters_json if prof is not None else DEFAULT_DEMO_PARAMS
                    h_crit = float(p.get("vpd", {}).get("high_crit", 1.4))
                    if z_st.last_valid_vpd is not None and z_st.last_valid_vpd > h_crit:
                        any_zone_dry = True
                        break

                is_locked_out = (
                    gh_state.mist_lockout_until is not None
                    and now < gh_state.mist_lockout_until
                )

                if (
                    any_zone_dry
                    and cur_mist == "off"
                    and cur_fan == "off"
                    and not is_locked_out
                ):
                    await self._create_command(
                        session=session,
                        client=client,
                        greenhouse_id=greenhouse_id,
                        actuator="mist",
                        action="on",
                        duration_s=mist_max_on_s,
                        reason="vpd_too_high",
                        now=now,
                    )
                    gh_state.last_mist_end_at = now + timedelta(seconds=mist_max_on_s)
                elif cur_mist == "on" and not any_zone_dry:
                    await self._create_command(
                        session=session,
                        client=client,
                        greenhouse_id=greenhouse_id,
                        actuator="mist",
                        action="off",
                        duration_s=None,
                        reason="vpd_recovered",
                        now=now,
                    )

    async def tick_5s(
        self,
        session: AsyncSession,
        client: aiomqtt.Client | None = None,
        now: datetime | None = None,
    ) -> None:
        """Quét định kỳ 5s để kiểm tra hết hạn quạt/máy tạo ẩm hoặc mất cảm biến kéo dài."""
        now = now or datetime.now(UTC)
        # Quét kiểm tra khí hậu cho các nhà kính đang có quạt hoặc mist đang chạy
        gh_ids = list(self._gh_states.keys())
        for gh_id in gh_ids:
            try:
                await self._evaluate_greenhouse_climate(session, gh_id, client, now)
            except Exception:  # noqa: BLE001
                log.exception("Lỗi khi tick_5s khí hậu nhà kính %s", gh_id)
