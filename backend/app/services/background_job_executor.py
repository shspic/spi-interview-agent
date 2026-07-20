from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import (
    BackgroundJob,
    BackgroundJobArtifact,
    InterviewSession,
    InterviewTurn,
)
from app.services.agent_service import ask_agent
from app.services.background_job_service import (
    BackgroundJobError,
    should_cancel,
    update_job_progress,
)
from app.services.data_retention_service import cleanup_expired_data
from app.services.improvement_generation_service import generate_improvements_for_session
from app.services.interview_flow_service import start_interview_flow
from app.services.interview_service import evaluate_interview_answer
from app.services.job_service import analyze_job
from app.services.resume_generation_service import generate_resume_project_description
from app.services.vector_store import rebuild_vector_store


class BackgroundJobCancelled(Exception):
    pass


def _artifact_input(db: Session, job: BackgroundJob) -> dict:
    if not job.input_reference or not job.input_reference.startswith("artifact:"):
        return {}
    artifact_id = job.input_reference.split(":", 1)[1]
    artifact = (
        db.query(BackgroundJobArtifact)
        .filter(
            BackgroundJobArtifact.id == artifact_id,
            BackgroundJobArtifact.user_id == job.user_id,
        )
        .first()
    )
    if artifact is None or not isinstance(artifact.input_data, dict):
        raise BackgroundJobError(409, "任务输入引用无效")
    return artifact.input_data


def _checkpoint(
    db: Session,
    job: BackgroundJob,
    worker_id: str,
    progress: int,
    phase: str,
    message_code: str,
) -> None:
    if should_cancel(db, job.id, worker_id):
        raise BackgroundJobCancelled()
    update_job_progress(
        db,
        job.id,
        worker_id,
        progress_percent=progress,
        phase=phase,
        message_code=message_code,
    )


def execute_background_job(
    db: Session,
    job: BackgroundJob,
    worker_id: str,
) -> dict:
    payload = _artifact_input(db, job)
    _checkpoint(db, job, worker_id, 5, "preparing", "job_preparing")

    if job.task_type == "knowledge_rebuild":
        _checkpoint(db, job, worker_id, 20, "parsing", "knowledge_parsing")
        result = rebuild_vector_store(db, job.user_id)
        _checkpoint(db, job, worker_id, 90, "indexing", "knowledge_indexed")
        return result

    if job.task_type == "agent_ask":
        _checkpoint(db, job, worker_id, 20, "retrieving", "agent_retrieving")
        result = ask_agent(
            question=str(payload["question"]),
            user_id=job.user_id,
            mode=str(payload.get("mode", "auto")),
            top_k=int(payload.get("top_k", 5)),
            max_web_results=int(payload.get("max_web_results", 5)),
            db=db,
            request_id=job.id,
        )
        _checkpoint(db, job, worker_id, 90, "saving", "agent_saved")
        return result

    if job.task_type == "job_analysis":
        _checkpoint(db, job, worker_id, 20, "retrieving", "job_analysis_retrieving")
        result = analyze_job(
            job_description=str(payload["job_description"]),
            user_id=job.user_id,
            db=db,
            use_web_search=bool(payload.get("use_web_search", False)),
            request_id=job.id,
        )
        _checkpoint(db, job, worker_id, 90, "saving", "job_analysis_saved")
        return result

    if job.task_type == "interview_start":
        session_id = int(payload["session_id"])
        existing_session = (
            db.query(InterviewSession)
            .filter(
                InterviewSession.id == session_id,
                InterviewSession.user_id == job.user_id,
            )
            .first()
        )
        existing_turn = (
            db.query(InterviewTurn)
            .filter(
                InterviewTurn.session_id == session_id,
                InterviewTurn.user_id == job.user_id,
            )
            .order_by(InterviewTurn.sequence_number.asc())
            .first()
        )
        if (
            existing_session is not None
            and existing_session.status in {"in_progress", "completed"}
            and existing_turn is not None
        ):
            return {
                "session_id": existing_session.id,
                "current_turn_id": existing_turn.id,
                "evidence_limited": False,
                "agent_execution_summary": existing_session.agent_execution_summary,
            }
        _checkpoint(db, job, worker_id, 20, "planning", "interview_planning")
        result = start_interview_flow(db, job.user_id, session_id)
        _checkpoint(db, job, worker_id, 90, "saving", "interview_saved")
        return {
            "session_id": result.interview_session.id,
            "current_turn_id": result.first_turn.id,
            "evidence_limited": result.evidence_limited,
            "agent_execution_summary": result.agent_execution_summary,
        }

    if job.task_type == "interview_evaluation":
        _checkpoint(db, job, worker_id, 20, "evaluating", "interview_evaluating")
        result = evaluate_interview_answer(
            interview_type=str(payload["interview_type"]),
            job_description=str(payload["job_description"]),
            question_index=int(payload["question_index"]),
            question=str(payload["question"]),
            user_answer=str(payload["user_answer"]),
            user_id=job.user_id,
            db=db,
            request_id=job.id,
        )
        _checkpoint(db, job, worker_id, 90, "saving", "interview_evaluation_saved")
        return result

    if job.task_type == "improvement_generation":
        _checkpoint(db, job, worker_id, 20, "evaluating", "improvement_evaluating")
        result = generate_improvements_for_session(
            db,
            job.user_id,
            int(payload["session_id"]),
        )
        _checkpoint(db, job, worker_id, 90, "saving", "improvement_saved")
        return {
            "session_id": result.interview_session.id,
            "generated": result.generated,
            "task_ids": [item.id for item in result.tasks],
        }

    if job.task_type == "resume_generation":
        _checkpoint(db, job, worker_id, 20, "retrieving", "resume_retrieving")
        result = generate_resume_project_description(
            db,
            job.user_id,
            session_id=payload.get("session_id"),
            target_job_id=payload.get("target_job_id"),
            project_file_ids=payload.get("project_file_ids") or [],
            source_job_id=job.id,
        )
        _checkpoint(db, job, worker_id, 90, "saving", "resume_saved")
        return {"description_id": result.id}

    if job.task_type == "data_retention_cleanup":
        _checkpoint(db, job, worker_id, 20, "cleaning_database", "cleanup_database")
        result = cleanup_expired_data(db)
        _checkpoint(db, job, worker_id, 90, "cleaning_vectors", "cleanup_finished")
        return result

    raise BackgroundJobError(422, "不支持的任务类型")
