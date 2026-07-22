from __future__ import annotations

import argparse
import logging
import signal
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from time import monotonic
from uuid import uuid4

from sqlalchemy import text

from app.core.config import settings
from app.db.database import DATABASE_DIALECT, SessionLocal
from app.db.models import BackgroundJob, MaintenanceState, WorkerHeartbeat
from app.services.background_job_executor import (
    BackgroundJobCancelled,
    execute_background_job,
)
from app.services.background_job_service import (
    BackgroundJobError,
    cleanup_job_history,
    claim_next_job,
    complete_job,
    fail_job,
    recover_expired_jobs,
    release_orphaned_job_reservations,
    renew_job_lease,
    utc_now,
    utc_text,
)
from app.services.data_retention_service import cleanup_expired_data, preview_expired_data
from app.services.interview_flow_service import InterviewFlowError
from app.services.usage_service import UsageLimitExceeded, get_local_now

logger = logging.getLogger("spi.worker")


class WorkerStartupError(RuntimeError):
    pass


PERMANENT_INTERVIEW_FLOW_STATUS_CODES = {400, 403, 404, 409, 410, 422}
PERMANENT_BACKGROUND_JOB_DETAILS = {"任务输入引用无效", "不支持的任务类型"}


def _is_retryable_job_error(error: Exception) -> bool:
    if isinstance(error, UsageLimitExceeded):
        return False
    if isinstance(error, InterviewFlowError):
        return error.status_code not in PERMANENT_INTERVIEW_FLOW_STATUS_CODES
    if isinstance(error, BackgroundJobError):
        return not (
            isinstance(error.detail, str)
            and error.detail in PERMANENT_BACKGROUND_JOB_DETAILS
        )
    return True


def _safe_job_error_summary(error: Exception) -> str | None:
    if isinstance(error, UsageLimitExceeded):
        detail = error.detail
        if isinstance(detail, dict):
            message = detail.get("message")
            return str(message) if message else "今日面试评价额度已用尽"
        return "今日面试评价额度已用尽"
    if isinstance(error, InterviewFlowError):
        return error.detail
    if isinstance(error, BackgroundJobError) and isinstance(error.detail, str):
        return error.detail
    return None


class JobLeaseHeartbeat:
    def __init__(self, job_id: str, worker_id: str):
        self.job_id = job_id
        self.worker_id = worker_id
        self._stop_event = threading.Event()
        self._lost_ownership = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"job-lease-{job_id[:8]}",
            daemon=True,
        )

    @property
    def lost_ownership(self) -> bool:
        return self._lost_ownership.is_set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(
                timeout=max(1.0, self._interval_seconds() * 2),
            )

    def _interval_seconds(self) -> float:
        return max(
            0.1,
            min(
                float(settings.job_heartbeat_seconds),
                float(settings.job_lease_seconds) / 3,
            ),
        )

    def _run(self) -> None:
        interval = self._interval_seconds()
        while not self._stop_event.wait(interval):
            db = SessionLocal()
            try:
                renewed = renew_job_lease(db, self.job_id, self.worker_id)
            except Exception:
                db.rollback()
                logger.exception(
                    "任务 lease 续租失败 task_id=%s worker_id=%s",
                    self.job_id,
                    self.worker_id,
                )
                continue
            finally:
                db.close()
            if not renewed:
                self._lost_ownership.set()
                self._stop_event.set()
                return


def register_worker(worker_id: str) -> None:
    db = SessionLocal()
    try:
        now = utc_now()
        if DATABASE_DIALECT == "sqlite":
            active_after = utc_text(
                now - timedelta(seconds=settings.job_lease_seconds * 2)
            )
            active = (
                db.query(WorkerHeartbeat)
                .filter(
                    WorkerHeartbeat.stopped_at.is_(None),
                    WorkerHeartbeat.heartbeat_at >= active_after,
                    WorkerHeartbeat.worker_id != worker_id,
                )
                .first()
            )
            if active is not None:
                raise WorkerStartupError("SQLite 仅允许一个活跃 Worker")
        heartbeat = WorkerHeartbeat(
            worker_id=worker_id,
            database_dialect=DATABASE_DIALECT,
            started_at=utc_text(now),
            heartbeat_at=utc_text(now),
            stopped_at=None,
        )
        db.merge(heartbeat)
        db.commit()
    finally:
        db.close()


def update_worker_heartbeat(worker_id: str, *, stopped: bool = False) -> None:
    db = SessionLocal()
    try:
        heartbeat = db.get(WorkerHeartbeat, worker_id)
        if heartbeat is None:
            return
        heartbeat.heartbeat_at = utc_text()
        if stopped:
            heartbeat.stopped_at = utc_text()
        db.commit()
    finally:
        db.close()


def run_job(job_id: str, worker_id: str) -> None:
    db = SessionLocal()
    started = monotonic()
    try:
        job = db.get(BackgroundJob, job_id)
        if job is None or job.worker_id != worker_id or job.status != "running":
            return
        lease_heartbeat = JobLeaseHeartbeat(job_id, worker_id)
        try:
            lease_heartbeat.start()
            try:
                result = execute_background_job(db, job, worker_id)
            finally:
                lease_heartbeat.stop()
            elapsed = monotonic() - started
            if elapsed > job.timeout_seconds:
                fail_job(
                    db,
                    job,
                    worker_id,
                    error_code="job_timed_out",
                    timed_out=True,
                    retryable=False,
                )
                return
            complete_job(db, job, worker_id, result)
        except BackgroundJobCancelled:
            fail_job(
                db,
                job,
                worker_id,
                error_code="job_cancelled",
                retryable=False,
            )
        except Exception as exc:
            db.rollback()
            job = db.get(BackgroundJob, job_id)
            if job is not None:
                retryable = _is_retryable_job_error(exc)
                fail_job(
                    db,
                    job,
                    worker_id,
                    error_code=type(exc).__name__,
                    error_summary=(
                        None if retryable else _safe_job_error_summary(exc)
                    ),
                    retryable=retryable,
                )
            logger.exception(
                "任务执行失败 task_id=%s task_type=%s phase=%s progress=%s "
                "error_code=%s",
                job_id,
                job.task_type if job is not None else "unknown",
                job.phase if job is not None else "unknown",
                job.progress_percent if job is not None else "unknown",
                type(exc).__name__,
            )
    finally:
        db.close()


def run_maintenance(*, dry_run: bool = False) -> dict:
    db = SessionLocal()
    postgres_lock = False
    try:
        if DATABASE_DIALECT == "postgresql":
            postgres_lock = bool(
                db.execute(text("SELECT pg_try_advisory_lock(73120260720)")).scalar()
            )
            if not postgres_lock:
                return {"skipped": "maintenance_lock_busy"}
        summary = {
            "lease_recovery": recover_expired_jobs(db, dry_run=dry_run),
            "history_cleanup": cleanup_job_history(db, dry_run=dry_run),
            "orphaned_quota": release_orphaned_job_reservations(
                db,
                dry_run=dry_run,
            ),
        }
        state = db.get(MaintenanceState, "data_retention")
        today = get_local_now().date()
        due = state is None or state.last_run_at is None
        if state is not None and state.last_run_at:
            due = get_local_now(datetime.fromisoformat(state.last_run_at)).date() < today
        if dry_run:
            summary["data_retention"] = preview_expired_data(db)
        elif due:
            summary["data_retention"] = cleanup_expired_data(db)
            now = utc_text()
            if state is None:
                state = MaintenanceState(key="data_retention")
                db.add(state)
            state.last_run_at = now
            state.updated_at = now
            db.commit()
        else:
            summary["data_retention"] = {"skipped": "already_ran_today"}
        return summary
    finally:
        if postgres_lock:
            db.execute(text("SELECT pg_advisory_unlock(73120260720)"))
        db.close()


def worker_loop(*, once: bool = False) -> None:
    concurrency = settings.worker_concurrency
    if DATABASE_DIALECT == "sqlite" and concurrency != 1:
        raise WorkerStartupError("SQLite 的 WORKER_CONCURRENCY 必须为 1")

    worker_id = f"worker-{uuid4().hex[:12]}"
    register_worker(worker_id)
    stop_event = threading.Event()

    def request_stop(signum, frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    logger.info("Worker 已启动 worker_id=%s dialect=%s", worker_id, DATABASE_DIALECT)

    futures: set[Future] = set()
    last_heartbeat = 0.0
    last_maintenance = 0.0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        try:
            while not stop_event.is_set():
                now_monotonic = monotonic()
                if now_monotonic - last_heartbeat >= settings.job_heartbeat_seconds:
                    update_worker_heartbeat(worker_id)
                    last_heartbeat = now_monotonic
                if now_monotonic - last_maintenance >= 60:
                    try:
                        summary = run_maintenance()
                        logger.info("Worker 维护完成 summary=%s", summary)
                    except Exception:
                        logger.exception("Worker 维护失败")
                    last_maintenance = now_monotonic

                futures = {item for item in futures if not item.done()}
                claimed = False
                while len(futures) < concurrency and not stop_event.is_set():
                    db = SessionLocal()
                    try:
                        job = claim_next_job(db, worker_id)
                    finally:
                        db.close()
                    if job is None:
                        break
                    futures.add(executor.submit(run_job, job.id, worker_id))
                    claimed = True
                if once and not futures and not claimed:
                    break
                stop_event.wait(settings.job_poll_interval_seconds)
        finally:
            stop_event.set()
            for future in futures:
                future.result()
            update_worker_heartbeat(worker_id, stopped=True)
            logger.info("Worker 已停止 worker_id=%s", worker_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="数据库驱动的后台任务 Worker")
    parser.add_argument("--once", action="store_true", help="处理完当前队列后退出")
    parser.add_argument("--maintenance", action="store_true", help="仅运行维护")
    parser.add_argument("--dry-run", action="store_true", help="维护仅预览")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = parse_args()
    if args.maintenance:
        print(run_maintenance(dry_run=args.dry_run))
        return
    worker_loop(once=args.once)


if __name__ == "__main__":
    main()
