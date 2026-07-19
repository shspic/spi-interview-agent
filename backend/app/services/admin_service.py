
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import hash_password, validate_password
from app.db.models import (
    AgentRun,
    FileRecord,
    HistoryRecord,
    ImprovementTask,
    InterviewRecord,
    InterviewSession,
    InterviewTurn,
    ResumeProjectDescription,
    TargetJob,
    UsageEvent,
    User,
    UserProfile,
)
from app.services.admin_audit_service import add_admin_audit_log
from app.services.auth_session_service import record_auth_event, revoke_all_sessions
from app.services.usage_service import get_user_usage
from app.services.vector_store import delete_user_vectors
from app.services.upload_security import (
    UploadSecurityError,
    resolve_owned_storage_path,
)


class AdminServiceError(Exception):
    def __init__(self, status_code: int, detail):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def get_admin_user_summary(db: Session, user: User) -> dict:
    file_count = (
        db.query(func.count(FileRecord.id))
        .filter(FileRecord.user_id == user.id)
        .scalar()
        or 0
    )
    session_count = (
        db.query(func.count(InterviewSession.id))
        .filter(InterviewSession.user_id == user.id)
        .scalar()
        or 0
    )
    return {
        "id": user.id,
        "username": user.username,
        "is_active": bool(user.is_active),
        "is_admin": bool(user.is_admin),
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "today_usage": get_user_usage(db, user.id)["items"],
        "file_count": file_count,
        "interview_session_count": session_count,
    }


def list_admin_users(
    db: Session,
    *,
    username: str | None,
    is_active: bool | None,
    is_admin: bool | None,
    sort_order: str,
    page: int,
    page_size: int,
) -> dict:
    query = db.query(User)
    if username:
        query = query.filter(User.username.contains(username.strip().lower()))
    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))
    if is_admin is not None:
        query = query.filter(User.is_admin.is_(is_admin))
    total = query.count()
    order_by = User.created_at.asc() if sort_order == "asc" else User.created_at.desc()
    users = (
        query.order_by(order_by, User.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [get_admin_user_summary(db, user) for user in users],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_admin_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise AdminServiceError(404, "目标用户不存在")
    return user


def set_user_active_status(
    db: Session,
    admin: User,
    user_id: int,
    is_active: bool,
) -> User:
    try:
        user = get_admin_user(db, user_id)
        if user.is_admin and user.is_active and not is_active:
            active_admin_count = (
                db.query(func.count(User.id))
                .filter(User.is_admin.is_(True), User.is_active.is_(True))
                .scalar()
                or 0
            )
            if active_admin_count <= 1:
                raise AdminServiceError(409, "不能禁用最后一个可用管理员")
        user.is_active = is_active
        if not is_active:
            revoke_all_sessions(db, user.id, "account_disabled")
            record_auth_event(db, "account_disabled", user_id=user.id)
        add_admin_audit_log(
            db,
            admin_user_id=admin.id,
            action="enable_user" if is_active else "disable_user",
            target_user_id=user.id,
            resource_type="user",
            resource_id=user.id,
            status="success",
            detail_summary="用户账号状态已更新",
            commit=False,
        )
        db.commit()
        db.refresh(user)
        return user
    except AdminServiceError as exc:
        db.rollback()
        add_admin_audit_log(
            db,
            admin_user_id=admin.id,
            action="enable_user" if is_active else "disable_user",
            target_user_id=user_id,
            resource_type="user",
            resource_id=user_id,
            status="failed",
            detail_summary=str(exc.detail),
        )
        raise


def reset_user_password(
    db: Session,
    admin: User,
    user_id: int,
    new_password: str,
) -> None:
    try:
        user = get_admin_user(db, user_id)
        validate_password(new_password)
        user.password_hash = hash_password(new_password)
        revoke_all_sessions(db, user.id, "admin_password_reset")
        record_auth_event(db, "admin_password_reset", user_id=user.id)
        add_admin_audit_log(
            db,
            admin_user_id=admin.id,
            action="reset_password",
            target_user_id=user.id,
            resource_type="user",
            resource_id=user.id,
            status="success",
            detail_summary="用户密码已由管理员重置",
            commit=False,
        )
        db.commit()
    except (AdminServiceError, HTTPException) as exc:
        db.rollback()
        status_code = getattr(exc, "status_code", 400)
        detail = getattr(exc, "detail", "密码不符合要求")
        add_admin_audit_log(
            db,
            admin_user_id=admin.id,
            action="reset_password",
            target_user_id=user_id,
            resource_type="user",
            resource_id=user_id,
            status="failed",
            detail_summary=str(detail),
        )
        if isinstance(exc, AdminServiceError):
            raise
        raise AdminServiceError(status_code, detail) from exc


def _user_resource_counts(db: Session, user_id: int) -> dict:
    models = {
        "files": FileRecord,
        "history_records": HistoryRecord,
        "interview_records": InterviewRecord,
        "profiles": UserProfile,
        "target_jobs": TargetJob,
        "interview_sessions": InterviewSession,
        "interview_turns": InterviewTurn,
        "improvement_tasks": ImprovementTask,
        "resume_project_descriptions": ResumeProjectDescription,
        "agent_runs": AgentRun,
        "usage_events": UsageEvent,
    }
    return {
        name: db.query(func.count(model.id)).filter(model.user_id == user_id).scalar()
        or 0
        for name, model in models.items()
    }


def delete_user_and_data(
    db: Session,
    admin: User,
    user_id: int,
    confirm_username: str,
) -> dict:
    if admin.id == user_id:
        add_admin_audit_log(
            db,
            admin_user_id=admin.id,
            action="delete_user",
            target_user_id=user_id,
            resource_type="user",
            resource_id=user_id,
            status="failed",
            detail_summary="管理员不能删除自己的账号",
        )
        raise AdminServiceError(409, "管理员不能删除自己的账号")
    try:
        user = get_admin_user(db, user_id)
    except AdminServiceError as exc:
        add_admin_audit_log(
            db,
            admin_user_id=admin.id,
            action="delete_user",
            target_user_id=user_id,
            resource_type="user",
            resource_id=user_id,
            status="failed",
            detail_summary=str(exc.detail),
        )
        raise
    if confirm_username != user.username:
        add_admin_audit_log(
            db,
            admin_user_id=admin.id,
            action="delete_user",
            target_user_id=user.id,
            resource_type="user",
            resource_id=user.id,
            status="failed",
            detail_summary="用户名确认不匹配",
        )
        raise AdminServiceError(422, "确认用户名与目标用户不匹配")

    counts = _user_resource_counts(db, user.id)
    failures = []
    files = db.query(FileRecord).filter(FileRecord.user_id == user.id).all()
    resolved_files = []
    for record in files:
        try:
            resolved_files.append(
                (record, resolve_owned_storage_path(user.id, record.file_path))
            )
        except UploadSecurityError as exc:
            failures.append(
                {
                    "resource_type": "file",
                    "resource_id": record.file_id,
                    "error_type": exc.error_code,
                }
            )
    if not failures:
        try:
            delete_user_vectors(user.id)
        except Exception as exc:
            failures.append(
                {
                    "resource_type": "vector",
                    "resource_id": str(user.id),
                    "error_type": type(exc).__name__,
                }
            )
    if not failures:
        for record, file_path in resolved_files:
            if file_path.exists():
                try:
                    file_path.unlink()
                except OSError as exc:
                    failures.append(
                        {
                            "resource_type": "file",
                            "resource_id": record.file_id,
                            "error_type": type(exc).__name__,
                        }
                    )

    if failures:
        add_admin_audit_log(
            db,
            admin_user_id=admin.id,
            action="delete_user",
            target_user_id=user.id,
            resource_type="user",
            resource_id=user.id,
            status="failed",
            detail_summary=f"用户清理未完成，失败项 {len(failures)} 个",
        )
        return {
            "success": False,
            "deleted_counts": {},
            "failed_items": failures,
        }

    db.delete(user)
    db.commit()
    add_admin_audit_log(
        db,
        admin_user_id=admin.id,
        action="delete_user",
        target_user_id=None,
        resource_type="user",
        resource_id=user_id,
        status="success",
        detail_summary="用户及关联业务数据已删除",
    )
    return {
        "success": True,
        "deleted_counts": {"users": 1, **counts},
        "failed_items": [],
    }
