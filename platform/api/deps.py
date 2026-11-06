"""Dependencies xác thực JWT, kiểm tra vai trò và cô lập dữ liệu theo `farm_id` (spec 9, 12)."""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.models import User
from core.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)

ROLE_RANK = {"viewer": 1, "operator": 2, "owner": 3}


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu token xác thực Bearer",
        )
    try:
        claims = decode_access_token(creds.credentials)
        user_id = uuid.UUID(str(claims["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc đã hết hạn",
        ) from exc

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Người dùng không tồn tại",
        )
    return user


def require_min_role(
    min_role: str,
) -> Callable[..., Coroutine[Any, Any, User]]:
    min_rank = ROLE_RANK[min_role]

    async def _checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if ROLE_RANK.get(user.role, 0) < min_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Yêu cầu quyền tối thiểu '{min_role}'",
            )
        return user

    return _checker


CurrentViewer = Annotated[User, Depends(require_min_role("viewer"))]
CurrentOperator = Annotated[User, Depends(require_min_role("operator"))]
CurrentOwner = Annotated[User, Depends(require_min_role("owner"))]
DbSession = Annotated[AsyncSession, Depends(get_session)]
