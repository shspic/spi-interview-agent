from datetime import timedelta

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import WorkerHeartbeat
from app.services.background_job_service import utc_now, utc_text


def main() -> None:
    active_after = utc_text(
        utc_now() - timedelta(seconds=settings.job_lease_seconds * 2)
    )
    db = SessionLocal()
    try:
        active = (
            db.query(WorkerHeartbeat)
            .filter(
                WorkerHeartbeat.stopped_at.is_(None),
                WorkerHeartbeat.heartbeat_at >= active_after,
            )
            .first()
        )
        if active is None:
            raise SystemExit(1)
        print("worker_ready")
    finally:
        db.close()


if __name__ == "__main__":
    main()
