from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_current_user,
    get_session_user,
    hash_password,
    normalize_username,
    validate_password,
    validate_username,
    verify_password,
)
from app.db.database import get_db
from app.db.models import AuthSession, User
from app.services.auth_session_service import (
    PREAUTH_BINDING,
    clear_auth_cookies,
    csrf_session_binding,
    create_csrf_token,
    create_session,
    hash_secret,
    record_auth_event,
    refresh_session_id,
    revoke_all_sessions,
    revoke_session,
    rotate_refresh_token,
    set_auth_cookies,
    set_csrf_cookie,
    utc_text,
    verify_csrf,
)
from app.services.registration_setting_service import (
    RegistrationSettingError,
    verify_registration_invite,
)
from app.services.rate_limit_service import enforce_ip_rate_limit, enforce_user_rate_limit
from app.services.password_reset_service import (
    ANONYMOUS_RESPONSE,
    create_password_reset_request,
    normalize_request_note,
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


class PasswordResetRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=64)
    request_note: str = Field(default="", max_length=2_000)


class TemporaryPasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str = Field(max_length=72)
    confirm_password: str = Field(max_length=72)


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_active": bool(user.is_active),
        "is_admin": bool(user.is_admin),
        "is_quota_exempt": bool(user.is_quota_exempt),
        "must_change_password": bool(user.must_change_password),
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


def refresh_failed(request: Request) -> JSONResponse:
    response = JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "error_code": "refresh_failed",
            "message": "无法刷新登录状态",
            "request_id": getattr(request.state, "request_id", ""),
            "details": None,
            "detail": {"error_code": "refresh_failed", "message": "无法刷新登录状态"},
        },
    )
    clear_auth_cookies(response)
    return response


def get_refresh_session(request: Request, db: Session) -> tuple[AuthSession | None, str | None]:
    refresh_token = request.cookies.get(settings.auth_refresh_cookie_name)
    session_id = refresh_session_id(refresh_token)
    return (db.get(AuthSession, session_id) if session_id else None, refresh_token)


@router.get("/auth/csrf")
def get_csrf(request: Request, response: Response, db: Session = Depends(get_db)):
    binding = PREAUTH_BINDING
    auth_session = None
    access_token = request.cookies.get(settings.auth_access_cookie_name)
    if access_token:
        try:
            payload = decode_access_token(access_token)
            auth_session = db.get(AuthSession, payload["session_id"])
        except HTTPException:
            auth_session = None
    if auth_session is None:
        candidate, refresh_token = get_refresh_session(request, db)
        if candidate is not None and refresh_token and candidate.refresh_token_hash == hash_secret(refresh_token):
            auth_session = candidate
    if (
        auth_session is not None
        and auth_session.revoked_at is None
        and auth_session.expires_at > utc_text()
    ):
        binding = csrf_session_binding(auth_session.id)
    token = create_csrf_token(
        binding,
        lifetime_minutes=(
            settings.auth_refresh_token_days * 24 * 60
            if auth_session is not None
            else 30
        ),
    )
    if auth_session is not None:
        auth_session.csrf_token_hash = hash_secret(token)
        db.commit()
    set_csrf_cookie(
        response,
        token,
        max_age=(
            settings.auth_refresh_token_days * 24 * 60 * 60
            if auth_session is not None
            else 30 * 60
        ),
    )
    return {"success": True}


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register_user(
    http_request: Request,
    request: RegisterRequest,
    db: Session = Depends(get_db),
):
    verify_csrf(http_request, expected_binding=PREAUTH_BINDING)
    enforce_ip_rate_limit(db, http_request, "register")
    try:
        invite_is_valid = verify_registration_invite(db, request.invite_code)
    except RegistrationSettingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if not invite_is_valid:
        raise HTTPException(status_code=403, detail="邀请码无效")
    username = validate_username(request.username)
    validate_password(request.password)
    if db.query(User).filter(User.username == username).first() is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=username,
        password_hash=hash_password(request.password),
        is_active=True,
        is_admin=False,
        is_quota_exempt=False,
        created_at=datetime.now().isoformat(timespec="seconds"),
        last_login_at=None,
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在") from exc
    return {"user": user_to_dict(user)}


@router.post("/auth/login")
def login_user(
    http_request: Request,
    response: Response,
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    verify_csrf(http_request, expected_binding=PREAUTH_BINDING)
    enforce_ip_rate_limit(db, http_request, "login")
    username = normalize_username(request.username)
    user = db.query(User).filter(User.username == username).first()
    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    if user is None or not verify_password(request.password, password_hash):
        record_auth_event(db, "login_failed", event_status="failed")
        db.commit()
        raise HTTPException(
            status_code=401,
            detail={"error_code": "invalid_credentials", "message": "用户名或密码错误"},
        )
    if not user.is_active:
        record_auth_event(db, "login_failed", user_id=user.id, event_status="failed")
        db.commit()
        raise HTTPException(
            status_code=401,
            detail={"error_code": "account_disabled", "message": "账号已停用"},
        )
    if user.must_change_password:
        try:
            expires_at = datetime.fromisoformat(
                user.temporary_password_expires_at or ""
            )
        except ValueError:
            expires_at = None
        if expires_at is None or expires_at <= datetime.now(expires_at.tzinfo):
            record_auth_event(
                db,
                "temporary_password_expired",
                user_id=user.id,
                event_status="failed",
            )
            db.commit()
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "temporary_password_expired",
                    "message": "临时密码已过期，请重新申请密码重置",
                },
            )

    auth_session, refresh_token, csrf_token = create_session(db, user)
    access_token = create_access_token(user.id, auth_session.id, auth_session.token_version)
    user.last_login_at = datetime.now().isoformat(timespec="seconds")
    record_auth_event(db, "login_success", user_id=user.id, session_id=auth_session.id)
    db.commit()
    db.refresh(user)
    set_auth_cookies(
        response,
        access_token=access_token,
        refresh_token=refresh_token,
        csrf_token=csrf_token,
    )
    return {"user": user_to_dict(user)}


@router.post("/auth/refresh")
def refresh_auth(request: Request, response: Response, db: Session = Depends(get_db)):
    auth_session, refresh_token = get_refresh_session(request, db)
    if auth_session is None or not refresh_token:
        return refresh_failed(request)
    if auth_session.refresh_token_hash != hash_secret(refresh_token):
        return refresh_failed(request)
    verify_csrf(
        request,
        expected_binding=csrf_session_binding(auth_session.id),
        stored_hash=auth_session.csrf_token_hash,
    )
    user = db.get(User, auth_session.user_id)
    if (
        auth_session.revoked_at is not None
        or auth_session.expires_at <= utc_text()
        or user is None
        or not user.is_active
    ):
        return refresh_failed(request)
    rotated = rotate_refresh_token(db, auth_session, refresh_token)
    if rotated is None:
        return refresh_failed(request)
    new_refresh_token, csrf_token = rotated
    access_token = create_access_token(
        user.id,
        auth_session.id,
        auth_session.token_version,
    )
    record_auth_event(db, "session_refreshed", user_id=user.id, session_id=auth_session.id)
    db.commit()
    set_auth_cookies(
        response,
        access_token=access_token,
        refresh_token=new_refresh_token,
        csrf_token=csrf_token,
    )
    return {"success": True, "user": user_to_dict(user)}


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    auth_session, refresh_token = get_refresh_session(request, db)
    if auth_session is not None and refresh_token:
        verify_csrf(
            request,
            expected_binding=csrf_session_binding(auth_session.id),
            stored_hash=auth_session.csrf_token_hash,
        )
        if auth_session.refresh_token_hash == hash_secret(refresh_token):
            revoke_session(db, auth_session, "logout")
            record_auth_event(
                db,
                "logout",
                user_id=auth_session.user_id,
                session_id=auth_session.id,
            )
            db.commit()
    clear_auth_cookies(response)
    return {"success": True}


@router.post("/auth/logout-all")
def logout_all(
    request: Request,
    response: Response,
    current_user: User = Depends(get_session_user),
    db: Session = Depends(get_db),
):
    auth_session = request.state.auth_session
    revoke_all_sessions(db, current_user.id, "logout_all")
    record_auth_event(
        db,
        "logout_all",
        user_id=current_user.id,
        session_id=auth_session.id,
    )
    db.commit()
    clear_auth_cookies(response)
    return {"success": True}


@router.get("/auth/me")
def get_me(response: Response, current_user: User = Depends(get_session_user)):
    response.headers["Cache-Control"] = "no-store"
    return {"user": user_to_dict(current_user)}


@router.post("/auth/password-reset-requests", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    http_request: Request,
    request: PasswordResetRequestCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    verify_csrf(http_request, expected_binding=PREAUTH_BINDING)
    enforce_ip_rate_limit(db, http_request, "password_reset_request")
    note = normalize_request_note(request.request_note)
    username = normalize_username(request.username)
    user = None
    try:
        validated_username = validate_username(username)
    except HTTPException:
        validated_username = ""
    if validated_username:
        user = db.query(User).filter(User.username == validated_username).first()
    verify_password("password-reset-uniform-work", DUMMY_PASSWORD_HASH)
    create_password_reset_request(db, user=user, request_note=note)
    response.headers["Cache-Control"] = "no-store"
    return {"success": True, "message": ANONYMOUS_RESPONSE}


@router.post("/auth/change-temporary-password")
def change_temporary_password(
    request: TemporaryPasswordChangeRequest,
    response: Response,
    current_user: User = Depends(get_session_user),
    db: Session = Depends(get_db),
):
    enforce_user_rate_limit(db, current_user.id, "password_change")
    if not current_user.must_change_password:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "temporary_password_not_required",
                "message": "当前账号不需要修改临时密码",
            },
        )
    try:
        expires_at = datetime.fromisoformat(
            current_user.temporary_password_expires_at or ""
        )
    except ValueError:
        expires_at = None
    if expires_at is None or expires_at <= datetime.now(expires_at.tzinfo):
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "temporary_password_expired",
                "message": "临时密码已过期，请重新申请密码重置",
            },
        )
    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")
    if verify_password(request.new_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="新密码不能与临时密码相同")
    validate_password(request.new_password)
    current_user.password_hash = hash_password(request.new_password)
    current_user.must_change_password = False
    current_user.temporary_password_expires_at = None
    revoke_all_sessions(db, current_user.id, "temporary_password_changed")
    record_auth_event(db, "temporary_password_changed", user_id=current_user.id)
    db.commit()
    clear_auth_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return {"success": True, "message": "密码修改成功，请使用新密码重新登录"}


@router.post("/auth/change-password")
def change_password(
    request: ChangePasswordRequest,
    response: Response,
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
    revoke_all_sessions(db, current_user.id, "password_changed")
    record_auth_event(db, "password_changed", user_id=current_user.id)
    db.commit()
    clear_auth_cookies(response)
    return {"success": True, "message": "密码修改成功，请重新登录"}
