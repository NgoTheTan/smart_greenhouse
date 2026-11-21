"""Unit tests cho Rule & Control Engine (spec mục 6.4, 7.1, 15)."""

import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from core.crop_templates import DEFAULT_DEMO_PARAMS
from core.models import CropProfile, DeviceState, Gateway, Greenhouse, Reading, Zone
from worker.rules import RuleEngine


def _run_coro(coro: Coroutine[Any, Any, Any]) -> Any:
    """Chạy coroutine thuần bộ nhớ không cần khởi tạo socket loopback của ProactorEventLoop."""
    try:
        while True:
            coro.send(None)
    except StopIteration as stop:
        return stop.value
    finally:
        coro.close()


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def scalar_one_or_none(self) -> Any:
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        if self._value is None:
            return []
        return self._value if isinstance(self._value, list) else [self._value]


class FakeAsyncSession:
    def __init__(self, execute_fn=None, get_fn=None, add_fn=None) -> None:
        self._execute_fn = execute_fn or (lambda s: _FakeResult(None))
        self._get_fn = get_fn or (lambda m, pk: None)
        self._add_fn = add_fn or (lambda o: None)
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        self._add_fn(obj)

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        return self._execute_fn(stmt)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None

    async def get(self, model: Any, pk: Any) -> Any:
        return self._get_fn(model, pk)


def _make_context(
    pump_status: str = "off",
    fan_status: str = "off",
    pump_mode: Any = "auto",
    fan_mode: Any = "auto",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, Zone, Greenhouse, Gateway, CropProfile, DeviceState]:
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()

    prof = CropProfile(
        id=uuid.uuid4(),
        farm_id=farm_id,
        crop_code="tomato_cherry",
        crop_name="Cà chua Demo",
        schema_version=2,
        parameters_json=DEFAULT_DEMO_PARAMS,
    )
    zone = Zone(
        id=zone_id,
        greenhouse_id=gh_id,
        zone_index=1,
        name="Zone 1",
        pump_channel=1,
        crop_profile_id=prof.id,
    )
    gh = Greenhouse(id=gh_id, farm_id=farm_id, name="Nhà kính 1")
    gw = Gateway(
        id=uuid.uuid4(),
        greenhouse_id=gh_id,
        mqtt_username="gw_test",
        is_simulated=True,
        online=True,
    )
    dev_state = DeviceState(
        greenhouse_id=gh_id,
        desired={"modes": {"pump_1": pump_mode, "fan": fan_mode}},
        reported={"actuators": {"pump_1": pump_status, "fan": fan_status}},
    )
    return farm_id, gh_id, zone_id, zone, gh, gw, prof, dev_state


def test_fixed_irrigation_hysteresis() -> None:
    engine = RuleEngine()
    farm_id, gh_id, zone_id, zone, gh, gw, prof, dev_state = _make_context(pump_status="off")

    created_commands = []

    def _execute(stmt):
        s_str = str(stmt)
        if "FROM zones" in s_str:
            if "greenhouses" in s_str:
                return _FakeResult((zone, gh, gw, prof))
            return _FakeResult([(zone, prof)])
        if "FROM device_state" in s_str:
            return _FakeResult(dev_state)
        if "FROM commands" in s_str:
            return _FakeResult(None)
        if "FROM alerts" in s_str:
            return _FakeResult(None)
        if "FROM crop_profiles" in s_str:
            return _FakeResult(prof)
        return _FakeResult(None)

    def _get(model, pk):
        if model == DeviceState:
            return dev_state
        if model == Greenhouse:
            return gh
        if model == Zone:
            return zone
        return None

    session = FakeAsyncSession(
        execute_fn=_execute,
        get_fn=_get,
        add_fn=lambda obj: created_commands.append(obj),
    )

    now = datetime(2026, 11, 8, 10, 0, 0, tzinfo=UTC)

    # 1. Ẩm đất 50% < min 55% -> BẬT BƠM
    reading_dry = Reading(
        zone_id=zone_id,
        ts=now,
        air_temp=24.0,
        air_rh=65.0,
        vpd=1.0,
        soil_moisture=50.0,
        quality="ok",
    )
    _run_coro(
        engine.evaluate_zone_telemetry(
            session, zone_id, gh_id, farm_id, reading_dry, now=now
        )
    )

    pump_cmds = [c for c in created_commands if getattr(c, "actuator", None) == "pump_1"]
    assert len(pump_cmds) == 1
    assert pump_cmds[0].action == "on"
    assert pump_cmds[0].duration_s == 15  # max_run_s trong DEFAULT_DEMO_PARAMS
    assert "soil_low:" in pump_cmds[0].reason

    # 2. Hysteresis TẮT SỚM: khi bơm đang on và độ ẩm vượt >= 75% -> TẮT BƠM
    created_commands.clear()
    dev_state.reported["actuators"]["pump_1"] = "on"

    reading_wet = Reading(
        zone_id=zone_id,
        ts=now + timedelta(seconds=30),
        air_temp=24.0,
        air_rh=65.0,
        vpd=1.0,
        soil_moisture=76.0,
        quality="ok",
    )
    _run_coro(
        engine.evaluate_zone_telemetry(
            session, zone_id, gh_id, farm_id, reading_wet, now=now + timedelta(seconds=30)
        )
    )

    off_cmds = [c for c in created_commands if getattr(c, "actuator", None) == "pump_1"]
    assert len(off_cmds) == 1
    assert off_cmds[0].action == "off"
    assert "soil_reached_max" in off_cmds[0].reason


def test_irrigation_safety_constraints() -> None:
    engine = RuleEngine()
    farm_id, gh_id, zone_id, zone, gh, gw, prof, dev_state = _make_context()

    created_commands = []

    def _execute(stmt):
        s = str(stmt)
        if "FROM zones" in s:
            if "greenhouses" in s:
                return _FakeResult((zone, gh, gw, prof))
            return _FakeResult([(zone, prof)])
        if "FROM device_state" in s:
            return _FakeResult(dev_state)
        return _FakeResult(None)

    def _get(model, pk):
        if model == DeviceState:
            return dev_state
        if model == Greenhouse:
            return gh
        if model == Zone:
            return zone
        return None

    session = FakeAsyncSession(
        execute_fn=_execute,
        get_fn=_get,
        add_fn=lambda obj: created_commands.append(obj),
    )

    now = datetime(2026, 11, 8, 10, 0, 0, tzinfo=UTC)
    gh_state = engine.get_gh_state(gh_id)

    # 1. Chặn bởi soil_settle_until
    gh_state.soil_settle_until["pump_1"] = now + timedelta(seconds=120)
    reading = Reading(
        zone_id=zone_id,
        ts=now,
        air_temp=24.0,
        air_rh=65.0,
        vpd=1.0,
        soil_moisture=45.0,
        quality="ok",
    )
    _run_coro(engine.evaluate_zone_telemetry(session, zone_id, gh_id, farm_id, reading, now=now))
    assert len([c for c in created_commands if getattr(c, "actuator", None) == "pump_1"]) == 0

    # 2. Chặn bởi min_gap_s (vừa kết thúc lần tưới trước cách 60s, min_gap_s = 300s)
    gh_state.soil_settle_until.clear()
    gh_state.last_pump_end_at["pump_1"] = now - timedelta(seconds=60)
    _run_coro(engine.evaluate_zone_telemetry(session, zone_id, gh_id, farm_id, reading, now=now))
    assert len([c for c in created_commands if getattr(c, "actuator", None) == "pump_1"]) == 0

    # 3. Chặn bởi max_total_s_per_hour (đã dùng 280s/300s tối đa)
    gh_state.last_pump_end_at.clear()
    gh_state.pump_hourly_runs["pump_1"] = [(now - timedelta(seconds=500), 280)]
    _run_coro(engine.evaluate_zone_telemetry(session, zone_id, gh_id, farm_id, reading, now=now))
    assert len([c for c in created_commands if getattr(c, "actuator", None) == "pump_1"]) == 0


def test_manual_mode_dict_blocks_auto_irrigation() -> None:
    """Chế độ manual lưu dạng dict `{"mode": "manual", "until": ...}` chặn tưới tự động."""
    engine = RuleEngine()
    until_iso = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    farm_id, gh_id, zone_id, zone, gh, gw, prof, dev_state = _make_context(
        pump_mode={"mode": "manual", "until": until_iso}
    )

    created_commands = []

    def _execute(stmt):
        s = str(stmt)
        if "FROM zones" in s:
            if "greenhouses" in s:
                return _FakeResult((zone, gh, gw, prof))
            return _FakeResult([(zone, prof)])
        if "FROM device_state" in s:
            return _FakeResult(dev_state)
        return _FakeResult(None)

    def _get(model, pk):
        if model == DeviceState:
            return dev_state
        if model == Greenhouse:
            return gh
        if model == Zone:
            return zone
        return None

    session = FakeAsyncSession(
        execute_fn=_execute,
        get_fn=_get,
        add_fn=lambda obj: created_commands.append(obj),
    )

    now = datetime(2026, 11, 8, 10, 0, 0, tzinfo=UTC)
    dry_reading = Reading(
        zone_id=zone_id,
        ts=now,
        air_temp=24.0,
        air_rh=65.0,
        vpd=1.0,
        soil_moisture=45.0,
        quality="ok",
    )
    _run_coro(
        engine.evaluate_zone_telemetry(session, zone_id, gh_id, farm_id, dry_reading, now=now)
    )
    assert not [c for c in created_commands if getattr(c, "actuator", None) == "pump_1"]


def test_scenario_a_disease_risk_activates_fan_and_high_vpd_guard() -> None:
    """Kịch bản A: Rủi ro nấm mở DISEASE_RISK & bật quạt; VPD > high_crit chặn bật quạt."""
    engine = RuleEngine()
    farm_id, gh_id, zone_id, zone, gh, gw, prof, dev_state = _make_context(
        fan_status="off",
        fan_mode="auto",
    )

    created_commands = []
    created_alerts = []

    def _execute(stmt):
        s_str = str(stmt)
        if "FROM zones" in s_str:
            if "greenhouses" in s_str:
                return _FakeResult((zone, gh, gw, prof))
            return _FakeResult([(zone, prof)])
        if "FROM device_state" in s_str:
            return _FakeResult(dev_state)
        if "FROM alerts" in s_str:
            return _FakeResult([])
        return _FakeResult(None)

    def _get(model, pk):
        if model == DeviceState:
            return dev_state
        if model == Greenhouse:
            return gh
        if model == Zone:
            return zone
        return None

    def _add(obj):
        if hasattr(obj, "actuator"):
            created_commands.append(obj)
        elif hasattr(obj, "alert_type"):
            created_alerts.append(obj)

    session = FakeAsyncSession(execute_fn=_execute, get_fn=_get, add_fn=_add)

    now = datetime(2026, 11, 8, 10, 0, 0, tzinfo=UTC)
    z_state = engine.get_zone_state(zone_id)
    # Giả lập đã tích luỹ đủ vpd_low_streak_s (>= 1800s)
    z_state.vpd_low_streak_s = 1850.0

    reading = Reading(
        zone_id=zone_id,
        ts=now,
        air_temp=22.0,
        air_rh=94.0,
        vpd=0.14,
        soil_moisture=65.0,
        quality="ok",
    )

    _run_coro(engine.evaluate_zone_telemetry(session, zone_id, gh_id, farm_id, reading, now=now))

    # 1. Mở alert DISEASE_RISK và bật quạt tự động (duration_s = fan.min_on_s = 60)
    assert any(getattr(a, "alert_type", None) == "DISEASE_RISK" for a in created_alerts)
    fan_cmds = [c for c in created_commands if c.actuator == "fan"]
    assert len(fan_cmds) == 1
    assert fan_cmds[0].action == "on"
    assert fan_cmds[0].duration_s == 60
    assert not any(c.actuator == "mist" for c in created_commands)

    # 2. Side-effect guard: khi air_t > optimal_max nhưng VPD > high_crit -> KHÔNG bật quạt
    guard_engine = RuleEngine()
    created_commands.clear()
    created_alerts.clear()
    dry_hot_reading = Reading(
        zone_id=zone_id,
        ts=now + timedelta(seconds=30),
        air_temp=30.0,
        air_rh=40.0,
        vpd=2.2,
        soil_moisture=65.0,
        quality="ok",
    )
    _run_coro(
        guard_engine.evaluate_zone_telemetry(
            session, zone_id, gh_id, farm_id, dry_hot_reading, now=now + timedelta(seconds=30)
        )
    )
    assert not any(c.actuator == "fan" for c in created_commands)
    assert not any(c.actuator == "mist" for c in created_commands)


def test_scenario_c_sensor_fault_blocks_irrigation() -> None:
    """Kịch bản C: Rút dây ẩm đất (quality != ok) -> Mở SENSOR_FAULT và KHÔNG tưới."""
    engine = RuleEngine()
    farm_id, gh_id, zone_id, zone, gh, gw, prof, dev_state = _make_context(pump_status="off")

    created_commands = []
    created_alerts = []

    def _execute(stmt):
        s = str(stmt)
        if "FROM zones" in s:
            if "greenhouses" in s:
                return _FakeResult((zone, gh, gw, prof))
            return _FakeResult([(zone, prof)])
        if "FROM device_state" in s:
            return _FakeResult(dev_state)
        return _FakeResult(None)

    def _get(model, pk):
        if model == DeviceState:
            return dev_state
        if model == Greenhouse:
            return gh
        if model == Zone:
            return zone
        return None

    def _add(obj):
        if hasattr(obj, "actuator"):
            created_commands.append(obj)
        elif hasattr(obj, "alert_type"):
            created_alerts.append(obj)

    session = FakeAsyncSession(execute_fn=_execute, get_fn=_get, add_fn=_add)

    now = datetime(2026, 11, 8, 10, 0, 0, tzinfo=UTC)

    # Rút dây: soil_raw = 0, quality = 'out_of_range'
    fault_reading = Reading(
        zone_id=zone_id,
        ts=now,
        air_temp=24.0,
        air_rh=65.0,
        vpd=1.0,
        soil_moisture=0.0,
        soil_raw=0,
        quality="out_of_range",
    )

    _run_coro(
        engine.evaluate_zone_telemetry(session, zone_id, gh_id, farm_id, fault_reading, now=now)
    )

    # 1. TUYỆT ĐỐI không có lệnh tưới nào được phát ra
    pump_cmds = [c for c in created_commands if getattr(c, "actuator", None) == "pump_1"]
    assert len(pump_cmds) == 0

    # 2. Alert SENSOR_FAULT được mở
    fault_alerts = [a for a in created_alerts if getattr(a, "alert_type", None) == "SENSOR_FAULT"]
    assert len(fault_alerts) == 1
    assert fault_alerts[0].severity == "warning"
    assert fault_alerts[0].dedupe_key == f"SENSOR_FAULT:{zone_id}"


def test_auto_light_control_hysteresis() -> None:
    """Điều khiển đèn chiếu sáng tự động theo hysteresis lux_min=100 / lux_max=150."""
    engine = RuleEngine()
    farm_id, gh_id, zone_id, zone, gh, gw, prof, dev_state = _make_context()
    dev_state.desired["modes"]["light"] = "auto"
    dev_state.reported["actuators"]["light"] = "off"

    created_commands = []

    def _execute(stmt):
        s_str = str(stmt)
        if "FROM zones" in s_str:
            if "greenhouses" in s_str:
                return _FakeResult((zone, gh, gw, prof))
            return _FakeResult([(zone, prof)])
        if "FROM device_state" in s_str:
            return _FakeResult(dev_state)
        if "FROM alerts" in s_str:
            return _FakeResult([])
        return _FakeResult(None)

    def _get(model, pk):
        if model == DeviceState:
            return dev_state
        if model == Greenhouse:
            return gh
        if model == Zone:
            return zone
        return None

    session = FakeAsyncSession(
        execute_fn=_execute,
        get_fn=_get,
        add_fn=lambda obj: created_commands.append(obj) if hasattr(obj, "actuator") else None,
    )

    now = datetime(2026, 11, 21, 10, 0, 0, tzinfo=UTC)

    # 1. lux = 60 < 100 -> BẬT đèn
    r_dark = Reading(
        zone_id=zone_id,
        ts=now,
        air_temp=24.0,
        air_rh=65.0,
        vpd=1.0,
        soil_moisture=65.0,
        lux=60.0,
        quality="ok",
    )
    _run_coro(engine.evaluate_zone_telemetry(session, zone_id, gh_id, farm_id, r_dark, now=now))
    light_cmds = [c for c in created_commands if c.actuator == "light"]
    assert len(light_cmds) == 1
    assert light_cmds[0].action == "on"
    assert light_cmds[0].duration_s == 60
    assert "auto_light_on:lux_low:" in light_cmds[0].reason

    # 2. Đang bật và lux = 120 (trong dải trễ 100..150) -> giữ nguyên trạng thái, không tắt
    created_commands.clear()
    dev_state.reported["actuators"]["light"] = "on"
    r_mid = Reading(
        zone_id=zone_id,
        ts=now + timedelta(seconds=10),
        air_temp=24.0,
        air_rh=65.0,
        vpd=1.0,
        soil_moisture=65.0,
        lux=120.0,
        quality="ok",
    )
    _run_coro(
        engine.evaluate_zone_telemetry(
            session, zone_id, gh_id, farm_id, r_mid, now=now + timedelta(seconds=10)
        )
    )
    assert not [c for c in created_commands if c.actuator == "light"]

    # 3. Đang bật và lux = 180 >= 150 -> TẮT đèn
    r_bright = Reading(
        zone_id=zone_id,
        ts=now + timedelta(seconds=20),
        air_temp=24.0,
        air_rh=65.0,
        vpd=1.0,
        soil_moisture=65.0,
        lux=180.0,
        quality="ok",
    )
    _run_coro(
        engine.evaluate_zone_telemetry(
            session, zone_id, gh_id, farm_id, r_bright, now=now + timedelta(seconds=20)
        )
    )
    off_cmds = [c for c in created_commands if c.actuator == "light"]
    assert len(off_cmds) == 1
    assert off_cmds[0].action == "off"
    assert off_cmds[0].duration_s is None
    assert "light_sufficient:" in off_cmds[0].reason


def test_auto_duration_clamped_to_60s() -> None:
    """Chế độ auto luôn giới hạn thời lượng bật bơm/quạt/đèn tối đa 60s dù profile đặt cao hơn."""
    import copy

    engine = RuleEngine()
    farm_id, gh_id, zone_id, zone, gh, gw, prof, dev_state = _make_context()
    big_params = copy.deepcopy(DEFAULT_DEMO_PARAMS)
    big_params["irrigation"]["max_run_s"] = 300
    big_params["fan"]["min_on_s"] = 300
    prof.parameters_json = big_params
    dev_state.desired["modes"]["light"] = "auto"
    dev_state.reported["actuators"]["light"] = "off"

    created_commands = []

    def _execute(stmt):
        s_str = str(stmt)
        if "FROM zones" in s_str:
            if "greenhouses" in s_str:
                return _FakeResult((zone, gh, gw, prof))
            return _FakeResult([(zone, prof)])
        if "FROM device_state" in s_str:
            return _FakeResult(dev_state)
        if "FROM alerts" in s_str:
            return _FakeResult([])
        return _FakeResult(None)

    def _get(model, pk):
        if model == DeviceState:
            return dev_state
        if model == Greenhouse:
            return gh
        if model == Zone:
            return zone
        return None

    session = FakeAsyncSession(
        execute_fn=_execute,
        get_fn=_get,
        add_fn=lambda obj: created_commands.append(obj) if hasattr(obj, "actuator") else None,
    )

    now = datetime(2026, 11, 21, 10, 40, 0, tzinfo=UTC)
    r = Reading(
        zone_id=zone_id,
        ts=now,
        air_temp=31.0,
        air_rh=65.0,
        vpd=1.1,
        soil_moisture=40.0,
        lux=50.0,
        quality="ok",
    )
    _run_coro(engine.evaluate_zone_telemetry(session, zone_id, gh_id, farm_id, r, now=now))
    assert {c.actuator for c in created_commands} == {"pump_1", "fan", "light"}
    for c in created_commands:
        assert c.duration_s == 60
