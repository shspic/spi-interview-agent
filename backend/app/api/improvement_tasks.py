from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.interview_sessions import task_to_response
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import User
from app.schemas.interview_training import (
    ImprovementCategory,
    ImprovementPriority,
    ImprovementStatus,
    ImprovementTaskListResponse,
    ImprovementTaskResponse,
    ImprovementTaskUpdate,
)
from app.services.improvement_task_service import (
    list_improvement_tasks,
    update_improvement_task_status,
)
from app.services.interview_session_service import InterviewTrainingServiceError

router = APIRouter()


@router.get("/improvement-tasks", response_model=ImprovementTaskListResponse)
def get_improvement_tasks(
    task_status: ImprovementStatus | None = Query(default=None, alias="status"),
    category: ImprovementCategory | None = None,
    priority: ImprovementPriority | None = None,
    session_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tasks = list_improvement_tasks(
        db,
        current_user.id,
        status=task_status,
        category=category,
        priority=priority,
        session_id=session_id,
    )
    return {"tasks": [task_to_response(task) for task in tasks]}


@router.patch(
    "/improvement-tasks/{task_id}",
    response_model=ImprovementTaskResponse,
)
def patch_improvement_task(
    task_id: int,
    request: ImprovementTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        task = update_improvement_task_status(
            db,
            current_user.id,
            task_id,
            request.status,
        )
    except InterviewTrainingServiceError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return task_to_response(task)
