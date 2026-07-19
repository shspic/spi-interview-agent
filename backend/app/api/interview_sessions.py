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
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewComparisonResponse,
    InterviewMode,
    InterviewSessionCreate,
    InterviewSessionDetail,
    InterviewSessionListResponse,
    InterviewSessionResponse,
    InterviewRetryResponse,
    InterviewStartResponse,
    InterviewSessionUpdate,
    InterviewStatus,
    ImprovementTaskResponse,
    ImprovementTaskSourceTurnSummary,
    ImprovementGenerationResponse,
    InterviewTurnResponse,
    PreviousSessionSummary,
    ProjectFileSummary,
    TargetJobSummary,
)
from app.services.interview_flow_service import (
    InterviewFlowError,
    answer_interview_turn,
    start_interview_flow,
)
from app.services.improvement_generation_service import (
    ImprovementGenerationError,
    generate_improvements_for_session,
)
from app.services.interview_retry_service import (
    compare_retry_session,
    comparison_available,
    create_retry_session,
)
from app.services.interview_session_service import (
    InterviewTrainingServiceError,
    cancel_interview_session,
    create_interview_session,
    delete_interview_session,
    get_owned_session,
    list_interview_sessions,
    update_interview_session,
)

router = APIRouter()


def raise_http_error(error: InterviewTrainingServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def task_to_response(task: ImprovementTask) -> ImprovementTaskResponse:
    source_turn = None
    if (
        task.turn is not None
        and task.turn.user_id == task.user_id
        and task.turn.session_id == task.session_id
    ):
        source_turn = ImprovementTaskSourceTurnSummary(
            id=task.turn.id,
            sequence_number=task.turn.sequence_number,
            main_question_number=task.turn.main_question_number,
            follow_up_number=task.turn.follow_up_number,
            question=task.turn.question,
        )
    return ImprovementTaskResponse(
        id=task.id,
        session_id=task.session_id,
        turn_id=task.turn_id,
        title=task.title,
        description=task.description,
        completion_criteria=task.completion_criteria,
        category=task.category,
        priority=task.priority,
        status=task.status,
        created_at=task.created_at,
        completed_at=task.completed_at,
        updated_at=task.updated_at,
        source_turn=source_turn,
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
        evaluation_source_ids=turn.evaluation_source_ids,
        unsupported_claims=turn.unsupported_claims,
        strengths=turn.strengths,
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
        improvement_status=interview_session.improvement_status,
        improvement_summary=interview_session.improvement_summary,
        next_round_strategy=interview_session.next_round_strategy,
        improvement_generated_at=interview_session.improvement_generated_at,
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
    progress = calculate_progress(interview_session, turns)
    return InterviewSessionDetail(
        **base.model_dump(),
        turns=[turn_to_response(turn) for turn in turns],
        improvement_tasks=[task_to_response(task) for task in tasks],
        interview_plan=interview_session.interview_plan,
        current_question=(
            turn_to_response(progress["current_question"])
            if progress["current_question"] is not None
            else None
        ),
        completed_main_questions=progress["completed_main_questions"],
        current_follow_up_count=progress["current_follow_up_count"],
        is_completed=interview_session.status == "completed",
        comparison_available=comparison_available(
            db,
            user_id,
            interview_session,
        ),
        agent_execution_summary=interview_session.agent_execution_summary,
    )


def calculate_progress(
    interview_session: InterviewSession,
    turns: list[InterviewTurn],
) -> dict:
    current_question = next(
        (turn for turn in reversed(turns) if turn.user_answer is None),
        None,
    )
    active_main_question = (
        current_question.main_question_number
        if current_question is not None
        else interview_session.current_main_question
    )
    current_follow_up_count = sum(
        1
        for turn in turns
        if turn.main_question_number == active_main_question
        and turn.follow_up_number > 0
    )
    main_question_numbers = sorted(
        {turn.main_question_number for turn in turns if turn.follow_up_number == 0}
    )
    max_main_question = max(main_question_numbers, default=0)
    completed_main_questions = 0
    for main_question_number in main_question_numbers:
        question_group = [
            turn
            for turn in turns
            if turn.main_question_number == main_question_number
        ]
        if all(turn.user_answer is not None for turn in question_group) and (
            interview_session.status == "completed"
            or main_question_number < max_main_question
        ):
            completed_main_questions += 1
    return {
        "current_question": current_question,
        "completed_main_questions": completed_main_questions,
        "current_follow_up_count": current_follow_up_count,
    }


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
    response_model=InterviewStartResponse,
)
def start_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = start_interview_flow(
            db,
            current_user.id,
            session_id,
        )
    except (InterviewFlowError, InterviewTrainingServiceError) as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    base = session_to_response(db, current_user.id, result.interview_session)
    return InterviewStartResponse(
        **base.model_dump(),
        interview_plan=result.plan,
        current_question=turn_to_response(result.first_turn),
        completed_main_questions=0,
        current_follow_up_count=0,
        is_completed=False,
        evidence_limited=result.evidence_limited,
        agent_execution_summary=result.agent_execution_summary,
    )


@router.post(
    "/interview-sessions/{session_id}/answer",
    response_model=InterviewAnswerResponse,
)
def answer_session_question(
    session_id: int,
    request: InterviewAnswerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = answer_interview_turn(
            db,
            current_user.id,
            session_id,
            request.turn_id,
            request.answer,
        )
    except (InterviewFlowError, InterviewTrainingServiceError) as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    turns = (
        db.query(InterviewTurn)
        .filter(
            InterviewTurn.session_id == session_id,
            InterviewTurn.user_id == current_user.id,
        )
        .order_by(InterviewTurn.sequence_number.asc())
        .all()
    )
    progress = calculate_progress(result.interview_session, turns)
    base = session_to_response(db, current_user.id, result.interview_session)
    return InterviewAnswerResponse(
        **base.model_dump(),
        decision=result.decision,
        answered_turn=turn_to_response(result.answered_turn),
        current_question=(
            turn_to_response(progress["current_question"])
            if progress["current_question"] is not None
            else None
        ),
        completed_main_questions=progress["completed_main_questions"],
        current_follow_up_count=progress["current_follow_up_count"],
        is_completed=result.interview_session.status == "completed",
        evidence_limited=result.evidence_limited,
        agent_execution_summary=result.agent_execution_summary,
    )


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


@router.post(
    "/interview-sessions/{session_id}/improvements/retry",
    response_model=ImprovementGenerationResponse,
)
def retry_improvement_generation(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = generate_improvements_for_session(
            db,
            current_user.id,
            session_id,
        )
    except ImprovementGenerationError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return ImprovementGenerationResponse(
        session_id=result.interview_session.id,
        improvement_status=result.interview_session.improvement_status,
        improvement_summary=result.interview_session.improvement_summary,
        next_round_strategy=result.interview_session.next_round_strategy,
        improvement_generated_at=(
            result.interview_session.improvement_generated_at
        ),
        generated=result.generated,
        tasks=[task_to_response(task) for task in result.tasks],
    )


@router.post(
    "/interview-sessions/{session_id}/retry",
    response_model=InterviewRetryResponse,
    status_code=status.HTTP_201_CREATED,
)
def retry_interview_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = create_retry_session(db, current_user.id, session_id)
    except InterviewTrainingServiceError as error:
        raise_http_error(error)
    base = session_to_response(db, current_user.id, result.interview_session)
    return InterviewRetryResponse(
        **base.model_dump(),
        source_session_id=result.source_session_id,
        previous_task_count=result.previous_task_count,
        completed_task_count=result.completed_task_count,
        pending_task_count=result.pending_task_count,
        task_completion_rate=result.task_completion_rate,
    )


@router.get(
    "/interview-sessions/{session_id}/comparison",
    response_model=InterviewComparisonResponse,
)
def get_interview_comparison(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return compare_retry_session(db, current_user.id, session_id)
    except InterviewTrainingServiceError as error:
        raise_http_error(error)
