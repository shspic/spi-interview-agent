from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.config import settings
from app.core.input_validation import validate_safe_text
from app.db.database import get_db
from app.db.models import User
from app.services.job_service import JobServiceError, analyze_job
from app.services.usage_service import (
    UsageServiceError,
    commit_usage,
    release_usage,
    reserve_usage,
)

router = APIRouter()


class JobAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_description: str
    use_web_search: bool = False

    @field_validator("job_description")
    @classmethod
    def validate_job_description(cls, value: str) -> str:
        return validate_safe_text(
            value,
            field_name="岗位描述",
            max_chars=settings.max_job_description_chars,
            strip=True,
        )


@router.post(
    "/jobs/analyze",
    summary="岗位 JD 分析",
    description="结合岗位 JD、本地知识库和可选联网搜索，分析用户匹配点、短板、简历优化建议和可能面试问题。",
)
def analyze_job_api(
    request: JobAnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        reservation = reserve_usage(
            db,
            current_user.id,
            "job_analysis",
            f"job-analysis:{uuid4()}",
            related_resource_type="job_analysis_request",
        )
    except UsageServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    try:
        result = analyze_job(
            job_description=request.job_description,
            user_id=current_user.id,
            db=db,
            use_web_search=request.use_web_search,
        )
    except JobServiceError as exc:
        release_usage(db, reservation, type(exc).__name__)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        release_usage(db, reservation, type(exc).__name__)
        raise
    commit_usage(db, reservation)
    return result
