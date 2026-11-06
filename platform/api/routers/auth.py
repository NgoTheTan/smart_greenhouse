"""Router xác thực: POST /api/auth/login và GET /api/me (spec 9)."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from api.deps import CurrentViewer, DbSession
from core.models import User
from core.schemas import LoginRequest, TokenResponse, UserResponse
from core.security import create_access_token, verify_password

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: DbSession) -> TokenResponse:
    user = (
        await session.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không đúng",
        )
    token = create_access_token(user.id, user.farm_id, user.role)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(user: CurrentViewer) -> User:
    return user

