from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AgentRun,
    AuthSecurityEvent,
    DailyUsageCounter,
    FileRecord,
    HistoryRecord,
    ImprovementTask,
    InterviewRecord,
    InterviewSession,
    InterviewTurn,
    ResumeProjectDescription,
    UsageEvent,
)
from app.services.usage_service import get_local_now
from app.services.vector_store import delete_file_vectors
from app.services.upload_security import resolve_owned_storage_path

CLEANUP_CONFIRMATION = "DELETE_EXPIRED_DATA"


def get_retention_cutoff(now: datetime | None = None) -> datetime:
    if settings.data_retention_days <= 0:
        raise RuntimeError("DATA_RETENTION_DAYS 必须大于 0")
    local_now = get_local_now(now)
    return local_now - timedelta(days=settings.data_retention_days)


def _old_session_ids(db: Session, cutoff_text: str):
    return db.query(InterviewSession.id).filter(
        InterviewSession.created_at < cutoff_text
    )


def preview_expired_data(db: Session, now: datetime | None = None) -> dict:
    cutoff = get_retention_cutoff(now)
    cutoff_text = cutoff.replace(tzinfo=None).isoformat(timespec="seconds")
    cutoff_date = cutoff.date().isoformat()
    old_session_ids = _old_session_ids(db, cutoff_text)
    counts = {
        "files": db.query(func.count(FileRecord.id))
        .filter(FileRecord.created_at < cutoff_text)
        .scalar()
        or 0,
        "history_records": db.query(func.count(HistoryRecord.id))
        .filter(HistoryRecord.created_at < cutoff_text)
        .scalar()
        or 0,
        "interview_records": db.query(func.count(InterviewRecord.id))
        .filter(InterviewRecord.created_at < cutoff_text)
        .scalar()
        or 0,
        "interview_sessions": old_session_ids.count(),
        "interview_turns": db.query(func.count(InterviewTurn.id))
        .filter(InterviewTurn.session_id.in_(old_session_ids))
        .scalar()
        or 0,
        "improvement_tasks": db.query(func.count(ImprovementTask.id))
        .filter(ImprovementTask.session_id.in_(old_session_ids))
        .scalar()
        or 0,
        "resume_project_descriptions": db.query(
            func.count(ResumeProjectDescription.id)
        )
        .filter(ResumeProjectDescription.created_at < cutoff_text)
        .scalar()
        or 0,
        "agent_runs": db.query(func.count(AgentRun.id))
        .filter(AgentRun.created_at < cutoff_text)
        .scalar()
        or 0,
        "usage_events": db.query(func.count(UsageEvent.id))
        .filter(UsageEvent.usage_date < cutoff_date)
        .scalar()
        or 0,
        "daily_usage_counters": db.query(func.count(DailyUsageCounter.id))
        .filter(DailyUsageCounter.usage_date < cutoff_date)
        .scalar()
        or 0,
        "auth_security_events": db.query(func.count(AuthSecurityEvent.id))
        .filter(AuthSecurityEvent.created_at < cutoff_text)
        .scalar()
        or 0,
    }
    return {
        "cutoff": cutoff.isoformat(timespec="seconds"),
        "retention_days": settings.data_retention_days,
        "timezone": settings.app_timezone,
        "estimated_counts": counts,
    }


def cleanup_expired_data(db: Session, now: datetime | None = None) -> dict:
    preview = preview_expired_data(db, now)
    cutoff = get_retention_cutoff(now)
    cutoff_text = cutoff.replace(tzinfo=None).isoformat(timespec="seconds")
    cutoff_date = cutoff.date().isoformat()
    deleted_counts = {name: 0 for name in preview["estimated_counts"]}
    failed_items = []
    turn_count_before = db.query(func.count(InterviewTurn.id)).scalar() or 0
    task_count_before = db.query(func.count(ImprovementTask.id)).scalar() or 0
    agent_run_count_before = db.query(func.count(AgentRun.id)).scalar() or 0

    old_files = (
        db.query(FileRecord)
        .filter(FileRecord.created_at < cutoff_text)
        .order_by(FileRecord.id.asc())
        .all()
    )
    for record in old_files:
        if record.user_id is None:
            failed_items.append(
                {
                    "resource_type": "file",
                    "resource_id": record.file_id,
                    "error_type": "legacy_owner_missing",
                }
            )
            continue
        try:
            file_path = resolve_owned_storage_path(
                record.user_id,
                record.file_path,
            )
            delete_file_vectors(record.user_id, record.file_id)
            if file_path.exists():
                file_path.unlink()
        except Exception as exc:
            failed_items.append(
                {
                    "resource_type": "file",
                    "resource_id": record.file_id,
                    "error_type": type(exc).__name__,
                }
            )
            continue
        db.delete(record)
        deleted_counts["files"] += 1

    old_session_ids = [item[0] for item in _old_session_ids(db, cutoff_text).all()]
    if old_session_ids:
        deleted_counts["interview_sessions"] = (
            db.query(InterviewSession)
            .filter(InterviewSession.id.in_(old_session_ids))
            .delete(synchronize_session=False)
        )

    deletion_queries = {
        "history_records": db.query(HistoryRecord).filter(
            HistoryRecord.created_at < cutoff_text
        ),
        "interview_records": db.query(InterviewRecord).filter(
            InterviewRecord.created_at < cutoff_text
        ),
        "resume_project_descriptions": db.query(ResumeProjectDescription).filter(
            ResumeProjectDescription.created_at < cutoff_text
        ),
        "agent_runs": db.query(AgentRun).filter(AgentRun.created_at < cutoff_text),
        "usage_events": db.query(UsageEvent).filter(
            UsageEvent.usage_date < cutoff_date
        ),
        "daily_usage_counters": db.query(DailyUsageCounter).filter(
            DailyUsageCounter.usage_date < cutoff_date
        ),
        "auth_security_events": db.query(AuthSecurityEvent).filter(
            AuthSecurityEvent.created_at < cutoff_text
        ),
    }
    for name, query in deletion_queries.items():
        query.delete(synchronize_session=False)

    deleted_counts["interview_turns"] = turn_count_before - (
        db.query(func.count(InterviewTurn.id)).scalar() or 0
    )
    deleted_counts["improvement_tasks"] = task_count_before - (
        db.query(func.count(ImprovementTask.id)).scalar() or 0
    )
    deleted_counts["agent_runs"] = agent_run_count_before - (
        db.query(func.count(AgentRun.id)).scalar() or 0
    )
    for name, query in deletion_queries.items():
        if name in {"agent_runs"}:
            continue
        deleted_counts[name] = preview["estimated_counts"][name]

    db.commit()
    return {
        "success": not failed_items,
        "cutoff": preview["cutoff"],
        "retention_days": preview["retention_days"],
        "timezone": preview["timezone"],
        "deleted_counts": deleted_counts,
        "failed_items": failed_items,
    }
