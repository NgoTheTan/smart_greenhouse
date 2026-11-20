"""Router xác thực: POST /api/auth/login và GET /api/me (spec 9)."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from api.deps import CurrentUser, DbSession
from core.models import Farm, User
from core.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from core.security import create_access_token, hash_password, verify_password

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=TokenResponse)
async def register(body: RegisterRequest, session: DbSession) -> TokenResponse:
    existing = (
        await session.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email này đã được sử dụng. Vui lòng đăng nhập hoặc dùng email khác.",
        )

    farm_name = body.farm_name.strip()
    if not farm_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tên trang trại là bắt buộc.",
        )
    farm = Farm(name=farm_name)
    session.add(farm)
    await session.flush()

    user = User(
        farm_id=farm.id,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        role="owner",
    )
    session.add(user)
    await session.flush()

    await session.commit()
    await session.refresh(user)

    token = create_access_token(user.id, user.farm_id, user.role)
    return TokenResponse(access_token=token)


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
async def get_me(user: CurrentUser, session: DbSession) -> UserResponse:
    farm = (
        await session.execute(select(Farm).where(Farm.id == user.farm_id))
    ).scalar_one_or_none()
    farm_name = farm.name if farm else None
    return UserResponse(
        id=user.id,
        farm_id=user.farm_id,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
        farm_name=farm_name,
    )

