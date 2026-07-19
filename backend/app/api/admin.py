from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
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
)
from app.services.admin_audit_service import add_admin_audit_log
from app.services.admin_reporting_service import (
    get_usage_summary,
    get_user_usage_report,
    list_agent_runs,
    list_audit_logs,
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
from app.services.usage_service import get_local_now

router = APIRouter()


def _raise_admin_error(error: AdminServiceError) -> None:
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
    username: str | None = None,
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
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    try:
        reset_user_password(
            db,
            current_admin,
            user_id,
            request.new_password,
        )
    except AdminServiceError as error:
        _raise_admin_error(error)
    return {"success": True, "message": "临时密码已设置"}


@router.delete("/admin/users/{user_id}")
def delete_user(
    user_id: int,
    request: UserDeleteRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
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
    agent_name: str | None = None,
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


@router.post("/admin/maintenance/cleanup")
def cleanup(
    request: CleanupRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
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
    action: str | None = None,
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
