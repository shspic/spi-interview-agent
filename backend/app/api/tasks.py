from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.input_validation import validate_safe_text
from app.core.security import get_current_admin, get_current_user
from app.db.database import get_db
from app.db.models import User
from app.services.background_job_service import (
    BackgroundJobError,
    cancel_background_job,
    create_background_job,
    get_owned_job,
    list_owned_jobs,
    serialize_job,
)
from app.services.usage_service import UsageServiceError

router = APIRouter()


class AgentJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    mode: Literal["auto", "local", "web", "hybrid"] = "auto"
    top_k: int = Field(default=5, ge=1, le=10)
    max_web_results: int = Field(default=5, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        return validate_safe_text(
            value,
            field_name="任务描述",
            max_chars=settings.max_task_input_chars,
            strip=True,
        )


class JobAnalysisJobRequest(BaseModel):
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


class SessionJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: int = Field(gt=0)


class ResumeJobRequest(SessionJobRequest):
    target_job_id: int | None = Field(default=None, gt=0)
    project_file_ids: list[str] = Field(default_factory=list, max_length=20)


class InterviewEvaluationJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: int = Field(gt=0)
    turn_id: int = Field(gt=0)
    answer: str

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, value: str) -> str:
        return validate_safe_text(
            value,
            field_name="面试回答",
            max_chars=settings.max_interview_answer_chars,
            strip=True,
        )


def _raise_job_error(error: Exception) -> None:
    if isinstance(error, (BackgroundJobError, UsageServiceError)):
        raise HTTPException(error.status_code, detail=error.detail) from error
    raise error


def _accepted(response: Response, db: Session, job, created: bool) -> dict:
    response.status_code = status.HTTP_202_ACCEPTED
    response.headers["Cache-Control"] = "no-store"
    return {**serialize_job(db, job), "created": created}


@router.post("/tasks/knowledge-rebuild", status_code=status.HTTP_202_ACCEPTED)
def create_knowledge_rebuild_job(
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        job, created = create_background_job(
            db,
            user_id=current_user.id,
            task_type="knowledge_rebuild",
            idempotency_key=idempotency_key or "",
        )
    except (BackgroundJobError, UsageServiceError) as error:
        _raise_job_error(error)
    return _accepted(response, db, job, created)


@router.post("/tasks/agent-ask", status_code=status.HTTP_202_ACCEPTED)
def create_agent_job(
    request: AgentJobRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        job, created = create_background_job(
            db,
            user_id=current_user.id,
            task_type="agent_ask",
            idempotency_key=idempotency_key or "",
            input_data=request.model_dump(),
            quota_usage_type="multi_agent_task",
        )
    except (BackgroundJobError, UsageServiceError) as error:
        _raise_job_error(error)
    return _accepted(response, db, job, created)


@router.post("/tasks/job-analysis", status_code=status.HTTP_202_ACCEPTED)
def create_job_analysis_job(
    request: JobAnalysisJobRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        job, created = create_background_job(
            db,
            user_id=current_user.id,
            task_type="job_analysis",
            idempotency_key=idempotency_key or "",
            input_data=request.model_dump(),
            quota_usage_type="job_analysis",
        )
    except (BackgroundJobError, UsageServiceError) as error:
        _raise_job_error(error)
    return _accepted(response, db, job, created)


@router.post("/tasks/interview-start", status_code=status.HTTP_202_ACCEPTED)
def create_interview_start_job(
    request: SessionJobRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        job, created = create_background_job(
            db,
            user_id=current_user.id,
            task_type="interview_start",
            idempotency_key=idempotency_key or "",
            input_data=request.model_dump(),
            quota_usage_type="multi_agent_task",
        )
    except (BackgroundJobError, UsageServiceError) as error:
        _raise_job_error(error)
    return _accepted(response, db, job, created)


@router.post("/tasks/interview-evaluation", status_code=status.HTTP_202_ACCEPTED)
def create_interview_evaluation_job(
    request: InterviewEvaluationJobRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        job, created = create_background_job(
            db,
            user_id=current_user.id,
            task_type="interview_evaluation",
            idempotency_key=idempotency_key or "",
            input_data=request.model_dump(),
        )
    except (BackgroundJobError, UsageServiceError) as error:
        _raise_job_error(error)
    return _accepted(response, db, job, created)


@router.post("/tasks/improvements", status_code=status.HTTP_202_ACCEPTED)
def create_improvement_job(
    request: SessionJobRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        job, created = create_background_job(
            db,
            user_id=current_user.id,
            task_type="improvement_generation",
            idempotency_key=idempotency_key or "",
            input_data=request.model_dump(),
        )
    except BackgroundJobError as error:
        _raise_job_error(error)
    return _accepted(response, db, job, created)


@router.post("/tasks/resume", status_code=status.HTTP_202_ACCEPTED)
def create_resume_job(
    request: ResumeJobRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        job, created = create_background_job(
            db,
            user_id=current_user.id,
            task_type="resume_generation",
            idempotency_key=idempotency_key or "",
            input_data=request.model_dump(),
        )
    except BackgroundJobError as error:
        _raise_job_error(error)
    return _accepted(response, db, job, created)


@router.post("/tasks/retention-cleanup", status_code=status.HTTP_202_ACCEPTED)
def create_retention_job(
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    try:
        job, created = create_background_job(
            db,
            user_id=current_admin.id,
            task_type="data_retention_cleanup",
            idempotency_key=idempotency_key or "",
        )
    except BackgroundJobError as error:
        _raise_job_error(error)
    return _accepted(response, db, job, created)


@router.get("/tasks")
def get_tasks(
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    jobs, total = list_owned_jobs(
        db,
        current_user.id,
        page=page,
        page_size=page_size,
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "items": [serialize_job(db, job, include_result=False) for job in jobs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/tasks/{task_id}")
def get_task(
    task_id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return serialize_job(db, get_owned_job(db, current_user.id, task_id))
    except BackgroundJobError as error:
        _raise_job_error(error)


@router.post("/tasks/{task_id}/cancel")
def cancel_task(
    task_id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return serialize_job(
            db,
            cancel_background_job(db, current_user.id, task_id),
        )
    except BackgroundJobError as error:
        _raise_job_error(error)
