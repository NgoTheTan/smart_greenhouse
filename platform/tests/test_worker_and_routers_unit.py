"""Unit tests cho RBAC, 409 gateway_offline, ghép MAC thủ công, ACK side_effects & manual expiry."""

import json
import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.deps import get_current_user, require_min_role
from api.routers.commands import create_command
from api.routers.devices import pair_node
from core.models import (
    ActuatorLog,
    Command,
    DeviceNode,
    DeviceState,
    Gateway,
    Greenhouse,
    User,
    Zone,
)
from core.schemas import CommandCreateRequest, NodePairRequest
from core.security import create_access_token
from worker.commands import expire_manual_modes, handle_ack


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
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        if self._value is None:
            return []
        return self._value if isinstance(self._value, list) else [self._value]


def test_rbac_and_gateway_offline_409() -> None:
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    viewer = User(
        id=uuid.uuid4(),
        farm_id=farm_id,
        email="v@greenhub.vn",
        password_hash="x",
        role="viewer",
    )
    operator = User(
        id=uuid.uuid4(),
        farm_id=farm_id,
        email="op@greenhub.vn",
        password_hash="x",
        role="operator",
    )
    gh = Greenhouse(id=gh_id, farm_id=farm_id, name="GH 1", created_at=datetime.now(UTC))
    offline_gw = Gateway(
        id=uuid.uuid4(),
        greenhouse_id=gh_id,
        mqtt_username="gw_1",
        is_simulated=True,
        online=False,
    )

    session = AsyncMock()
    session.get.side_effect = lambda _m, pk: {viewer.id: viewer, operator.id: operator}.get(pk)

    # 1. Thiếu token -> 401
    with pytest.raises(HTTPException) as exc_unauth:
        _run_coro(get_current_user(None, session))
    assert exc_unauth.value.status_code == 401

    # 2. Viewer truy cập quyền operator -> 403
    v_tok = create_access_token(viewer.id, farm_id, "viewer")
    v_user = _run_coro(
        get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=v_tok), session)
    )
    checker = require_min_role("operator")
    with pytest.raises(HTTPException) as exc_forbid:
        _run_coro(checker(v_user))
    assert exc_forbid.value.status_code == 403

    # 3. Operator gửi lệnh khi gateway offline -> 409 gateway_offline (spec 6.5 & 9)
    session.execute.side_effect = [_FakeResult(gh), _FakeResult(offline_gw)]
    req = CommandCreateRequest(actuator="fan", action="on", duration_s=30)
    with pytest.raises(HTTPException) as exc_offline:
        _run_coro(create_command(gh_id, req, operator, session))
    assert exc_offline.value.status_code == 409
    assert exc_offline.value.detail == "gateway_offline"


def test_manual_mac_pairing_and_cfg_version_bump() -> None:
    farm_id = uuid.uuid4()
    gh = Greenhouse(id=uuid.uuid4(), farm_id=farm_id, name="GH", created_at=datetime.now(UTC))
    zone = Zone(id=uuid.uuid4(), greenhouse_id=gh.id, zone_index=1, name="Z1")
    owner = User(
        id=uuid.uuid4(), farm_id=farm_id, email="o@greenhub.vn", password_hash="x", role="owner"
    )
    state = DeviceState(
        greenhouse_id=gh.id, reported={}, desired={}, cfg_version_desired=1, cfg_version_reported=1
    )

    added: list[Any] = []
    session = AsyncMock()
    session.add = added.append
    session.get.return_value = state
    session.execute.side_effect = [
        _FakeResult((zone, gh)),  # tìm zone thuộc farm
        _FakeResult(None),  # MAC chưa từng gửi discovery (nhập tay)
        _FakeResult([]),  # không có node cũ gắn vào zone này
        _FakeResult(None),  # pg_notify
    ]

    paired = _run_coro(
        pair_node("aa-bb-cc-dd-ee-99", NodePairRequest(zone_id=zone.id), owner, session)
    )
    assert isinstance(paired, DeviceNode)
    assert paired.mac_address == "AA:BB:CC:DD:EE:99"
    assert paired.status == "paired"
    assert state.cfg_version_desired == 2


def test_handle_ack_records_side_effects_and_updates_shadow() -> None:
    farm_id = uuid.uuid4()
    gh = Greenhouse(id=uuid.uuid4(), farm_id=farm_id, name="GH", created_at=datetime.now(UTC))
    cmd = Command(
        id=uuid.uuid4(),
        greenhouse_id=gh.id,
        actuator="fan",
        action="on",
        duration_s=60,
        source="manual",
        status="sent",
        expires_at=datetime.now(UTC) + timedelta(seconds=20),
    )
    state = DeviceState(
        greenhouse_id=gh.id, reported={}, desired={}, cfg_version_desired=1, cfg_version_reported=1
    )

    added_logs: list[Any] = []
    session = AsyncMock()
    session.add = added_logs.append
    session.get.return_value = state
    session.execute.side_effect = [_FakeResult((cmd, gh)), _FakeResult(None)]

    ack_raw = json.dumps(
        {
            "cmd_id": str(cmd.id),
            "status": "applied",
            "reason": None,
            "applied_at": datetime.now(UTC).isoformat(),
            "side_effects": ["mist_off"],
            "state": {"pump_1": "off", "pump_2": "off", "fan": "on", "mist": "off"},
        }
    ).encode()

    ok = _run_coro(handle_ack(session, farm_id, gh.id, cmd.id, ack_raw))
    assert ok is True
    assert cmd.status == "applied"
    assert state.reported["actuators"]["fan"] == "on"
    assert state.reported["actuators"]["mist"] == "off"
    actuator_logs = [x for x in added_logs if isinstance(x, ActuatorLog)]
    assert {(lg.actuator, lg.action) for lg in actuator_logs} == {("fan", "on"), ("mist", "off")}


def test_expire_manual_modes_resets_past_until() -> None:
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    future = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
    st = DeviceState(
        greenhouse_id=uuid.uuid4(),
        reported={},
        desired={
            "modes": {
                "fan": {"mode": "manual", "until": past},
                "mist": {"mode": "manual", "until": future},
            }
        },
        cfg_version_desired=1,
        cfg_version_reported=1,
    )
    fake_session = AsyncMock()
    fake_session.execute.return_value = _FakeResult([st])

    changed = _run_coro(expire_manual_modes(fake_session))
    assert changed == 1
    assert st.desired["modes"]["fan"] == {"mode": "auto", "until": None}
    assert st.desired["modes"]["mist"]["mode"] == "manual"
