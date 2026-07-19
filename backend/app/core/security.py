import re
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.input_validation import validate_safe_text
from app.db.database import get_db
from app.db.models import User

USERNAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72
JWT_ALGORITHM = "HS256"

bearer_scheme = HTTPBearer(auto_error=False)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    normalized_username = normalize_username(username)

    if len(normalized_username) < 3 or len(normalized_username) > 32:
        raise HTTPException(
            status_code=400,
            detail="用户名长度必须在 3 到 32 个字符之间",
        )

    if not USERNAME_PATTERN.fullmatch(normalized_username):
        raise HTTPException(
            status_code=400,
            detail="用户名只能包含小写字母、数字和下划线",
        )

    return normalized_username


def validate_password(password: str) -> None:
    try:
        validate_safe_text(
            password,
            field_name="密码",
            max_chars=MAX_PASSWORD_BYTES,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"密码长度不能少于 {MIN_PASSWORD_LENGTH} 个字符",
        )

    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=400,
            detail="密码长度不能超过 72 个 UTF-8 字节",
        )


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
            detail="认证服务尚未配置",
        )

    return secret_key


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, get_jwt_secret_key(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(
            token,
            get_jwt_secret_key(),
            algorithms=[JWT_ALGORITHM],
        )
        user_id = int(payload.get("sub", ""))
    except (InvalidTokenError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭证无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭证无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_id


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decode_access_token(credentials.credentials)
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭证无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已停用",
        )

    return user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可以访问该接口",
        )
    return current_user
