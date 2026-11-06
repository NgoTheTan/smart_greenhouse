"""Router điều khiển & chế độ Auto/Manual: /api/greenhouses/{id}/commands|modes (spec 6.5, 9)."""

import copy
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from api.deps import CurrentOperator, CurrentViewer, DbSession
from api.routers.greenhouses import get_owned_greenhouse
from core.config import get_settings
from core.models import Command, Gateway
from core.pubsub import CHANNEL_WORKER, pg_notify
from core.schemas import ActuatorModeUpdateRequest, CommandCreateRequest, CommandResponse
from worker.shadow import ensure_device_state

router = APIRouter(prefix="/greenhouses", tags=["commands"])


@router.post(
    "/{gh_id}/commands",
    response_model=CommandResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_command(
    gh_id: uuid.UUID,
    body: CommandCreateRequest,
    user: CurrentOperator,
    session: DbSession,
) -> Command:
    await get_owned_greenhouse(session, gh_id, user.farm_id)
    gw = (
        await session.execute(select(Gateway).where(Gateway.greenhouse_id == gh_id))
    ).scalar_one_or_none()
    if gw is None or not gw.online:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="gateway_offline",
        )

    now = datetime.now(UTC)
    s = get_settings()
    cmd = Command(
        id=uuid.uuid4(),
        greenhouse_id=gh_id,
        actuator=body.actuator,
        action=body.action,
        duration_s=body.duration_s,
        source="manual",
        requested_by=user.id,
        reason=body.reason,
        status="pending",
        created_at=now,
        expires_at=now + timedelta(seconds=s.command_expire_s),
    )
    session.add(cmd)
    await session.flush()

    await pg_notify(
        session,
        CHANNEL_WORKER,
        {"type": "command_created", "cmd_id": str(cmd.id), "greenhouse_id": str(gh_id)},
    )
    await session.commit()
    await session.refresh(cmd)
    return cmd


@router.get("/{gh_id}/commands", response_model=list[CommandResponse])
async def list_commands(
    gh_id: uuid.UUID,
    user: CurrentViewer,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[Command]:
    await get_owned_greenhouse(session, gh_id, user.farm_id)
    rows = (
        await session.execute(
            select(Command)
            .where(Command.greenhouse_id == gh_id)
            .order_by(Command.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


@router.put("/{gh_id}/modes", response_model=dict)
async def update_actuator_mode(
    gh_id: uuid.UUID,
    body: ActuatorModeUpdateRequest,
    user: CurrentOperator,
    session: DbSession,
) -> dict:
    await get_owned_greenhouse(session, gh_id, user.farm_id)
    state = await ensure_device_state(session, gh_id)
    desired = copy.deepcopy(state.desired or {})
    modes = desired.setdefault("modes", {})
    modes[body.actuator] = {
        "mode": body.mode,
        "until": body.until.isoformat() if body.until else None,
    }
    state.desired = desired
    state.updated_at = datetime.now(UTC)
    await session.commit()
    return {"greenhouse_id": str(gh_id), "modes": modes}
