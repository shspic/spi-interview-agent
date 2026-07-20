import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.readiness import auth_unavailable_message
from app.db.models import AuthSecurityEvent, AuthSession, User

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PREAUTH_BINDING = "preauth"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def short_session_ref(session_id: str | None) -> str | None:
    if not session_id:
        return None
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]


def record_auth_event(
    db: Session,
    event_type: str,
    *,
    user_id: int | None = None,
    session_id: str | None = None,
    event_status: str = "success",
) -> None:
    db.add(
        AuthSecurityEvent(
            user_id=user_id,
            event_type=event_type,
            status=event_status,
            session_ref=short_session_ref(session_id),
            created_at=utc_text(),
        )
    )


def get_csrf_secret() -> bytes:
    secret = settings.auth_csrf_secret.strip()
    if not secret or secret == "change-me":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "auth_unavailable",
                "message": auth_unavailable_message(settings),
            },
        )
    return secret.encode("utf-8")


def _encode_signature(value: str) -> str:
    signature = hmac.new(get_csrf_secret(), value.encode("utf-8"), hashlib.sha256)
    return base64.urlsafe_b64encode(signature.digest()).rstrip(b"=").decode("ascii")


def csrf_session_binding(session_id: str) -> str:
    return _encode_signature(f"session:{session_id}")


def create_csrf_token(binding: str, *, lifetime_minutes: int = 30) -> str:
    expires_at = int((utc_now() + timedelta(minutes=lifetime_minutes)).timestamp())
    unsigned = f"{binding}.{expires_at}.{secrets.token_urlsafe(32)}"
    return f"{unsigned}.{_encode_signature(unsigned)}"


def parse_csrf_token(token: str) -> tuple[str, int]:
    try:
        binding, expires_raw, nonce, signature = token.split(".", 3)
        expires_at = int(expires_raw)
    except (AttributeError, TypeError, ValueError) as exc:
        raise_csrf("csrf_invalid", "CSRF 校验失败", exc)
    unsigned = f"{binding}.{expires_at}.{nonce}"
    if not secrets.compare_digest(signature, _encode_signature(unsigned)):
        raise_csrf("csrf_invalid", "CSRF 校验失败")
    if expires_at < int(utc_now().timestamp()):
        raise_csrf("csrf_invalid", "CSRF 校验失败")
    return binding, expires_at


def raise_csrf(error_code: str, message: str, cause: Exception | None = None):
    error = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error_code": error_code, "message": message},
    )
    if cause is None:
        raise error
    raise error from cause


def _request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    referer = request.headers.get("referer")
    if not referer:
        return None
    parsed = urlsplit(referer)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "invalid"
    return f"{parsed.scheme}://{parsed.netloc}"


def verify_request_origin(request: Request) -> None:
    if not settings.auth_require_origin_check:
        return
    supplied_origin = _request_origin(request)
    if supplied_origin is None:
        if settings.app_environment == "test":
            return
        raise_csrf("csrf_invalid", "请求来源校验失败")
    same_origin = f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
    allowed = {origin.rstrip("/") for origin in settings.cors_allowed_origins}
    allowed.add(same_origin)
    if supplied_origin not in allowed:
        raise_csrf("csrf_invalid", "请求来源校验失败")


def verify_csrf(
    request: Request,
    *,
    expected_binding: str,
    stored_hash: str | None = None,
) -> None:
    if request.method.upper() not in UNSAFE_METHODS:
        return
    verify_request_origin(request)
    cookie_token = request.cookies.get(settings.auth_csrf_cookie_name)
    header_token = request.headers.get("X-CSRF-Token")
    if not cookie_token or not header_token:
        raise_csrf("csrf_required", "缺少 CSRF 凭证")
    if not secrets.compare_digest(cookie_token, header_token):
        raise_csrf("csrf_invalid", "CSRF 校验失败")
    binding, _ = parse_csrf_token(cookie_token)
    if not secrets.compare_digest(binding, expected_binding):
        raise_csrf("csrf_invalid", "CSRF 校验失败")
    if stored_hash and not secrets.compare_digest(hash_secret(cookie_token), stored_hash):
        raise_csrf("csrf_invalid", "CSRF 校验失败")


def create_refresh_token(session_id: str) -> str:
    return f"{session_id}.{secrets.token_urlsafe(48)}"


def refresh_session_id(refresh_token: str | None) -> str | None:
    if not refresh_token:
        return None
    session_id, separator, secret = refresh_token.partition(".")
    if not separator or not session_id or not secret:
        return None
    return session_id


def create_session(db: Session, user: User) -> tuple[AuthSession, str, str]:
    now = utc_now()
    active_sessions = (
        db.query(AuthSession)
        .filter(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utc_text(now),
        )
        .order_by(AuthSession.created_at.asc(), AuthSession.id.asc())
        .all()
    )
    excess = len(active_sessions) - settings.auth_max_active_sessions + 1
    for old_session in active_sessions[: max(0, excess)]:
        old_session.revoked_at = utc_text(now)
        old_session.revoke_reason = "session_limit"
        record_auth_event(
            db,
            "session_revoked",
            user_id=user.id,
            session_id=old_session.id,
        )

    session_id = str(uuid4())
    refresh_token = create_refresh_token(session_id)
    csrf_token = create_csrf_token(
        csrf_session_binding(session_id),
        lifetime_minutes=settings.auth_refresh_token_days * 24 * 60,
    )
    session = AuthSession(
        id=session_id,
        user_id=user.id,
        refresh_token_hash=hash_secret(refresh_token),
        csrf_token_hash=hash_secret(csrf_token),
        created_at=utc_text(now),
        last_seen_at=utc_text(now),
        expires_at=utc_text(now + timedelta(days=settings.auth_refresh_token_days)),
        revoked_at=None,
        revoke_reason=None,
        token_version=1,
        user_agent_hash=None,
    )
    db.add(session)
    db.flush()
    return session, refresh_token, csrf_token


def rotate_refresh_token(
    db: Session,
    session: AuthSession,
    presented_token: str,
) -> tuple[str, str] | None:
    refresh_token = create_refresh_token(session.id)
    csrf_token = create_csrf_token(
        csrf_session_binding(session.id),
        lifetime_minutes=settings.auth_refresh_token_days * 24 * 60,
    )
    result = db.execute(
        update(AuthSession)
        .where(
            AuthSession.id == session.id,
            AuthSession.refresh_token_hash == hash_secret(presented_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utc_text(),
        )
        .values(
            refresh_token_hash=hash_secret(refresh_token),
            csrf_token_hash=hash_secret(csrf_token),
            last_seen_at=utc_text(),
        )
    )
    if result.rowcount != 1:
        db.rollback()
        return None
    db.flush()
    return refresh_token, csrf_token


def revoke_session(
    db: Session,
    session: AuthSession,
    reason: str,
    *,
    commit: bool = False,
) -> None:
    if session.revoked_at is None:
        session.revoked_at = utc_text()
        session.revoke_reason = reason
        record_auth_event(
            db,
            "session_revoked",
            user_id=session.user_id,
            session_id=session.id,
        )
    if commit:
        db.commit()


def revoke_all_sessions(
    db: Session,
    user_id: int,
    reason: str,
    *,
    commit: bool = False,
) -> int:
    sessions = (
        db.query(AuthSession)
        .filter(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .all()
    )
    for session in sessions:
        revoke_session(db, session, reason)
    if commit:
        db.commit()
    return len(sessions)


def set_csrf_cookie(response: Response, token: str, *, max_age: int | None = None) -> None:
    response.set_cookie(
        key=settings.auth_csrf_cookie_name,
        value=token,
        max_age=max_age or settings.auth_refresh_token_days * 24 * 60 * 60,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        domain=settings.auth_cookie_domain,
        path=settings.auth_csrf_cookie_path,
    )


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
) -> None:
    response.set_cookie(
        key=settings.auth_access_cookie_name,
        value=access_token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        domain=settings.auth_cookie_domain,
        path=settings.auth_access_cookie_path,
    )
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=refresh_token,
        max_age=settings.auth_refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        domain=settings.auth_cookie_domain,
        path=settings.auth_refresh_cookie_path,
    )
    set_csrf_cookie(response, csrf_token)


def clear_auth_cookies(response: Response) -> None:
    for name, path, httponly in (
        (settings.auth_access_cookie_name, settings.auth_access_cookie_path, True),
        (settings.auth_refresh_cookie_name, settings.auth_refresh_cookie_path, True),
        (settings.auth_csrf_cookie_name, settings.auth_csrf_cookie_path, False),
    ):
        response.delete_cookie(
            key=name,
            path=path,
            domain=settings.auth_cookie_domain,
            secure=settings.auth_cookie_secure,
            httponly=httponly,
            samesite=settings.auth_cookie_samesite,
        )
