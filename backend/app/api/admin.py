from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.security import get_current_admin
from app.db.database import get_db
from app.db.models import RegistrationSetting, User
from app.schemas.admin import (
    AdminPasswordResetRequest,
    CleanupRequest,
    InviteCodeUpdateRequest,
    UserDeleteRequest,
    UserStatusUpdateRequest,
    PasswordResetDecisionRequest,
)
from app.services.admin_audit_service import add_admin_audit_log
from app.services.admin_reporting_service import (
    get_usage_summary,
    get_user_usage_report,
    get_worker_status,
    list_agent_runs,
    list_audit_logs,
    list_background_jobs,
)
from app.services.admin_service import (
    AdminServiceError,
    delete_user_and_data,
    get_admin_user,
    get_admin_user_summary,
    list_admin_users,
    reset_user_password,
    set_user_active_status,
)
from app.services.data_retention_service import (
    CLEANUP_CONFIRMATION,
    cleanup_expired_data,
    preview_expired_data,
)
from app.services.registration_setting_service import (
    RegistrationSettingError,
    update_registration_invite_code,
)
from app.services.rate_limit_service import enforce_user_rate_limit
from app.services.password_reset_service import (
    PasswordResetServiceError,
    approve_password_reset_request,
    list_password_reset_requests,
    reject_password_reset_request,
)
from app.services.usage_service import get_local_now
from app.api.deprecation import enforce_sync_long_task_policy

router = APIRouter()


def _raise_admin_error(error: AdminServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _raise_password_reset_error(error: PasswordResetServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _date_range(
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date]:
    end = date_to or get_local_now().date()
    start = date_from or end - timedelta(days=6)
    if start > end:
        raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")
    return start, end


@router.get("/admin/users")
def get_users(
    username: str | None = Query(
        default=None,
        max_length=64,
        pattern=r"^[A-Za-z0-9_]*$",
    ),
    is_active: bool | None = None,
    is_admin: bool | None = None,
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    return list_admin_users(
        db,
        username=username,
        is_active=is_active,
        is_admin=is_admin,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.get("/admin/users/{user_id}")
def get_user_detail(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    try:
        return get_admin_user_summary(db, get_admin_user(db, user_id))
    except AdminServiceError as error:
        _raise_admin_error(error)


@router.patch("/admin/users/{user_id}/status")
def update_user_status(
    user_id: int,
    request: UserStatusUpdateRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    enforce_user_rate_limit(db, current_admin.id, "admin_write")
    try:
        user = set_user_active_status(
            db,
            current_admin,
            user_id,
            request.is_active,
        )
    except AdminServiceError as error:
        _raise_admin_error(error)
    return {
        "success": True,
        "user": get_admin_user_summary(db, user),
    }


@router.post("/admin/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    request: AdminPasswordResetRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    enforce_user_rate_limit(db, current_admin.id, "admin_write")
    try:
        reset_user_password(
            db,
            current_admin,
            user_id,
            request.new_password,
        )
    except AdminServiceError as error:
        _raise_admin_error(error)
    response.headers["Cache-Control"] = "no-store"
    return {"success": True, "message": "临时密码已设置"}


@router.get("/admin/password-reset-requests")
def get_password_reset_requests(
    request_status: Literal["pending", "approved", "rejected", "cancelled"] | None = Query(
        default=None,
        alias="status",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    return list_password_reset_requests(
        db,
        request_status=request_status,
        page=page,
        page_size=page_size,
    )


@router.post("/admin/password-reset-requests/{request_id}/approve")
def approve_password_reset(
    request_id: int,
    request: PasswordResetDecisionRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    enforce_user_rate_limit(db, current_admin.id, "admin_write")
    try:
        item, temporary_password = approve_password_reset_request(
            db,
            request_id=request_id,
            admin=current_admin,
            admin_note=request.admin_note,
        )
    except PasswordResetServiceError as error:
        db.rollback()
        _raise_password_reset_error(error)
    response.headers["Cache-Control"] = "no-store"
    return {
        "success": True,
        "request": item,
        "temporary_password": temporary_password,
    }


@router.post("/admin/password-reset-requests/{request_id}/reject")
def reject_password_reset(
    request_id: int,
    request: PasswordResetDecisionRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    enforce_user_rate_limit(db, current_admin.id, "admin_write")
    try:
        item = reject_password_reset_request(
            db,
            request_id=request_id,
            admin=current_admin,
            admin_note=request.admin_note,
        )
    except PasswordResetServiceError as error:
        db.rollback()
        _raise_password_reset_error(error)
    return {"success": True, "request": item}


@router.delete("/admin/users/{user_id}")
def delete_user(
    user_id: int,
    request: UserDeleteRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    enforce_user_rate_limit(db, current_admin.id, "admin_write")
    try:
        return delete_user_and_data(
            db,
            current_admin,
            user_id,
            request.confirm_username,
        )
    except AdminServiceError as error:
        _raise_admin_error(error)


@router.get("/admin/usage/summary")
def usage_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    start, end = _date_range(date_from, date_to)
    return get_usage_summary(db, start, end)


@router.get("/admin/usage/users/{user_id}")
def user_usage(
    user_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    start, end = _date_range(date_from, date_to)
    try:
        return get_user_usage_report(db, user_id, start, end)
    except AdminServiceError as error:
        _raise_admin_error(error)


@router.get("/admin/agent-runs")
def agent_runs(
    user_id: int | None = None,
    session_id: int | None = None,
    agent_name: str | None = Query(
        default=None,
        max_length=64,
        pattern=r"^[a-z_]*$",
    ),
    status: Literal["success", "error"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    return list_agent_runs(
        db,
        user_id=user_id,
        session_id=session_id,
        agent_name=agent_name,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@router.get("/admin/settings/registration")
def registration_setting_status(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    registration_setting = db.get(RegistrationSetting, 1)
    return {
        "configured": registration_setting is not None,
        "updated_at": (
            registration_setting.updated_at if registration_setting else None
        ),
        "updated_by": (
            registration_setting.updated_by if registration_setting else None
        ),
    }


@router.put("/admin/settings/registration/invite-code")
def update_invite_code(
    request: InviteCodeUpdateRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    enforce_user_rate_limit(db, current_admin.id, "admin_write")
    try:
        registration_setting = update_registration_invite_code(
            db,
            request.invite_code,
            current_admin.id,
        )
    except RegistrationSettingError as error:
        add_admin_audit_log(
            db,
            admin_user_id=current_admin.id,
            action="update_invite_code",
            resource_type="registration_setting",
            resource_id=1,
            status="failed",
            detail_summary=error.detail,
        )
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    add_admin_audit_log(
        db,
        admin_user_id=current_admin.id,
        action="update_invite_code",
        resource_type="registration_setting",
        resource_id=1,
        status="success",
        detail_summary="注册邀请码已更新",
    )
    return {
        "success": True,
        "configured": True,
        "updated_at": registration_setting.updated_at,
        "updated_by": registration_setting.updated_by,
    }


@router.post("/admin/maintenance/cleanup-preview")
def cleanup_preview(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    return preview_expired_data(db)


@router.post("/admin/maintenance/cleanup", deprecated=True)
def cleanup(
    request: CleanupRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    enforce_sync_long_task_policy(response, "/api/tasks/retention-cleanup")
    enforce_user_rate_limit(db, current_admin.id, "admin_write")
    if request.confirm != CLEANUP_CONFIRMATION:
        add_admin_audit_log(
            db,
            admin_user_id=current_admin.id,
            action="cleanup_data",
            resource_type="maintenance",
            status="failed",
            detail_summary="清理确认字段不匹配",
        )
        raise HTTPException(status_code=422, detail="清理确认字段不匹配")
    try:
        result = cleanup_expired_data(db)
    except Exception as error:
        db.rollback()
        add_admin_audit_log(
            db,
            admin_user_id=current_admin.id,
            action="cleanup_data",
            resource_type="maintenance",
            status="failed",
            detail_summary=f"数据清理失败：{type(error).__name__}",
        )
        raise HTTPException(status_code=500, detail="数据清理失败") from error
    add_admin_audit_log(
        db,
        admin_user_id=current_admin.id,
        action="cleanup_data",
        resource_type="maintenance",
        status="success" if result["success"] else "failed",
        detail_summary=(
            "过期数据清理完成"
            if result["success"]
            else f"过期数据部分清理，失败项 {len(result['failed_items'])} 个"
        ),
    )
    return result


@router.get("/admin/audit-logs")
def audit_logs(
    action: str | None = Query(
        default=None,
        max_length=64,
        pattern=r"^[a-z_]*$",
    ),
    admin_user_id: int | None = None,
    target_user_id: int | None = None,
    status: Literal["success", "failed"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    return list_audit_logs(
        db,
        action=action,
        admin_user_id=admin_user_id,
        target_user_id=target_user_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@router.get("/admin/background-jobs")
def background_jobs(
    user_id: int | None = None,
    task_type: str | None = Query(default=None, max_length=64, pattern=r"^[a-z_]*$"),
    status: Literal[
        "queued",
        "running",
        "retry_wait",
        "cancel_requested",
        "succeeded",
        "failed",
        "cancelled",
        "timed_out",
    ]
    | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    return list_background_jobs(
        db,
        user_id=user_id,
        task_type=task_type,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/admin/workers")
def worker_status(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    return get_worker_status(db)
