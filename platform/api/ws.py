"""WebSocket /ws: nhận sự kiện từ worker qua PostgreSQL ws_events (spec 3.2, 9)."""

import asyncio
import logging
import uuid
from typing import Any

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import User
from core.security import decode_access_token

log = logging.getLogger("api.ws")

router = APIRouter(tags=["realtime"])


class ConnectionManager:
    """Quản lý kết nối WebSocket theo tenant (farm_id)."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, farm_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(farm_id, set()).add(websocket)
        log.info(
            "WebSocket connected for farm %s (total: %d)",
            farm_id,
            len(self._connections[farm_id]),
        )

    async def disconnect(self, farm_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            if farm_id in self._connections:
                self._connections[farm_id].discard(websocket)
                if not self._connections[farm_id]:
                    del self._connections[farm_id]
        log.info("WebSocket disconnected for farm %s", farm_id)

    async def broadcast_to_farm(self, farm_id: str, message: dict[str, Any]) -> None:
        """Gửi khung JSON {type, data} tới các client WebSocket thuộc cùng farm_id."""
        async with self._lock:
            sockets = list(self._connections.get(farm_id, set()))
        if not sockets:
            return

        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    if farm_id in self._connections:
                        self._connections[farm_id].discard(ws)
                if farm_id in self._connections and not self._connections[farm_id]:
                    del self._connections[farm_id]

    async def on_ws_event(self, event: dict[str, Any]) -> None:
        """Xử lý thông điệp từ kênh PostgreSQL ws_events, fan-out đúng farm_id."""
        farm_id = str(event.get("farm_id") or "")
        if not farm_id:
            return

        msg_type = event.get("type")
        data = event.get("data")
        if msg_type is None or data is None:
            return

        payload = {"type": msg_type, "data": data}
        await self.broadcast_to_farm(farm_id, payload)


manager = ConnectionManager()


async def _authenticate_ws(
    websocket: WebSocket,
    token: str | None,
    session: AsyncSession | None = None,
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Xác thực token JWT qua query param, trả về (user_id, farm_id) hoặc None."""
    if not token:
        auth_hdr = websocket.headers.get("authorization")
        if auth_hdr and auth_hdr.lower().startswith("bearer "):
            token = auth_hdr[7:].strip()
        else:
            token = websocket.headers.get("sec-websocket-protocol")

    if not token:
        return None

    try:
        claims = decode_access_token(token)
        user_id = uuid.UUID(str(claims["sub"]))
        token_farm_id = uuid.UUID(str(claims["farm_id"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None

    if session is not None and hasattr(session, "execute"):
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            return None
        return user.id, user.farm_id

    return user_id, token_farm_id


@router.websocket("/ws")
@router.websocket("/api/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    auth_result = await _authenticate_ws(websocket, token)
    if auth_result is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    _user_id, farm_id = auth_result
    farm_id_str = str(farm_id)
    await manager.connect(farm_id_str, websocket)

    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Lỗi trong kết nối WebSocket farm %s", farm_id_str)
    finally:
        await manager.disconnect(farm_id_str, websocket)
