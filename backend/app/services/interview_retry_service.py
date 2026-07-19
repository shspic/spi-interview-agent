from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import ImprovementTask, InterviewSession
from app.services.evaluation_service import SCORE_WEIGHTS
from app.services.interview_session_service import (
    InterviewTrainingServiceError,
    create_interview_session,
    get_owned_session,
)

COMPARISON_NOTE = "这是训练表现对比，不是严格的同题实验。"


@dataclass
class RetrySessionResult:
    interview_session: InterviewSession
    source_session_id: int
    previous_task_count: int
    completed_task_count: int
    pending_task_count: int
    task_completion_rate: float


def _task_stats(db: Session, user_id: int, session_id: int) -> tuple[int, int, float]:
    tasks = (
        db.query(ImprovementTask.status)
        .filter(
            ImprovementTask.user_id == user_id,
            ImprovementTask.session_id == session_id,
        )
        .all()
    )
    total = len(tasks)
    completed = sum(1 for task in tasks if task.status == "completed")
    rate = round(completed * 100 / total, 2) if total else 0.0
    return total, completed, rate


def create_retry_session(
    db: Session,
    user_id: int,
    session_id: int,
) -> RetrySessionResult:
    source = get_owned_session(db, user_id, session_id)
    if source.status != "completed":
        raise InterviewTrainingServiceError(409, "只有已完成会话可以再次练习")

    suffix = " - 再次练习"
    title = f"{source.title[: 200 - len(suffix)]}{suffix}"
    retry_session = create_interview_session(
        db,
        user_id,
        title=title,
        mode=source.mode,
        target_job_id=source.target_job_id,
        selected_project_file_ids=list(source.selected_project_file_ids or []),
        previous_session_id=source.id,
    )
    total, completed, rate = _task_stats(db, user_id, source.id)
    return RetrySessionResult(
        interview_session=retry_session,
        source_session_id=source.id,
        previous_task_count=total,
        completed_task_count=completed,
        pending_task_count=total - completed,
        task_completion_rate=rate,
    )


def compare_retry_session(
    db: Session,
    user_id: int,
    session_id: int,
) -> dict:
    current = get_owned_session(db, user_id, session_id)
    if current.previous_session_id is None:
        return _not_comparable(current.id, None, "当前会话不是再次练习会话")

    previous = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.id == current.previous_session_id,
            InterviewSession.user_id == user_id,
        )
        .first()
    )
    if previous is None:
        raise InterviewTrainingServiceError(404, "上一轮会话不存在")
    if current.status != "completed" or previous.status != "completed":
        raise InterviewTrainingServiceError(409, "两轮会话均完成后才能比较")

    total, completed, rate = _task_stats(db, user_id, previous.id)
    if current.overall_score is None or previous.overall_score is None:
        return _not_comparable(
            current.id,
            previous.id,
            "至少一轮会话缺少总分，无法比较",
            total,
            completed,
            rate,
        )
    current_dimensions = current.dimension_scores or {}
    previous_dimensions = previous.dimension_scores or {}
    missing_dimensions = [
        name
        for name in SCORE_WEIGHTS
        if name not in current_dimensions or name not in previous_dimensions
    ]
    if missing_dimensions:
        return _not_comparable(
            current.id,
            previous.id,
            "至少一轮会话缺少完整维度分，无法比较",
            total,
            completed,
            rate,
        )

    dimension_deltas = {
        name: round(
            float(current_dimensions[name]) - float(previous_dimensions[name]),
            2,
        )
        for name in SCORE_WEIGHTS
    }
    return {
        "comparable": True,
        "reason": None,
        "note": COMPARISON_NOTE,
        "previous_session_id": previous.id,
        "current_session_id": current.id,
        "previous_overall_score": previous.overall_score,
        "current_overall_score": current.overall_score,
        "overall_delta": round(current.overall_score - previous.overall_score, 2),
        "previous_dimension_scores": previous_dimensions,
        "current_dimension_scores": current_dimensions,
        "dimension_deltas": dimension_deltas,
        "improved_dimensions": [
            name for name, delta in dimension_deltas.items() if delta > 0
        ],
        "regressed_dimensions": [
            name for name, delta in dimension_deltas.items() if delta < 0
        ],
        "unchanged_dimensions": [
            name for name, delta in dimension_deltas.items() if delta == 0
        ],
        "previous_task_count": total,
        "completed_task_count": completed,
        "task_completion_rate": rate,
    }


def comparison_available(
    db: Session,
    user_id: int,
    interview_session: InterviewSession,
) -> bool:
    if interview_session.previous_session_id is None:
        return False
    try:
        return bool(
            compare_retry_session(db, user_id, interview_session.id)["comparable"]
        )
    except InterviewTrainingServiceError:
        return False


def _not_comparable(
    current_session_id: int,
    previous_session_id: int | None,
    reason: str,
    previous_task_count: int = 0,
    completed_task_count: int = 0,
    task_completion_rate: float = 0.0,
) -> dict:
    return {
        "comparable": False,
        "reason": reason,
        "note": COMPARISON_NOTE,
        "previous_session_id": previous_session_id,
        "current_session_id": current_session_id,
        "previous_overall_score": None,
        "current_overall_score": None,
        "overall_delta": None,
        "previous_dimension_scores": None,
        "current_dimension_scores": None,
        "dimension_deltas": None,
        "improved_dimensions": [],
        "regressed_dimensions": [],
        "unchanged_dimensions": [],
        "previous_task_count": previous_task_count,
        "completed_task_count": completed_task_count,
        "task_completion_rate": task_completion_rate,
    }
