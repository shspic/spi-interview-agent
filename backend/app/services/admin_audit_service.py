from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import AdminAuditLog


def add_admin_audit_log(
    db: Session,
    *,
    admin_user_id: int | None,
    action: str,
    resource_type: str,
    status: str,
    target_user_id: int | None = None,
    resource_id: str | int | None = None,
    detail_summary: str = "",
    commit: bool = True,
) -> AdminAuditLog:
    log = AdminAuditLog(
        admin_user_id=admin_user_id,
        action=action,
        target_user_id=target_user_id,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        status=status,
        detail_summary=detail_summary[:500],
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    db.add(log)
    if commit:
        db.commit()
        db.refresh(log)
    return log
