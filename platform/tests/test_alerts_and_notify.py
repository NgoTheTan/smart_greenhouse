"""Unit tests cho Alert Service, Notification Service và REST Routers (spec 6.6, 6.7, 9)."""

import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pywebpush import WebPushException

from api.routers.alerts import acknowledge_alert, list_alerts
from api.routers.push import get_notification_preferences, subscribe_push
from core.models import Alert, Greenhouse, PushSubscription, User
from core.schemas import PushSubscribeRequest, PushSubscriptionKeys
from worker.alerts import escalate_alerts, raise_alert, resolve_alert
from worker.notify import format_alert_body, get_alert_title, send_webpush_to_subscription


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


def test_alert_escalation_after_timeout() -> None:
    gh_id = uuid.uuid4()
    now = datetime(2026, 11, 8, 11, 0, 0, tzinfo=UTC)

    crit_alert = Alert(
        id=uuid.uuid4(),
        greenhouse_id=gh_id,
        alert_type="HEAT_STRESS",
        severity="critical",
        dedupe_key="HEAT_STRESS:z1",
        state="notified",
        created_at=now - timedelta(minutes=10),
        escalated_at=None,
    )

    session = FakeAsyncSession(
        execute_fn=lambda stmt: _FakeResult([crit_alert]),
        get_fn=_make_get_gh(gh_id),
    )

    notify_calls = []

    async def fake_notify(*args, **kwargs):
        notify_calls.append((args, kwargs))
        return 1

    with patch("worker.alerts.send_alert_notifications", side_effect=fake_notify):
        escalated = _run_coro(escalate_alerts(session, now=now))
        assert len(escalated) == 1
        assert crit_alert.escalated_at == now
        assert len(notify_calls) == 1
        assert notify_calls[0][1].get("is_escalation") is True


def test_dead_webpush_subscription_cleanup() -> None:
    sub = PushSubscription(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        endpoint="https://push.example.com/dead_token",
        p256dh="key",
        auth="auth",
    )

    executed_stmts = []

    session = FakeAsyncSession(
        execute_fn=lambda stmt: executed_stmts.append(str(stmt)),
    )

    class _FakeResp:
        status_code = 410

    async def fake_to_thread(*args, **kwargs):
        raise WebPushException("Subscription expired", response=_FakeResp())

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        success = _run_coro(
            send_webpush_to_subscription(
                session=session,
                sub=sub,
                payload_dict={"title": "Test"},
                private_key="priv_key",
                subject="mailto:test@greenhub.vn",
                now=datetime.now(UTC),
            )
        )
        assert success is False
        assert len(executed_stmts) == 1
        assert "DELETE FROM push_subscriptions" in executed_stmts[0]


def test_alerts_and_push_api_endpoints() -> None:
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    user = User(id=uuid.uuid4(), farm_id=farm_id, email="u@greenhub.vn", role="operator")

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
    acked = _run_coro(acknowledge_alert(alert_id=test_alert.id, user=user, session=session))
    assert acked.state == "acknowledged"
    assert acked.acked_by == user.id

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

    # 4. push subscribe
    class _FakeReq:
        headers = {"user-agent": "Mozilla/5.0"}

    session._execute_fn = lambda stmt: _FakeResult(None)
    sub_res = _run_coro(
        subscribe_push(
            request=_FakeReq(),
            body=PushSubscribeRequest(
                endpoint="https://push.example.com/test",
                keys=PushSubscriptionKeys(p256dh="p256", auth="auth_secret"),
            ),
            user=user,
            session=session,
        )
    )
    assert sub_res == {"status": "ok"}

    # 5. notification prefs
    pref = _run_coro(get_notification_preferences(user=user, session=session))
    assert pref.user_id == user.id
    assert pref.push_enabled is True
