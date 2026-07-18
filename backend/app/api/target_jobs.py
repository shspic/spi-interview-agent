from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import TargetJob, User

router = APIRouter()


class TargetJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_title: str = Field(min_length=1, max_length=200)
    company_name: str = Field(default="", max_length=200)
    jd_text: str = Field(min_length=1, max_length=50000)
    notes: str = Field(default="", max_length=5000)
    is_active: bool = False

    @field_validator("job_title", "jd_text")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("岗位名称和 JD 文本不能为空")

        return normalized


class TargetJobUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_title: str = Field(min_length=1, max_length=200)
    company_name: str = Field(default="", max_length=200)
    jd_text: str = Field(min_length=1, max_length=50000)
    notes: str = Field(default="", max_length=5000)

    @field_validator("job_title", "jd_text")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("岗位名称和 JD 文本不能为空")

        return normalized


class TargetJobResponse(BaseModel):
    id: int
    job_title: str
    company_name: str
    jd_text: str
    notes: str
    is_active: bool
    created_at: str
    updated_at: str


class TargetJobListResponse(BaseModel):
    jobs: list[TargetJobResponse]


def job_to_response(job: TargetJob) -> TargetJobResponse:
    return TargetJobResponse(
        id=job.id,
        job_title=job.job_title,
        company_name=job.company_name,
        jd_text=job.jd_text,
        notes=job.notes,
        is_active=bool(job.is_active),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def get_owned_job(db: Session, user_id: int, job_id: int) -> TargetJob:
    job = (
        db.query(TargetJob)
        .filter(
            TargetJob.id == job_id,
            TargetJob.user_id == user_id,
        )
        .first()
    )

    if job is None:
        raise HTTPException(status_code=404, detail="目标岗位不存在")

    return job


def deactivate_current_job(db: Session, user_id: int) -> None:
    db.query(TargetJob).filter(
        TargetJob.user_id == user_id,
        TargetJob.is_active.is_(True),
    ).update({TargetJob.is_active: False}, synchronize_session="fetch")


@router.get("/target-jobs", response_model=TargetJobListResponse)
def list_target_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    jobs = (
        db.query(TargetJob)
        .filter(TargetJob.user_id == current_user.id)
        .order_by(TargetJob.is_active.desc(), TargetJob.id.desc())
        .all()
    )

    return {"jobs": [job_to_response(job) for job in jobs]}


@router.post(
    "/target-jobs",
    response_model=TargetJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_target_job(
    request: TargetJobCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now().isoformat(timespec="seconds")

    if request.is_active:
        deactivate_current_job(db, current_user.id)

    job = TargetJob(
        user_id=current_user.id,
        job_title=request.job_title.strip(),
        company_name=request.company_name.strip(),
        jd_text=request.jd_text.strip(),
        notes=request.notes.strip(),
        is_active=request.is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return job_to_response(job)


@router.get("/target-jobs/{job_id}", response_model=TargetJobResponse)
def get_target_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return job_to_response(get_owned_job(db, current_user.id, job_id))


@router.put("/target-jobs/{job_id}", response_model=TargetJobResponse)
def update_target_job(
    job_id: int,
    request: TargetJobUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = get_owned_job(db, current_user.id, job_id)
    job.job_title = request.job_title.strip()
    job.company_name = request.company_name.strip()
    job.jd_text = request.jd_text.strip()
    job.notes = request.notes.strip()
    job.updated_at = datetime.now().isoformat(timespec="seconds")
    db.commit()
    db.refresh(job)

    return job_to_response(job)


@router.delete("/target-jobs/{job_id}")
def delete_target_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = get_owned_job(db, current_user.id, job_id)
    db.delete(job)
    db.commit()

    return {"success": True, "message": "目标岗位已删除"}


@router.post("/target-jobs/{job_id}/activate", response_model=TargetJobResponse)
def activate_target_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = get_owned_job(db, current_user.id, job_id)
    deactivate_current_job(db, current_user.id)
    job.is_active = True
    job.updated_at = datetime.now().isoformat(timespec="seconds")
    db.commit()
    db.refresh(job)

    return job_to_response(job)
