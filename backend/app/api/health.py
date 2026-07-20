from fastapi import APIRouter

from app.core.config import settings
from app.core.readiness import is_auth_ready
from app.db.database import engine
from app.db.schema_version import get_schema_status

router = APIRouter()


@router.get("/health")
def health_check():
    auth_ready = is_auth_ready(settings)
    try:
        schema_ready = get_schema_status(engine).ready
    except Exception:
        schema_ready = False
    ready = auth_ready and schema_ready
    return {
        "status": "ok" if ready else "degraded",
        "auth_ready": auth_ready,
        "schema_ready": schema_ready,
    }
