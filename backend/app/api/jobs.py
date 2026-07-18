from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import User
from app.services.job_service import JobServiceError, analyze_job

router = APIRouter()


class JobAnalyzeRequest(BaseModel):
    job_description: str
    use_web_search: bool = False


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
        return analyze_job(
            job_description=request.job_description,
            user_id=current_user.id,
            db=db,
            use_web_search=request.use_web_search,
        )
    except JobServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
