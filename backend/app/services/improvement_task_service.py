from sqlalchemy.orm import Session

from app.db.models import ImprovementTask, InterviewTurn
from app.services.interview_session_service import (
    InterviewTrainingServiceError,
    get_owned_session,
    now_iso,
)

ALLOWED_CATEGORIES = {
    "technical",
    "project_evidence",
    "answer_depth",
    "expression",
    "job_match",
    "resume",
}
ALLOWED_PRIORITIES = {"low", "medium", "high"}


def get_owned_improvement_task(
    db: Session,
    user_id: int,
    task_id: int,
) -> ImprovementTask:
    task = (
        db.query(ImprovementTask)
        .filter(
            ImprovementTask.id == task_id,
            ImprovementTask.user_id == user_id,
        )
        .first()
    )
    if task is None:
        raise InterviewTrainingServiceError(404, "改进任务不存在")
    return task


def create_improvement_task(
    db: Session,
    user_id: int,
    session_id: int,
    *,
    title: str,
    description: str,
    category: str,
    priority: str,
    turn_id: int | None = None,
    completion_criteria: str = "",
) -> ImprovementTask:
    get_owned_session(db, user_id, session_id)
    if category not in ALLOWED_CATEGORIES:
        raise InterviewTrainingServiceError(400, "改进任务分类无效")
    if priority not in ALLOWED_PRIORITIES:
        raise InterviewTrainingServiceError(400, "改进任务优先级无效")
    if not title.strip() or not description.strip():
        raise InterviewTrainingServiceError(400, "改进任务标题和描述不能为空")

    if turn_id is not None:
        turn = (
            db.query(InterviewTurn)
            .filter(
                InterviewTurn.id == turn_id,
                InterviewTurn.user_id == user_id,
            )
            .first()
        )
        if turn is None or turn.session_id != session_id:
            raise InterviewTrainingServiceError(400, "题目必须属于同一面试会话")

    now = now_iso()
    task = ImprovementTask(
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
        title=title.strip(),
        description=description.strip(),
        completion_criteria=completion_criteria.strip(),
        category=category,
        priority=priority,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def list_improvement_tasks(
    db: Session,
    user_id: int,
    *,
    status: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    session_id: int | None = None,
) -> list[ImprovementTask]:
    query = db.query(ImprovementTask).filter(ImprovementTask.user_id == user_id)
    if status is not None:
        query = query.filter(ImprovementTask.status == status)
    if category is not None:
        query = query.filter(ImprovementTask.category == category)
    if priority is not None:
        query = query.filter(ImprovementTask.priority == priority)
    if session_id is not None:
        query = query.filter(ImprovementTask.session_id == session_id)
    return query.order_by(ImprovementTask.id.desc()).all()


def update_improvement_task_status(
    db: Session,
    user_id: int,
    task_id: int,
    new_status: str,
) -> ImprovementTask:
    if new_status not in {"pending", "completed"}:
        raise InterviewTrainingServiceError(400, "改进任务状态无效")
    task = get_owned_improvement_task(db, user_id, task_id)
    now = now_iso()
    task.status = new_status
    task.completed_at = now if new_status == "completed" else None
    task.updated_at = now
    db.commit()
    db.refresh(task)
    return task
