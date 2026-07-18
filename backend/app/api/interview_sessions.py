from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import (
    FileRecord,
    ImprovementTask,
    InterviewSession,
    InterviewTurn,
    TargetJob,
    User,
)
from app.schemas.interview_training import (
    InterviewMode,
    InterviewSessionCreate,
    InterviewSessionDetail,
    InterviewSessionListResponse,
    InterviewSessionResponse,
    InterviewSessionUpdate,
    InterviewStatus,
    ImprovementTaskResponse,
    InterviewTurnResponse,
    PreviousSessionSummary,
    ProjectFileSummary,
    TargetJobSummary,
)
from app.services.interview_session_service import (
    InterviewTrainingServiceError,
    cancel_interview_session,
    create_interview_session,
    delete_interview_session,
    get_owned_session,
    list_interview_sessions,
    start_interview_session,
    update_interview_session,
)

router = APIRouter()


def raise_http_error(error: InterviewTrainingServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def task_to_response(task: ImprovementTask) -> ImprovementTaskResponse:
    return ImprovementTaskResponse(
        id=task.id,
        session_id=task.session_id,
        turn_id=task.turn_id,
        title=task.title,
        description=task.description,
        category=task.category,
        priority=task.priority,
        status=task.status,
        created_at=task.created_at,
        completed_at=task.completed_at,
        updated_at=task.updated_at,
    )


def turn_to_response(turn: InterviewTurn) -> InterviewTurnResponse:
    return InterviewTurnResponse(
        id=turn.id,
        session_id=turn.session_id,
        sequence_number=turn.sequence_number,
        main_question_number=turn.main_question_number,
        follow_up_number=turn.follow_up_number,
        parent_turn_id=turn.parent_turn_id,
        question=turn.question,
        question_type=turn.question_type,
        user_answer=turn.user_answer,
        technical_accuracy_score=turn.technical_accuracy_score,
        evidence_consistency_score=turn.evidence_consistency_score,
        answer_depth_score=turn.answer_depth_score,
        expression_structure_score=turn.expression_structure_score,
        job_match_score=turn.job_match_score,
        total_score=turn.total_score,
        evaluation_summary=turn.evaluation_summary,
        problems=turn.problems,
        optimized_answer=turn.optimized_answer,
        modification_reason=turn.modification_reason,
        has_evidence_conflict=bool(turn.has_evidence_conflict),
        evidence_conflicts=turn.evidence_conflicts,
        evidence_sources=turn.evidence_sources,
        answered_at=turn.answered_at,
        created_at=turn.created_at,
        updated_at=turn.updated_at,
    )


def session_to_response(
    db: Session,
    user_id: int,
    interview_session: InterviewSession,
) -> InterviewSessionResponse:
    target_job = None
    if interview_session.target_job_id is not None:
        job = (
            db.query(TargetJob)
            .filter(
                TargetJob.id == interview_session.target_job_id,
                TargetJob.user_id == user_id,
            )
            .first()
        )
        if job is not None:
            target_job = TargetJobSummary(
                id=job.id,
                job_title=job.job_title,
                company_name=job.company_name,
                is_active=bool(job.is_active),
            )

    selected_ids = interview_session.selected_project_file_ids or []
    project_files = []
    if selected_ids:
        records = (
            db.query(FileRecord)
            .filter(
                FileRecord.file_id.in_(selected_ids),
                FileRecord.user_id == user_id,
                FileRecord.category == "project",
            )
            .all()
        )
        records_by_id = {record.file_id: record for record in records}
        project_files = [
            ProjectFileSummary(
                file_id=records_by_id[file_id].file_id,
                filename=records_by_id[file_id].filename,
                file_type=records_by_id[file_id].file_type,
                category=records_by_id[file_id].category,
            )
            for file_id in selected_ids
            if file_id in records_by_id
        ]

    previous_session = None
    if interview_session.previous_session_id is not None:
        previous = (
            db.query(InterviewSession)
            .filter(
                InterviewSession.id == interview_session.previous_session_id,
                InterviewSession.user_id == user_id,
            )
            .first()
        )
        if previous is not None:
            previous_session = PreviousSessionSummary(
                id=previous.id,
                title=previous.title,
                mode=previous.mode,
                overall_score=previous.overall_score,
                completed_at=previous.completed_at,
            )

    return InterviewSessionResponse(
        id=interview_session.id,
        title=interview_session.title,
        mode=interview_session.mode,
        status=interview_session.status,
        planned_main_questions=interview_session.planned_main_questions,
        current_main_question=interview_session.current_main_question,
        selected_project_file_ids=selected_ids,
        overall_score=interview_session.overall_score,
        dimension_scores=interview_session.dimension_scores,
        summary=interview_session.summary,
        started_at=interview_session.started_at,
        completed_at=interview_session.completed_at,
        created_at=interview_session.created_at,
        updated_at=interview_session.updated_at,
        target_job=target_job,
        project_files=project_files,
        previous_session=previous_session,
    )


def session_to_detail(
    db: Session,
    user_id: int,
    interview_session: InterviewSession,
) -> InterviewSessionDetail:
    base = session_to_response(db, user_id, interview_session)
    turns = (
        db.query(InterviewTurn)
        .filter(
            InterviewTurn.session_id == interview_session.id,
            InterviewTurn.user_id == user_id,
        )
        .order_by(InterviewTurn.sequence_number.asc())
        .all()
    )
    tasks = (
        db.query(ImprovementTask)
        .filter(
            ImprovementTask.session_id == interview_session.id,
            ImprovementTask.user_id == user_id,
        )
        .order_by(ImprovementTask.id.asc())
        .all()
    )
    return InterviewSessionDetail(
        **base.model_dump(),
        turns=[turn_to_response(turn) for turn in turns],
        improvement_tasks=[task_to_response(task) for task in tasks],
    )


@router.post(
    "/interview-sessions",
    response_model=InterviewSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    request: InterviewSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        interview_session = create_interview_session(
            db,
            current_user.id,
            title=request.title,
            mode=request.mode,
            target_job_id=request.target_job_id,
            selected_project_file_ids=request.selected_project_file_ids,
            previous_session_id=request.previous_session_id,
        )
    except InterviewTrainingServiceError as error:
        raise_http_error(error)
    return session_to_response(db, current_user.id, interview_session)


@router.get(
    "/interview-sessions",
    response_model=InterviewSessionListResponse,
)
def get_sessions(
    session_status: InterviewStatus | None = Query(default=None, alias="status"),
    mode: InterviewMode | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sessions = list_interview_sessions(
        db,
        current_user.id,
        status=session_status,
        mode=mode,
    )
    return {
        "sessions": [
            session_to_response(db, current_user.id, interview_session)
            for interview_session in sessions
        ]
    }


@router.get(
    "/interview-sessions/{session_id}",
    response_model=InterviewSessionDetail,
)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        interview_session = get_owned_session(db, current_user.id, session_id)
    except InterviewTrainingServiceError as error:
        raise_http_error(error)
    return session_to_detail(db, current_user.id, interview_session)


@router.patch(
    "/interview-sessions/{session_id}",
    response_model=InterviewSessionResponse,
)
def patch_session(
    session_id: int,
    request: InterviewSessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        interview_session = update_interview_session(
            db,
            current_user.id,
            session_id,
            request.model_dump(exclude_unset=True),
        )
    except InterviewTrainingServiceError as error:
        raise_http_error(error)
    return session_to_response(db, current_user.id, interview_session)


@router.delete("/interview-sessions/{session_id}")
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        delete_interview_session(db, current_user.id, session_id)
    except InterviewTrainingServiceError as error:
        raise_http_error(error)
    return {"success": True, "message": "面试会话已删除"}


@router.post(
    "/interview-sessions/{session_id}/start",
    response_model=InterviewSessionResponse,
)
def start_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        interview_session = start_interview_session(
            db,
            current_user.id,
            session_id,
        )
    except InterviewTrainingServiceError as error:
        raise_http_error(error)
    return session_to_response(db, current_user.id, interview_session)


@router.post(
    "/interview-sessions/{session_id}/cancel",
    response_model=InterviewSessionResponse,
)
def cancel_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        interview_session = cancel_interview_session(
            db,
            current_user.id,
            session_id,
        )
    except InterviewTrainingServiceError as error:
        raise_http_error(error)
    return session_to_response(db, current_user.id, interview_session)
