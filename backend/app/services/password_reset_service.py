import secrets
import string
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.input_validation import validate_safe_text
from app.core.security import hash_password, validate_password
from app.db.models import PasswordResetRequest, User
from app.services.admin_audit_service import add_admin_audit_log
from app.services.auth_session_service import (
    record_auth_event,
    revoke_all_sessions,
    utc_now,
    utc_text,
)

ANONYMOUS_RESPONSE = "如果账号存在且申请信息有效，管理员会处理你的申请。"
TEMPORARY_PASSWORD_ALPHABET = (
    string.ascii_letters + string.digits + "!@#$%*-_=+"
)


class PasswordResetServiceError(Exception):
    def __init__(self, status_code: int, detail):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def normalize_request_note(note: str) -> str:
    try:
        normalized = validate_safe_text(
            note,
            field_name="申请说明",
            max_chars=settings.password_reset_request_note_max_length,
            allow_empty=True,
            strip=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "<" in normalized or ">" in normalized:
        raise HTTPException(status_code=422, detail="申请说明不能包含 HTML 标记")
    return normalized


def create_password_reset_request(
    db: Session,
    *,
    user: User | None,
    request_note: str,
) -> None:
    if user is None:
        return
    existing = (
        db.query(PasswordResetRequest.id)
        .filter(
            PasswordResetRequest.user_id == user.id,
            PasswordResetRequest.status == "pending",
        )
        .first()
    )
    if existing is not None:
        return
    now = utc_text()
    db.add(
        PasswordResetRequest(
            user_id=user.id,
            status="pending",
            request_note=request_note,
            admin_note="",
            requested_at=now,
            processed_at=None,
            processed_by_user_id=None,
            created_at=now,
            updated_at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def _request_to_dict(item: PasswordResetRequest) -> dict:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "username": item.user.username,
        "status": item.status,
        "request_note": item.request_note,
        "admin_note": item.admin_note,
        "requested_at": item.requested_at,
        "processed_at": item.processed_at,
        "processed_by_user_id": item.processed_by_user_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def list_password_reset_requests(
    db: Session,
    *,
    request_status: str | None,
    page: int,
    page_size: int,
) -> dict:
    query = db.query(PasswordResetRequest).options(
        joinedload(PasswordResetRequest.user)
    )
    if request_status:
        query = query.filter(PasswordResetRequest.status == request_status)
    total = query.count()
    items = (
        query.order_by(
            PasswordResetRequest.requested_at.desc(),
            PasswordResetRequest.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [_request_to_dict(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _validate_admin_note(note: str) -> str:
    try:
        normalized = validate_safe_text(
            note,
            field_name="管理员备注",
            max_chars=500,
            allow_empty=True,
            strip=True,
        )
    except ValueError as exc:
        raise PasswordResetServiceError(422, str(exc)) from exc
    if "<" in normalized or ">" in normalized:
        raise PasswordResetServiceError(422, "管理员备注不能包含 HTML 标记")
    return normalized


def _generate_temporary_password() -> str:
    while True:
        password = "".join(
            secrets.choice(TEMPORARY_PASSWORD_ALPHABET) for _ in range(20)
        )
        if (
            any(char.islower() for char in password)
            and any(char.isupper() for char in password)
            and any(char.isdigit() for char in password)
            and any(char in "!@#$%*-_=+" for char in password)
        ):
            return password


def approve_password_reset_request(
    db: Session,
    *,
    request_id: int,
    admin: User,
    admin_note: str,
) -> tuple[dict, str]:
    note = _validate_admin_note(admin_note)
    item = (
        db.query(PasswordResetRequest)
        .filter(PasswordResetRequest.id == request_id)
        .with_for_update()
        .one_or_none()
    )
    if item is None:
        raise PasswordResetServiceError(404, "密码重置申请不存在")
    if item.status != "pending":
        raise PasswordResetServiceError(409, "该密码重置申请已处理")
    user = (
        db.query(User)
        .filter(User.id == item.user_id)
        .with_for_update()
        .one_or_none()
    )
    if user is None:
        raise PasswordResetServiceError(409, "申请对应用户已不存在")

    temporary_password = _generate_temporary_password()
    validate_password(temporary_password)
    now = utc_now()
    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    user.temporary_password_expires_at = utc_text(
        now + timedelta(hours=settings.temporary_password_ttl_hours)
    )
    revoke_all_sessions(db, user.id, "temporary_password_issued")
    record_auth_event(db, "temporary_password_issued", user_id=user.id)
    item.status = "approved"
    item.admin_note = note
    item.processed_at = utc_text(now)
    item.processed_by_user_id = admin.id
    item.updated_at = utc_text(now)
    add_admin_audit_log(
        db,
        admin_user_id=admin.id,
        action="approve_password_reset",
        target_user_id=user.id,
        resource_type="password_reset_request",
        resource_id=item.id,
        status="success",
        detail_summary="密码重置申请已批准并签发一次性临时密码",
        commit=False,
    )
    db.commit()
    db.refresh(item)
    return _request_to_dict(item), temporary_password


def reject_password_reset_request(
    db: Session,
    *,
    request_id: int,
    admin: User,
    admin_note: str,
) -> dict:
    note = _validate_admin_note(admin_note)
    item = (
        db.query(PasswordResetRequest)
        .filter(PasswordResetRequest.id == request_id)
        .with_for_update()
        .one_or_none()
    )
    if item is None:
        raise PasswordResetServiceError(404, "密码重置申请不存在")
    if item.status != "pending":
        raise PasswordResetServiceError(409, "该密码重置申请已处理")
    now = utc_text()
    item.status = "rejected"
    item.admin_note = note
    item.processed_at = now
    item.processed_by_user_id = admin.id
    item.updated_at = now
    add_admin_audit_log(
        db,
        admin_user_id=admin.id,
        action="reject_password_reset",
        target_user_id=item.user_id,
        resource_type="password_reset_request",
        resource_id=item.id,
        status="success",
        detail_summary="密码重置申请已拒绝",
        commit=False,
    )
    db.commit()
    db.refresh(item)
    return _request_to_dict(item)
