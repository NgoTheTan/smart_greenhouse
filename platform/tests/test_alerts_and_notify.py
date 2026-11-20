"""Unit tests cho Alert Service, Notification Service và REST Routers (spec 6.6, 6.7, 9)."""

import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.routers.alerts import acknowledge_alert, list_alerts
from core.models import Alert, Greenhouse, User, Zone
from worker.alerts import raise_alert, resolve_alert
from worker.notify import format_alert_body, get_alert_title, send_alert_notifications


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


def _make_get_gh(gh_id: uuid.UUID):
    return (
        lambda m, pk: Greenhouse(id=gh_id, farm_id=uuid.uuid4(), name="GH")
        if m == Greenhouse
        else None
    )


def test_alert_deduplication_and_cooldown() -> None:
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    dedupe_key = f"DISEASE_RISK:{zone_id}"

    stored_alerts = {}

    def _execute(stmt):
        s = str(stmt)
        if "FROM alerts" in s and "dedupe_key" in s:
            match = [
                a
                for a in stored_alerts.values()
                if a.dedupe_key == dedupe_key and a.state != "resolved"
            ]
            return _FakeResult(match[0] if match else None)
        return _FakeResult(None)

    session = FakeAsyncSession(
        execute_fn=_execute,
        get_fn=_make_get_gh(gh_id),
        add_fn=lambda a: stored_alerts.update({a.id: a}),
    )

    notify_calls = []

    async def fake_notify(*args, **kwargs):
        notify_calls.append((args, kwargs))
        return 1

    with patch("worker.alerts.send_alert_notifications", side_effect=fake_notify):
        t0 = datetime(2026, 11, 8, 10, 0, 0, tzinfo=UTC)

        # 1. Lần đầu tạo alert mới
        alert1, is_new1 = _run_coro(
            raise_alert(
                session, gh_id, "DISEASE_RISK", "critical", dedupe_key, zone_id=zone_id, now=t0
            )
        )
        assert is_new1 is True
        assert alert1.state == "notified"
        assert alert1.notified_at == t0
        assert len(notify_calls) == 1

        # 2. Gọi lại sau 2 phút (< cooldown 10 phút) -> không gửi thông báo nhắc
        t1 = t0 + timedelta(minutes=2)
        alert2, is_new2 = _run_coro(
            raise_alert(
                session, gh_id, "DISEASE_RISK", "critical", dedupe_key, zone_id=zone_id, now=t1
            )
        )
        assert is_new2 is False
        assert alert2.id == alert1.id
        assert alert2.notified_at == t0
        assert len(notify_calls) == 1

        # 3. Gọi lại sau 11 phút (> cooldown 10 phút) -> gửi lại thông báo nhắc
        t2 = t0 + timedelta(minutes=11)
        alert3, is_new3 = _run_coro(
            raise_alert(
                session, gh_id, "DISEASE_RISK", "critical", dedupe_key, zone_id=zone_id, now=t2
            )
        )
        assert is_new3 is False
        assert alert3.notified_at == t2
        assert len(notify_calls) == 2


def test_alert_acknowledged_suppresses_cooldown_renotify() -> None:
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    dedupe_key = f"HEAT_STRESS:{zone_id}"
    t0 = datetime(2026, 11, 8, 10, 0, 0, tzinfo=UTC)

    acked_alert = Alert(
        id=uuid.uuid4(),
        greenhouse_id=gh_id,
        zone_id=zone_id,
        alert_type="HEAT_STRESS",
        severity="critical",
        dedupe_key=dedupe_key,
        state="acknowledged",
        created_at=t0,
        notified_at=t0,
        acknowledged_at=t0 + timedelta(minutes=1),
    )

    session = FakeAsyncSession(
        execute_fn=lambda stmt: _FakeResult(acked_alert),
        get_fn=_make_get_gh(gh_id),
    )

    notify_calls = []

    async def fake_notify(*args, **kwargs):
        notify_calls.append((args, kwargs))
        return 1

    with patch("worker.alerts.send_alert_notifications", side_effect=fake_notify):
        alert, is_new = _run_coro(
            raise_alert(
                session,
                gh_id,
                "HEAT_STRESS",
                "critical",
                dedupe_key,
                zone_id=zone_id,
                now=t0 + timedelta(minutes=20),
            )
        )
        assert is_new is False
        assert alert.state == "acknowledged"
        assert len(notify_calls) == 0


def test_alert_resolve_and_reopen() -> None:
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    dedupe_key = f"SOIL_DRY:{zone_id}"

    existing_alert = Alert(
        id=uuid.uuid4(),
        greenhouse_id=gh_id,
        zone_id=zone_id,
        alert_type="SOIL_DRY",
        severity="warning",
        dedupe_key=dedupe_key,
        state="notified",
        created_at=datetime.now(UTC),
    )

    def _check_open(stmt):
        return _FakeResult(existing_alert if existing_alert.state != "resolved" else None)

    session = FakeAsyncSession(
        execute_fn=_check_open,
        get_fn=_make_get_gh(gh_id),
    )

    notify_calls = []

    async def fake_notify(*args, **kwargs):
        notify_calls.append((args, kwargs))
        return 1

    with patch("worker.alerts.send_alert_notifications", side_effect=fake_notify):
        now = datetime.now(UTC)
        res = _run_coro(resolve_alert(session, dedupe_key, now=now))
        assert res is not None
        assert res.state == "resolved"
        assert res.resolved_at == now
        assert len(notify_calls) == 1

        # Lần sau resolve tiếp khi đã resolved -> trả None
        res2 = _run_coro(resolve_alert(session, dedupe_key, now=now))
        assert res2 is None


def test_send_alert_notifications_emits_ws_event() -> None:
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    gh = Greenhouse(id=gh_id, farm_id=farm_id, name="Nhà kính Demo")
    zone = Zone(id=zone_id, greenhouse_id=gh_id, zone_index=2, name="Luống Dâu tây")

    alert = Alert(
        id=uuid.uuid4(),
        greenhouse_id=gh_id,
        zone_id=zone_id,
        alert_type="DISEASE_RISK",
        severity="critical",
        state="raised",
        dedupe_key=f"DISEASE_RISK:{zone_id}",
        payload={"vpd": 0.14, "air_rh": 94.0, "fungal_minutes": 6.0},
        created_at=datetime(2026, 11, 20, 9, 0, 0, tzinfo=UTC),
    )

    def _get(model, pk):
        if model == Greenhouse and pk == gh_id:
            return gh
        if model == Zone and pk == zone_id:
            return zone
        return None

    session = FakeAsyncSession(get_fn=_get)
    ws_events: list[tuple[str, dict[str, Any]]] = []

    async def fake_pg_notify(_session, channel, payload):
        ws_events.append((channel, payload))

    with patch("worker.notify.pg_notify", side_effect=fake_pg_notify):
        sent = _run_coro(send_alert_notifications(session, alert))

    assert sent == 1
    assert len(ws_events) == 1
    channel, evt = ws_events[0]
    assert channel == "ws_events"
    assert evt["farm_id"] == str(farm_id)
    assert evt["type"] == "alert"
    data = evt["data"]
    assert data["url"] == f"/zones/{zone_id}"
    assert "Nguy cơ nấm bệnh" in data["title"]
    assert "Nhà kính Demo - Luống Dâu tây" in data["body"]
    assert "escalated_at" not in data

    # Khi không tìm thấy Greenhouse -> trả 0 và không gửi sự kiện
    missing_session = FakeAsyncSession(get_fn=lambda _m, _pk: None)
    assert _run_coro(send_alert_notifications(missing_session, alert)) == 0


def test_alerts_api_endpoints() -> None:
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    user = User(id=uuid.uuid4(), farm_id=farm_id, email="u@greenhub.vn", role="owner")

    test_alert = Alert(
        id=uuid.uuid4(),
        greenhouse_id=gh_id,
        alert_type="SOIL_DRY",
        severity="warning",
        state="raised",
        dedupe_key="SOIL_DRY:1",
        created_at=datetime.now(UTC),
    )

    session = FakeAsyncSession(
        execute_fn=lambda stmt: _FakeResult([test_alert] if "SELECT" in str(stmt) else None),
        get_fn=lambda m, pk: None,
    )

    # 1. list_alerts
    alerts = _run_coro(list_alerts(user=user, session=session, state="open", limit=50))
    assert len(alerts) == 1

    # 2. acknowledge_alert
    session._execute_fn = lambda stmt: _FakeResult(test_alert)
    ws_ack_events: list[dict[str, Any]] = []

    async def fake_ack_notify(_session, _channel, payload):
        ws_ack_events.append(payload)

    with patch("api.routers.alerts.pg_notify", side_effect=fake_ack_notify):
        acked = _run_coro(acknowledge_alert(alert_id=test_alert.id, user=user, session=session))
    assert acked.state == "acknowledged"
    assert acked.acked_by == user.id
    assert len(ws_ack_events) == 1
    assert "escalated_at" not in ws_ack_events[0]["data"]

    # 3. acknowledge alert đã resolved -> 409
    resolved_alert = Alert(
        id=uuid.uuid4(),
        greenhouse_id=gh_id,
        alert_type="YIELD_FORECAST_LOW",
        severity="info",
        state="resolved",
        dedupe_key="YIELD_FORECAST_LOW:1",
        payload={"value": 1.35, "score": 0.45},
        created_at=datetime.now(UTC),
    )
    session._execute_fn = lambda stmt: _FakeResult(resolved_alert)
    with pytest.raises(HTTPException) as exc:
        _run_coro(acknowledge_alert(alert_id=resolved_alert.id, user=user, session=session))
    assert exc.value.status_code == 409

    # 3b. Kiểm tra tiêu đề & nội dung thông điệp YIELD_FORECAST_LOW (info)
    title = get_alert_title(resolved_alert.alert_type)
    body = format_alert_body(resolved_alert)
    assert "năng suất" in title.lower()
    assert "45%" in body or "năng suất" in body.lower()
