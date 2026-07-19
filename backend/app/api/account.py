from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user, verify_password
from app.db.database import get_db
from app.db.models import User
from app.schemas.account import DataCleanupPreviewRequest, DataCleanupRequest
from app.services.account_data_service import (
    USER_DATA_CLEANUP_CONFIRMATION,
    cleanup_user_business_data,
    preview_user_data_cleanup,
    record_rejected_cleanup,
)
from app.services.rate_limit_service import enforce_user_rate_limit

router = APIRouter()


@router.post("/account/data-cleanup-preview")
def preview_data_cleanup(
    request: DataCleanupPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return preview_user_data_cleanup(db, current_user.id)


@router.post("/account/data-cleanup")
def cleanup_data(
    request: DataCleanupRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_user_rate_limit(db, current_user.id, "password_change")
    if request.confirm != USER_DATA_CLEANUP_CONFIRMATION:
        record_rejected_cleanup(db, current_user.id, "个人数据清理确认文本不匹配")
        raise HTTPException(status_code=422, detail="确认文本不匹配")
    if not verify_password(request.current_password, current_user.password_hash):
        record_rejected_cleanup(db, current_user.id, "个人数据清理密码校验失败")
        raise HTTPException(status_code=400, detail="当前密码错误")
    return cleanup_user_business_data(db, current_user.id)
