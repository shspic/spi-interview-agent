from datetime import datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    AgentRun,
    FileRecord,
    HistoryRecord,
    ImprovementTask,
    InterviewRecord,
    InterviewSession,
    InterviewTurn,
    ResumeProjectDescription,
    UserDataDeletionLog,
)
from app.services.vector_store import delete_user_vectors

USER_DATA_CLEANUP_CONFIRMATION = "DELETE_MY_DATA"
RETAINED_RESOURCES = [
    "user",
    "user_profile",
    "target_jobs",
    "usage_events",
    "daily_usage_counters",
    "admin_audit_logs",
]


def _resource_counts(db: Session, user_id: int) -> dict[str, int]:
    models = {
        "files": FileRecord,
        "history_records": HistoryRecord,
        "interview_records": InterviewRecord,
        "interview_sessions": InterviewSession,
        "interview_turns": InterviewTurn,
        "improvement_tasks": ImprovementTask,
        "resume_project_descriptions": ResumeProjectDescription,
        "agent_runs": AgentRun,
    }
    return {
        name: db.query(func.count(model.id))
        .filter(model.user_id == user_id)
        .scalar()
        or 0
        for name, model in models.items()
    }


def preview_user_data_cleanup(db: Session, user_id: int) -> dict:
    return {
        "estimated_counts": _resource_counts(db, user_id),
        "retained_resources": RETAINED_RESOURCES,
        "confirmation_text": USER_DATA_CLEANUP_CONFIRMATION,
    }


def _add_deletion_log(
    db: Session,
    *,
    user_id: int,
    status: str,
    deleted_counts: dict,
    failure_count: int,
    detail_summary: str,
) -> None:
    db.add(
        UserDataDeletionLog(
            user_id=user_id,
            status=status,
            deleted_counts=deleted_counts,
            failure_count=failure_count,
            detail_summary=detail_summary,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
    )


def record_rejected_cleanup(db: Session, user_id: int, reason: str) -> None:
    _add_deletion_log(
        db,
        user_id=user_id,
        status="failed",
        deleted_counts={},
        failure_count=1,
        detail_summary=reason,
    )
    db.commit()


def cleanup_user_business_data(db: Session, user_id: int) -> dict:
    counts = _resource_counts(db, user_id)
    files = db.query(FileRecord).filter(FileRecord.user_id == user_id).all()
    failures = []

    try:
        delete_user_vectors(user_id)
    except Exception as exc:
        failures.append(
            {
                "resource_type": "vector",
                "resource_id": str(user_id),
                "error_type": type(exc).__name__,
            }
        )

    if not failures:
        for record in files:
            file_path = Path(record.file_path)
            if not file_path.exists():
                continue
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
        _add_deletion_log(
            db,
            user_id=user_id,
            status="failed",
            deleted_counts={},
            failure_count=len(failures),
            detail_summary=f"个人业务数据清理未完成，失败项 {len(failures)} 个",
        )
        db.commit()
        return {
            "success": False,
            "deleted_counts": {},
            "failed_items": failures,
            "retained_resources": RETAINED_RESOURCES,
        }

    deletion_models = (
        ImprovementTask,
        InterviewTurn,
        AgentRun,
        ResumeProjectDescription,
        InterviewSession,
        InterviewRecord,
        HistoryRecord,
        FileRecord,
    )
    try:
        for model in deletion_models:
            db.query(model).filter(model.user_id == user_id).delete(
                synchronize_session=False
            )
        _add_deletion_log(
            db,
            user_id=user_id,
            status="success",
            deleted_counts=counts,
            failure_count=0,
            detail_summary="个人业务数据已清理，账号与持续配置保留",
        )
        db.commit()
    except Exception:
        db.rollback()
        _add_deletion_log(
            db,
            user_id=user_id,
            status="failed",
            deleted_counts={},
            failure_count=1,
            detail_summary="个人业务数据数据库清理失败",
        )
        db.commit()
        raise

    return {
        "success": True,
        "deleted_counts": counts,
        "failed_items": [],
        "retained_resources": RETAINED_RESOURCES,
    }
