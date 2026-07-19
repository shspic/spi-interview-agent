from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    normalize_username,
    validate_password,
    validate_username,
    verify_password,
)
from app.db.database import get_db
from app.db.models import User
from app.services.registration_setting_service import (
    RegistrationSettingError,
    verify_registration_invite,
)
from app.services.rate_limit_service import (
    enforce_ip_rate_limit,
    enforce_user_rate_limit,
)

router = APIRouter()
DUMMY_PASSWORD_HASH = "$2b$12$4FmMnne2zvpIMYOumkZHpOHSi70GDSu5WdT4sqLiUqwI408BO4YNq"


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(max_length=64)
    password: str = Field(max_length=72)
    invite_code: str = Field(max_length=64)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(max_length=64)
    password: str = Field(max_length=72)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(max_length=72)
    new_password: str = Field(max_length=72)
    confirm_password: str = Field(max_length=72)


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_active": bool(user.is_active),
        "is_admin": bool(user.is_admin),
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register_user(
    http_request: Request,
    request: RegisterRequest,
    db: Session = Depends(get_db),
):
    enforce_ip_rate_limit(db, http_request, "register")
    try:
        invite_is_valid = verify_registration_invite(db, request.invite_code)
    except RegistrationSettingError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc

    if not invite_is_valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="邀请码无效",
        )

    username = validate_username(request.username)
    validate_password(request.password)

    if db.query(User).filter(User.username == username).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )

    user = User(
        username=username,
        password_hash=hash_password(request.password),
        is_active=True,
        is_admin=False,
        created_at=datetime.now().isoformat(timespec="seconds"),
        last_login_at=None,
    )

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        ) from exc

    return {"user": user_to_dict(user)}


@router.post("/auth/login")
def login_user(
    http_request: Request,
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    enforce_ip_rate_limit(db, http_request, "login")
    username = normalize_username(request.username)
    user = db.query(User).filter(User.username == username).first()
    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_is_valid = verify_password(request.password, password_hash)

    if user is None or not password_is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已停用",
        )

    access_token = create_access_token(user.id)
    user.last_login_at = datetime.now().isoformat(timespec="seconds")
    db.commit()
    db.refresh(user)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_minutes * 60,
        "user": user_to_dict(user),
    }


@router.get("/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {"user": user_to_dict(current_user)}


@router.post("/auth/change-password")
def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_user_rate_limit(db, current_user.id, "password_change")
    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")
    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码错误")
    if verify_password(request.new_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")

    validate_password(request.new_password)
    current_user.password_hash = hash_password(request.new_password)
    db.commit()
    return {"success": True, "message": "密码修改成功，请重新登录"}
