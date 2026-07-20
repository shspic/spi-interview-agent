from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    BackgroundJob,
    BackgroundJobArtifact,
    BackgroundJobEvent,
    UsageEvent,
)
from app.services.rate_limit_service import hash_identifier
from app.services.usage_service import (
    UsageReservation,
    UsageReservationConflict,
    UsageServiceError,
    commit_usage,
    release_usage,
    reserve_usage,
)

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}
CLAIMABLE_STATUSES = {"queued", "retry_wait"}
LEGAL_TRANSITIONS = {
    "queued": {"running", "cancelled", "failed"},
    "retry_wait": {"running", "cancelled", "failed"},
    "running": {
        "succeeded",
        "failed",
        "cancel_requested",
        "timed_out",
        "retry_wait",
    },
    "cancel_requested": {"cancelled", "failed", "timed_out"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
    "timed_out": set(),
}
TASK_TIMEOUTS = {
    "knowledge_rebuild": 1800,
    "agent_ask": 600,
    "job_analysis": 600,
    "interview_start": 900,
    "interview_evaluation": 900,
    "improvement_generation": 900,
    "resume_generation": 900,
    "data_retention_cleanup": 1800,
}
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class BackgroundJobError(Exception):
    def __init__(self, status_code: int, detail):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds")


def validate_idempotency_key(value: str | None) -> str:
    normalized = (value or "").strip()
    if not IDEMPOTENCY_PATTERN.fullmatch(normalized):
        raise BackgroundJobError(
            422,
            {
                "error_code": "invalid_idempotency_key",
                "message": "Idempotency-Key 必须为 8 到 128 位安全字符",
            },
        )
    return normalized


def _event(
    job: BackgroundJob,
    from_status: str | None,
    to_status: str,
) -> BackgroundJobEvent:
    return BackgroundJobEvent(
        job_id=job.id,
        user_id=job.user_id,
        from_status=from_status,
        to_status=to_status,
        phase=job.phase,
        message_code=job.message_code,
        attempt_count=job.attempt_count,
        created_at=utc_text(),
    )


def transition_job(
    db: Session,
    job: BackgroundJob,
    target_status: str,
    *,
    phase: str,
    message_code: str,
    progress_percent: int | None = None,
    error_code: str | None = None,
    error_summary: str | None = None,
    commit: bool = True,
) -> BackgroundJob:
    current = job.status
    if target_status == current:
        return job
    if target_status not in LEGAL_TRANSITIONS.get(current, set()):
        raise BackgroundJobError(
            409,
            {
                "error_code": "invalid_job_transition",
                "message": "任务当前状态不允许该操作",
            },
        )
    job.status = target_status
    job.phase = phase
    job.message_code = message_code
    if progress_percent is not None:
        job.progress_percent = min(100, max(job.progress_percent, progress_percent))
    job.error_code = error_code[:100] if error_code else None
    job.error_summary = error_summary[:300] if error_summary else None
    if target_status in TERMINAL_STATUSES:
        job.completed_at = utc_text()
        job.lease_expires_at = None
        job.worker_id = None
        if target_status == "succeeded":
            job.progress_percent = 100
    db.add(_event(job, current, target_status))
    if commit:
        db.commit()
        db.refresh(job)
    return job


def get_owned_job(db: Session, user_id: int, job_id: str) -> BackgroundJob:
    job = (
        db.query(BackgroundJob)
        .filter(BackgroundJob.id == job_id, BackgroundJob.user_id == user_id)
        .first()
    )
    if job is None:
        raise BackgroundJobError(404, "任务不存在")
    return job


def _artifact_for_job(db: Session, job: BackgroundJob) -> BackgroundJobArtifact | None:
    reference = job.result_reference or job.input_reference
    if not reference or not reference.startswith("artifact:"):
        return None
    artifact_id = reference.split(":", 1)[1]
    return (
        db.query(BackgroundJobArtifact)
        .filter(
            BackgroundJobArtifact.id == artifact_id,
            BackgroundJobArtifact.user_id == job.user_id,
        )
        .first()
    )


def serialize_job(db: Session, job: BackgroundJob, *, include_result: bool = True) -> dict:
    result = None
    if include_result and job.status == "succeeded":
        artifact = _artifact_for_job(db, job)
        result = artifact.result_data if artifact is not None else None
    return {
        "task_id": job.id,
        "task_type": job.task_type,
        "status": job.status,
        "progress_percent": job.progress_percent,
        "phase": job.phase,
        "message_code": job.message_code,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "cancel_requested_at": job.cancel_requested_at,
        "error_code": job.error_code,
        "error_summary": job.error_summary,
        "result": result,
        "poll_after_seconds": 1 if job.status not in TERMINAL_STATUSES else None,
    }


def create_background_job(
    db: Session,
    *,
    user_id: int,
    task_type: str,
    idempotency_key: str,
    input_data: dict | None = None,
    input_reference: str | None = None,
    quota_usage_type: str | None = None,
    max_attempts: int | None = None,
) -> tuple[BackgroundJob, bool]:
    if task_type not in TASK_TIMEOUTS:
        raise BackgroundJobError(422, "不支持的任务类型")
    normalized_key = validate_idempotency_key(idempotency_key)
    key_hash = hash_identifier("background_job", normalized_key)
    existing = (
        db.query(BackgroundJob)
        .filter(
            BackgroundJob.user_id == user_id,
            BackgroundJob.task_type == task_type,
            BackgroundJob.idempotency_key_hash == key_hash,
        )
        .first()
    )
    if existing is not None:
        return existing, False

    now = utc_now()
    artifact = None
    reference = input_reference
    if input_data is not None:
        artifact = BackgroundJobArtifact(
            id=str(uuid4()),
            user_id=user_id,
            artifact_type=f"{task_type}_request",
            input_data=input_data,
            result_data=None,
            created_at=utc_text(now),
            updated_at=utc_text(now),
            expires_at=utc_text(now + timedelta(days=settings.job_history_days)),
        )
        db.add(artifact)
        reference = f"artifact:{artifact.id}"

    job = BackgroundJob(
        id=str(uuid4()),
        user_id=user_id,
        task_type=task_type,
        status="queued",
        progress_percent=0,
        phase="queued",
        message_code="job_queued",
        idempotency_key_hash=key_hash,
        input_reference=reference,
        created_at=utc_text(now),
        available_at=utc_text(now),
        attempt_count=0,
        max_attempts=max_attempts or settings.job_max_attempts,
        timeout_seconds=TASK_TIMEOUTS[task_type],
        quota_usage_type=quota_usage_type,
    )
    db.add(job)
    db.flush()
    db.add(_event(job, None, "queued"))
    try:
        db.commit()
        db.refresh(job)
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(BackgroundJob)
            .filter(
                BackgroundJob.user_id == user_id,
                BackgroundJob.task_type == task_type,
                BackgroundJob.idempotency_key_hash == key_hash,
            )
            .first()
        )
        if existing is None:
            raise
        return existing, False

    if quota_usage_type is not None:
        try:
            reservation = reserve_usage(
                db,
                user_id,
                quota_usage_type,
                f"background-job:{key_hash}",
                related_resource_type="background_job",
                related_resource_id=job.id,
            )
            job.quota_event_id = reservation.event_id
            db.commit()
            db.refresh(job)
        except UsageReservationConflict:
            db.refresh(job)
        except UsageServiceError as exc:
            transition_job(
                db,
                job,
                "failed",
                phase="quota",
                message_code="job_quota_rejected",
                error_code="quota_rejected",
                error_summary="任务额度预留失败",
            )
            raise exc
    return job, True


def list_owned_jobs(
    db: Session,
    user_id: int,
    *,
    page: int,
    page_size: int,
) -> tuple[list[BackgroundJob], int]:
    query = db.query(BackgroundJob).filter(BackgroundJob.user_id == user_id)
    total = query.count()
    jobs = (
        query.order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return jobs, total


def _release_job_quota(db: Session, job: BackgroundJob, error_type: str) -> None:
    if job.quota_event_id is None or job.quota_usage_type is None:
        return
    release_usage(
        db,
        UsageReservation(job.quota_event_id, job.quota_usage_type),
        error_type,
    )


def cancel_background_job(db: Session, user_id: int, job_id: str) -> BackgroundJob:
    job = get_owned_job(db, user_id, job_id)
    if job.status in TERMINAL_STATUSES:
        return job
    if job.status in CLAIMABLE_STATUSES:
        transition_job(
            db,
            job,
            "cancelled",
            phase="cancelled",
            message_code="job_cancelled",
        )
        _release_job_quota(db, job, "job_cancelled")
        db.refresh(job)
        return job
    if job.status == "running":
        job.cancel_requested_at = utc_text()
        return transition_job(
            db,
            job,
            "cancel_requested",
            phase=job.phase,
            message_code="job_cancel_requested",
        )
    return job


def claim_next_job(db: Session, worker_id: str) -> BackgroundJob | None:
    now = utc_text()
    query = db.query(BackgroundJob).filter(
        BackgroundJob.status.in_(CLAIMABLE_STATUSES),
        BackgroundJob.available_at <= now,
        or_(
            BackgroundJob.quota_usage_type.is_(None),
            BackgroundJob.quota_event_id.is_not(None),
        ),
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    job = query.order_by(BackgroundJob.created_at.asc(), BackgroundJob.id.asc()).first()
    if job is None:
        return None
    if job.attempt_count >= job.max_attempts:
        transition_job(
            db,
            job,
            "failed",
            phase="failed",
            message_code="job_attempts_exhausted",
            error_code="attempts_exhausted",
            error_summary="任务已达到最大尝试次数",
        )
        _release_job_quota(db, job, "attempts_exhausted")
        return None
    current = job.status
    now_value = utc_now()
    job.status = "running"
    job.phase = "preparing"
    job.message_code = "job_started"
    job.started_at = job.started_at or utc_text(now_value)
    job.heartbeat_at = utc_text(now_value)
    job.lease_expires_at = utc_text(
        now_value + timedelta(seconds=settings.job_lease_seconds)
    )
    job.worker_id = worker_id
    job.attempt_count += 1
    db.add(_event(job, current, "running"))
    db.commit()
    db.refresh(job)
    return job


def update_job_progress(
    db: Session,
    job_id: str,
    worker_id: str,
    *,
    progress_percent: int,
    phase: str,
    message_code: str,
) -> BackgroundJob:
    job = db.get(BackgroundJob, job_id)
    if job is None or job.worker_id != worker_id or job.status not in {
        "running",
        "cancel_requested",
    }:
        raise BackgroundJobError(409, "任务 lease 已失效")
    now = utc_now()
    job.progress_percent = min(99, max(job.progress_percent, progress_percent))
    job.phase = phase[:64]
    job.message_code = message_code[:100]
    job.heartbeat_at = utc_text(now)
    job.lease_expires_at = utc_text(now + timedelta(seconds=settings.job_lease_seconds))
    db.commit()
    db.refresh(job)
    return job


def should_cancel(db: Session, job_id: str, worker_id: str) -> bool:
    db.expire_all()
    job = db.get(BackgroundJob, job_id)
    return bool(
        job is None
        or job.worker_id != worker_id
        or job.status == "cancel_requested"
    )


def complete_job(
    db: Session,
    job: BackgroundJob,
    worker_id: str,
    result: dict | None,
) -> BackgroundJob:
    db.refresh(job)
    if job.worker_id != worker_id:
        raise BackgroundJobError(409, "任务 lease 已失效")
    if job.status == "cancel_requested":
        transition_job(
            db,
            job,
            "cancelled",
            phase="cancelled",
            message_code="job_cancelled",
        )
        _release_job_quota(db, job, "job_cancelled")
        db.refresh(job)
        return job
    artifact = _artifact_for_job(db, job)
    if artifact is None:
        now = utc_now()
        artifact = BackgroundJobArtifact(
            id=str(uuid4()),
            user_id=job.user_id,
            artifact_type=f"{job.task_type}_result",
            input_data=None,
            result_data=result or {},
            created_at=utc_text(now),
            updated_at=utc_text(now),
            expires_at=utc_text(now + timedelta(days=settings.job_history_days)),
        )
        db.add(artifact)
    else:
        artifact.result_data = result or {}
        artifact.updated_at = utc_text()
    job.result_reference = f"artifact:{artifact.id}"
    db.commit()
    if job.quota_event_id is not None and job.quota_usage_type is not None:
        commit_usage(
            db,
            UsageReservation(job.quota_event_id, job.quota_usage_type),
        )
    return transition_job(
        db,
        job,
        "succeeded",
        phase="completed",
        message_code="job_succeeded",
        progress_percent=100,
    )


def fail_job(
    db: Session,
    job: BackgroundJob,
    worker_id: str,
    *,
    error_code: str,
    timed_out: bool = False,
    retryable: bool = True,
) -> BackgroundJob:
    db.refresh(job)
    if job.worker_id != worker_id:
        return job
    if job.status == "cancel_requested":
        transition_job(
            db,
            job,
            "cancelled",
            phase="cancelled",
            message_code="job_cancelled",
        )
        _release_job_quota(db, job, "job_cancelled")
        db.refresh(job)
        return job
    if timed_out:
        transition_job(
            db,
            job,
            "timed_out",
            phase="timed_out",
            message_code="job_timed_out",
            error_code="job_timed_out",
            error_summary="任务执行超时",
        )
        _release_job_quota(db, job, "job_timed_out")
        db.refresh(job)
        return job
    if retryable and job.attempt_count < job.max_attempts:
        delay = min(60, 2 ** job.attempt_count)
        job.available_at = utc_text(utc_now() + timedelta(seconds=delay))
        job.worker_id = None
        job.lease_expires_at = None
        return transition_job(
            db,
            job,
            "retry_wait",
            phase="retry_wait",
            message_code="job_retry_scheduled",
            error_code=error_code,
            error_summary="任务将在受控退避后重试",
        )
    transition_job(
        db,
        job,
        "failed",
        phase="failed",
        message_code="job_failed",
        error_code=error_code,
        error_summary="任务执行失败",
    )
    _release_job_quota(db, job, error_code)
    db.refresh(job)
    return job


def recover_expired_jobs(db: Session, *, dry_run: bool = False) -> dict:
    now = utc_text()
    jobs = (
        db.query(BackgroundJob)
        .filter(
            BackgroundJob.status.in_({"running", "cancel_requested"}),
            BackgroundJob.lease_expires_at.is_not(None),
            BackgroundJob.lease_expires_at < now,
        )
        .order_by(BackgroundJob.id.asc())
        .all()
    )
    summary = {"expired": len(jobs), "retried": 0, "failed": 0, "cancelled": 0}
    if dry_run:
        return summary
    for job in jobs:
        if job.status == "cancel_requested":
            transition_job(
                db,
                job,
                "cancelled",
                phase="cancelled",
                message_code="job_cancelled_after_lease",
            )
            _release_job_quota(db, job, "job_cancelled")
            summary["cancelled"] += 1
        elif job.attempt_count < job.max_attempts:
            job.available_at = now
            job.worker_id = None
            job.lease_expires_at = None
            transition_job(
                db,
                job,
                "retry_wait",
                phase="retry_wait",
                message_code="job_lease_recovered",
            )
            summary["retried"] += 1
        else:
            transition_job(
                db,
                job,
                "failed",
                phase="failed",
                message_code="job_attempts_exhausted",
                error_code="attempts_exhausted",
                error_summary="任务 lease 失效且已达到最大尝试次数",
            )
            _release_job_quota(db, job, "attempts_exhausted")
            summary["failed"] += 1
    return summary


def cleanup_job_history(db: Session, *, dry_run: bool = False) -> dict:
    cutoff = utc_text(utc_now() - timedelta(days=settings.job_history_days))
    terminal_query = db.query(BackgroundJob).filter(
        BackgroundJob.status.in_(TERMINAL_STATUSES),
        BackgroundJob.completed_at < cutoff,
    )
    artifact_query = db.query(BackgroundJobArtifact).filter(
        BackgroundJobArtifact.expires_at < utc_text()
    )
    summary = {
        "jobs": terminal_query.count(),
        "artifacts": artifact_query.count(),
    }
    if dry_run:
        return summary
    terminal_query.delete(synchronize_session=False)
    artifact_query.delete(synchronize_session=False)
    db.commit()
    return summary


def release_orphaned_job_reservations(
    db: Session,
    *,
    dry_run: bool = False,
) -> dict:
    terminal_events = (
        db.query(UsageEvent)
        .join(BackgroundJob, BackgroundJob.quota_event_id == UsageEvent.id)
        .filter(
            BackgroundJob.status.in_(TERMINAL_STATUSES),
            UsageEvent.status == "reserved",
        )
        .all()
    )
    missing_job_events = (
        db.query(UsageEvent)
        .outerjoin(
            BackgroundJob,
            BackgroundJob.id == UsageEvent.related_resource_id,
        )
        .filter(
            UsageEvent.related_resource_type == "background_job",
            UsageEvent.status == "reserved",
            BackgroundJob.id.is_(None),
        )
        .all()
    )
    events = {event.id: event for event in [*terminal_events, *missing_job_events]}
    summary = {"released": len(events)}
    if dry_run:
        return summary
    for event in events.values():
        release_usage(
            db,
            UsageReservation(event.id, event.usage_type),
            "orphaned_background_job",
        )
    return summary
