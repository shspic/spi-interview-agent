from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.db.models import FileRecord, HistoryRecord, InterviewRecord
from app.services.vector_store import get_vector_store_status

router = APIRouter()


@router.get(
    "/system/status",
    summary="系统状态自检",
    description="检查后端配置、API Key、数据库记录、知识库索引等状态。",
)
def get_system_status(db: Session = Depends(get_db)):
    vector_status = get_vector_store_status(db)

    file_count = db.query(FileRecord).count()
    history_count = db.query(HistoryRecord).count()
    interview_count = db.query(InterviewRecord).count()

    return {
        "backend": {
            "status": "ok",
            "app_name": settings.app_name,
        },
        "keys": {
            "deepseek_configured": bool(settings.deepseek_api_key),
            "tavily_configured": bool(settings.tavily_api_key),
        },
        "database": {
            "file_count": file_count,
            "history_count": history_count,
            "interview_count": interview_count,
        },
        "knowledge_base": vector_status,
    }