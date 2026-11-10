"""Unit tests cho WebSocket /ws và ConnectionManager (spec 3.2, 9)."""

import uuid
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock

from starlette import status
from starlette.websockets import WebSocketDisconnect

from api.ws import ConnectionManager, _authenticate_ws, websocket_endpoint
from core.security import create_access_token


def _run_coro(coro: Coroutine[Any, Any, Any]) -> Any:
    """Chạy coroutine thuần bộ nhớ không cần khởi tạo socket loopback của ProactorEventLoop."""
    try:
        while True:
            coro.send(None)
    except StopIteration as stop:
        return stop.value
    finally:
        coro.close()


def test_ws_authenticate_missing_or_invalid_token() -> None:
    ws_mock = AsyncMock()
    ws_mock.headers = {}

    # Không có token
    assert _run_coro(_authenticate_ws(ws_mock, None)) is None

    # Token sai định dạng
    assert _run_coro(_authenticate_ws(ws_mock, "invalid-token-string")) is None


def test_ws_authenticate_valid_token() -> None:
    user_id = uuid.uuid4()
    farm_id = uuid.uuid4()
    token = create_access_token(user_id, farm_id, role="viewer")

    ws_mock = AsyncMock()
    ws_mock.headers = {}

    res = _run_coro(_authenticate_ws(ws_mock, token))
    assert res is not None
    res_uid, res_fid = res
    assert res_uid == user_id
    assert res_fid == farm_id


def test_ws_endpoint_rejects_unauthorized() -> None:
    ws_mock = AsyncMock()
    ws_mock.headers = {}

    _run_coro(websocket_endpoint(ws_mock, token=None))
    ws_mock.close.assert_awaited_once_with(
        code=status.WS_1008_POLICY_VIOLATION,
        reason="Unauthorized",
    )


def test_ws_endpoint_accepts_and_handles_ping() -> None:
    user_id = uuid.uuid4()
    farm_id = uuid.uuid4()
    token = create_access_token(user_id, farm_id, role="operator")

    ws_mock = AsyncMock()
    ws_mock.headers = {}
    ws_mock.receive_text.side_effect = ["ping", WebSocketDisconnect()]

    _run_coro(websocket_endpoint(ws_mock, token=token))

    ws_mock.accept.assert_awaited_once()
    ws_mock.send_text.assert_awaited_once_with("pong")


def test_ws_connection_manager_fanout_and_isolation() -> None:
    """Kiểm tra ConnectionManager chỉ gửi sự kiện tới đúng farm_id (không rò rỉ tenant)."""
    manager = ConnectionManager()

    farm_a = str(uuid.uuid4())
    farm_b = str(uuid.uuid4())

    ws_a1 = AsyncMock()
    ws_a2 = AsyncMock()
    ws_b = AsyncMock()

    _run_coro(manager.connect(farm_a, ws_a1))
    _run_coro(manager.connect(farm_a, ws_a2))
    _run_coro(manager.connect(farm_b, ws_b))

    # Phát sự kiện cho farm A
    event_a = {
        "farm_id": farm_a,
        "type": "telemetry",
        "data": {"air_temp": 24.5, "air_rh": 85.0},
    }
    _run_coro(manager.on_ws_event(event_a))

    ws_a1.send_json.assert_awaited_once_with({
        "type": "telemetry",
        "data": {"air_temp": 24.5, "air_rh": 85.0},
    })
    ws_a2.send_json.assert_awaited_once_with({
        "type": "telemetry",
        "data": {"air_temp": 24.5, "air_rh": 85.0},
    })
    # ws_b thuộc farm B tuyệt đối không nhận được
    ws_b.send_json.assert_not_awaited()

    # Ngắt kết nối một client
    _run_coro(manager.disconnect(farm_a, ws_a1))
    ws_a1.reset_mock()
    ws_a2.reset_mock()

    # Phát tiếp sự kiện cảnh báo
    event_alert = {
        "farm_id": farm_a,
        "type": "alert",
        "data": {"alert_type": "DISEASE_RISK"},
    }
    _run_coro(manager.on_ws_event(event_alert))

    ws_a1.send_json.assert_not_awaited()
    ws_a2.send_json.assert_awaited_once_with({
        "type": "alert",
        "data": {"alert_type": "DISEASE_RISK"},
    })


def test_ws_connection_manager_prunes_dead_sockets() -> None:
    """Kiểm tra tự động dọn dẹp socket bị lỗi/gãy khi gửi tin."""
    manager = ConnectionManager()
    farm_id = str(uuid.uuid4())

    ws_healthy = AsyncMock()
    ws_dead = AsyncMock()
    ws_dead.send_json.side_effect = RuntimeError("Socket broken")

    _run_coro(manager.connect(farm_id, ws_healthy))
    _run_coro(manager.connect(farm_id, ws_dead))

    event = {
        "farm_id": farm_id,
        "type": "command_status",
        "data": {"status": "applied"},
    }
    _run_coro(manager.on_ws_event(event))

    assert ws_dead not in manager._connections.get(farm_id, set())
    assert ws_healthy in manager._connections.get(farm_id, set())
