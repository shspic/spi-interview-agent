from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Response, status
from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.readiness import is_auth_ready
from app.db.database import BACKEND_DIR, DATABASE_DIALECT, SessionLocal, engine
from app.db.models import WorkerHeartbeat
from app.db.schema_version import get_schema_status
from app.services.background_job_service import utc_now, utc_text

router = APIRouter()


def _resolve_directory(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else BACKEND_DIR / path


@router.get("/health/live")
def liveness_check():
    return {"status": "alive"}


@router.get("/health/ready")
def readiness_check(response: Response):
    auth_ready = is_auth_ready(settings)
    database_ready = False
    schema_ready = False
    task_system_ready = False
    worker_ready = False
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ready = True
        schema_ready = get_schema_status(engine).ready
        task_system_ready = "background_jobs" in inspect(engine).get_table_names()
        if task_system_ready:
            db = SessionLocal()
            try:
                active_after = utc_text(
                    utc_now() - timedelta(seconds=settings.job_lease_seconds * 2)
                )
                worker_ready = (
                    db.query(WorkerHeartbeat)
                    .filter(
                        WorkerHeartbeat.stopped_at.is_(None),
                        WorkerHeartbeat.heartbeat_at >= active_after,
                    )
                    .first()
                    is not None
                )
            finally:
                db.close()
    except Exception:
        pass
    storage_ready = all(
        path.exists() and path.is_dir()
        for path in (
            _resolve_directory(settings.upload_dir),
            _resolve_directory(settings.chroma_persist_dir),
        )
    )
    ready = (
        auth_ready
        and database_ready
        and schema_ready
        and storage_ready
        and task_system_ready
    )
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "auth_ready": auth_ready,
        "database_ready": database_ready,
        "database_type": DATABASE_DIALECT,
        "schema_ready": schema_ready,
        "storage_ready": storage_ready,
        "task_system_ready": task_system_ready,
        "worker_ready": worker_ready,
    }


@router.get("/health")
def health_check(response: Response):
    return liveness_check()
