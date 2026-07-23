import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import ExpiredSignatureError, InvalidTokenError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.readiness import auth_unavailable_message
from app.core.input_validation import validate_safe_text
from app.db.database import get_db
from app.db.models import AuthSession, User
from app.services.auth_session_service import (
    csrf_session_binding,
    record_auth_event,
    utc_text,
    verify_csrf,
)

USERNAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72
JWT_ALGORITHM = "HS256"


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    normalized_username = normalize_username(username)
    if len(normalized_username) < 3 or len(normalized_username) > 32:
        raise HTTPException(status_code=400, detail="用户名长度必须在 3 到 32 个字符之间")
    if not USERNAME_PATTERN.fullmatch(normalized_username):
        raise HTTPException(status_code=400, detail="用户名只能包含小写字母、数字和下划线")
    return normalized_username


def validate_password(password: str) -> None:
    try:
        validate_safe_text(password, field_name="密码", max_chars=MAX_PASSWORD_BYTES)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"密码长度不能少于 {MIN_PASSWORD_LENGTH} 个字符",
        )
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise HTTPException(status_code=400, detail="密码长度不能超过 72 个 UTF-8 字节")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (TypeError, ValueError):
        return False


def get_jwt_secret_key() -> str:
    secret_key = settings.jwt_secret_key.strip()
    if not secret_key or secret_key == "change-me":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "auth_unavailable",
                "message": auth_unavailable_message(settings),
            },
        )
    return secret_key


def create_access_token(user_id: int, session_id: str, token_version: int) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "session_id": session_id,
        "token_type": "access",
        "token_version": token_version,
        "iat": now,
        "exp": expires_at,
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, get_jwt_secret_key(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, get_jwt_secret_key(), algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub", ""))
        session_id = str(payload.get("session_id", ""))
        token_type = payload.get("token_type")
        token_version = int(payload.get("token_version", 0))
        jti = str(payload.get("jti", ""))
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "auth_expired", "message": "登录状态已过期"},
        ) from exc
    except (InvalidTokenError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "auth_required", "message": "请重新登录"},
        ) from exc
    if (
        user_id <= 0
        or not session_id
        or token_type != "access"
        or token_version <= 0
        or not jti
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "auth_required", "message": "请重新登录"},
        )
    return {
        "user_id": user_id,
        "session_id": session_id,
        "token_version": token_version,
        "jti": jti,
    }


def get_session_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(settings.auth_access_cookie_name)
    authorization = request.headers.get("authorization")
    if authorization:
        error_code = "auth_conflict" if token else "auth_required"
        message = "认证来源冲突" if token else "Bearer 认证已关闭"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": error_code, "message": message},
        )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "auth_required", "message": "请先登录"},
        )

    payload = decode_access_token(token)
    auth_session = db.get(AuthSession, payload["session_id"])
    if (
        auth_session is None
        or auth_session.user_id != payload["user_id"]
        or auth_session.token_version != payload["token_version"]
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= utc_text()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "session_revoked", "message": "登录会话已失效"},
        )
    user = db.get(User, payload["user_id"])
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "session_revoked", "message": "登录会话已失效"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "account_disabled", "message": "账号已停用"},
        )

    try:
        verify_csrf(
            request,
            expected_binding=csrf_session_binding(auth_session.id),
            stored_hash=auth_session.csrf_token_hash,
        )
    except HTTPException:
        record_auth_event(
            db,
            "csrf_rejected",
            user_id=user.id,
            session_id=auth_session.id,
            event_status="failed",
        )
        db.commit()
        raise
    request.state.auth_session = auth_session
    return user


def get_current_user(current_user: User = Depends(get_session_user)) -> User:
    if current_user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "password_change_required",
                "message": "请先修改临时密码",
            },
        )
    return current_user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="仅管理员可以访问该接口")
    return current_user
