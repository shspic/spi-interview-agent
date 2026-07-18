from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.interview_graph import (
    InterviewAgentRuntime,
    InterviewGraphState,
    run_interview_graph,
)
from app.agents.schemas import (
    InterviewPlanOutput,
    SupervisorDecisionOutput,
)
from app.db.models import InterviewSession, InterviewTurn, TargetJob
from app.services.interview_session_service import (
    InterviewTrainingServiceError,
    create_interview_turn,
    get_owned_session,
    now_iso,
)


class InterviewFlowError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class InterviewStartResult:
    interview_session: InterviewSession
    first_turn: InterviewTurn
    plan: InterviewPlanOutput
    evidence_limited: bool
    agent_execution_summary: dict


@dataclass
class InterviewAnswerResult:
    interview_session: InterviewSession
    answered_turn: InterviewTurn
    next_turn: InterviewTurn | None
    decision: SupervisorDecisionOutput
    evidence_limited: bool
    agent_execution_summary: dict


def _target_job_title(
    db: Session,
    user_id: int,
    interview_session: InterviewSession,
) -> str | None:
    query = db.query(TargetJob).filter(TargetJob.user_id == user_id)
    if interview_session.target_job_id is not None:
        query = query.filter(TargetJob.id == interview_session.target_job_id)
    else:
        query = query.filter(TargetJob.is_active.is_(True))
    job = query.first()
    return job.job_title if job is not None else None


def _store_failed_summary(
    db: Session,
    user_id: int,
    session_id: int,
    runtime: InterviewAgentRuntime,
    error: Exception,
) -> None:
    db.rollback()
    interview_session = get_owned_session(db, user_id, session_id)
    interview_session.agent_execution_summary = runtime.summary(
        "error",
        error=type(error).__name__,
    )
    interview_session.updated_at = now_iso()
    db.commit()


def _build_success_summary(
    runtime: InterviewAgentRuntime,
    state: InterviewGraphState,
) -> dict:
    summary = runtime.summary("success")
    decision = state.get("decision")
    question = state.get("generated_question")
    evidence = state.get("evidence")
    if decision is not None:
        summary["decision"] = decision.model_dump()
    if question is not None:
        summary["evidence_limited"] = question.evidence_limited
    elif evidence is not None:
        summary["evidence_limited"] = not evidence.is_sufficient
    return summary


def start_interview_flow(
    db: Session,
    user_id: int,
    session_id: int,
) -> InterviewStartResult:
    interview_session = get_owned_session(db, user_id, session_id)
    if interview_session.status != "draft":
        raise InterviewFlowError(409, "只有草稿会话可以启动")
    existing_turn = (
        db.query(InterviewTurn.id)
        .filter(
            InterviewTurn.session_id == session_id,
            InterviewTurn.user_id == user_id,
        )
        .first()
    )
    if existing_turn is not None:
        raise InterviewFlowError(409, "该会话已经生成过面试题")

    runtime = InterviewAgentRuntime(db, user_id, session_id)
    initial_state: InterviewGraphState = {
        "operation": "start",
        "title": interview_session.title,
        "mode": interview_session.mode,
        "planned_main_questions": interview_session.planned_main_questions,
        "target_job_title": _target_job_title(
            db,
            user_id,
            interview_session,
        ),
        "session_id": session_id,
        "user_id": user_id,
    }
    try:
        state = run_interview_graph(runtime, initial_state)
    except Exception as exc:
        _store_failed_summary(db, user_id, session_id, runtime, exc)
        raise InterviewFlowError(
            502,
            "多 Agent 面试启动失败，请稍后重试",
        ) from exc

    plan = state["plan"]
    generated_question = state["generated_question"]
    summary = _build_success_summary(runtime, state)
    now = now_iso()
    try:
        updated = (
            db.query(InterviewSession)
            .filter(
                InterviewSession.id == session_id,
                InterviewSession.user_id == user_id,
                InterviewSession.status == "draft",
            )
            .update(
                {
                    InterviewSession.status: "in_progress",
                    InterviewSession.started_at: now,
                    InterviewSession.current_main_question: 1,
                    InterviewSession.interview_plan: plan.model_dump(),
                    InterviewSession.agent_execution_summary: summary,
                    InterviewSession.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            db.rollback()
            raise InterviewFlowError(409, "该会话已经启动")
        turn = create_interview_turn(
            db,
            user_id,
            session_id,
            question=generated_question.question,
            main_question_number=1,
            commit=False,
        )
        turn.evidence_sources = [
            item.model_dump() for item in state["evidence"].sources
        ]
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise InterviewFlowError(409, "该会话已经生成第一题") from exc

    interview_session = get_owned_session(db, user_id, session_id)
    db.refresh(turn)
    return InterviewStartResult(
        interview_session=interview_session,
        first_turn=turn,
        plan=plan,
        evidence_limited=generated_question.evidence_limited,
        agent_execution_summary=summary,
    )


def _load_plan(interview_session: InterviewSession) -> InterviewPlanOutput:
    if not interview_session.interview_plan:
        raise InterviewFlowError(409, "面试计划不存在，请重新创建会话")
    try:
        return InterviewPlanOutput.model_validate(interview_session.interview_plan)
    except Exception as exc:
        raise InterviewFlowError(409, "面试计划数据无效") from exc


def answer_interview_turn(
    db: Session,
    user_id: int,
    session_id: int,
    turn_id: int,
    answer: str,
) -> InterviewAnswerResult:
    interview_session = get_owned_session(db, user_id, session_id)
    if interview_session.status != "in_progress":
        raise InterviewFlowError(409, "当前会话不在进行中")
    current_turn = (
        db.query(InterviewTurn)
        .filter(
            InterviewTurn.session_id == session_id,
            InterviewTurn.user_id == user_id,
        )
        .order_by(InterviewTurn.sequence_number.desc())
        .first()
    )
    if current_turn is None or current_turn.id != turn_id:
        raise InterviewFlowError(409, "只能回答当前待回答题目")

    normalized_answer = answer.strip()
    now = now_iso()
    if current_turn.user_answer is None:
        updated = (
            db.query(InterviewTurn)
            .filter(
                InterviewTurn.id == turn_id,
                InterviewTurn.session_id == session_id,
                InterviewTurn.user_id == user_id,
                InterviewTurn.user_answer.is_(None),
            )
            .update(
                {
                    InterviewTurn.user_answer: normalized_answer,
                    InterviewTurn.answered_at: now,
                    InterviewTurn.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if updated != 1:
            db.expire_all()
        current_turn = db.get(InterviewTurn, turn_id)
        if updated != 1:
            newer_turn = (
                db.query(InterviewTurn.id)
                .filter(
                    InterviewTurn.session_id == session_id,
                    InterviewTurn.sequence_number > current_turn.sequence_number,
                )
                .first()
            )
            if (
                newer_turn is not None
                or current_turn.user_answer != normalized_answer
            ):
                raise InterviewFlowError(409, "该题目已经回答")
    else:
        newer_turn = (
            db.query(InterviewTurn.id)
            .filter(
                InterviewTurn.session_id == session_id,
                InterviewTurn.sequence_number > current_turn.sequence_number,
            )
            .first()
        )
        if newer_turn is not None or current_turn.user_answer != normalized_answer:
            raise InterviewFlowError(409, "该题目已经回答")

    plan = _load_plan(interview_session)
    follow_up_count = (
        db.query(InterviewTurn)
        .filter(
            InterviewTurn.session_id == session_id,
            InterviewTurn.main_question_number == current_turn.main_question_number,
            InterviewTurn.follow_up_number > 0,
        )
        .count()
    )
    runtime = InterviewAgentRuntime(db, user_id, session_id)
    initial_state: InterviewGraphState = {
        "operation": "answer",
        "title": interview_session.title,
        "mode": interview_session.mode,
        "planned_main_questions": interview_session.planned_main_questions,
        "target_job_title": _target_job_title(db, user_id, interview_session),
        "session_id": session_id,
        "user_id": user_id,
        "plan": plan,
        "current_main_question": current_turn.main_question_number,
        "current_follow_up_count": follow_up_count,
        "current_question": current_turn.question,
        "latest_answer": current_turn.user_answer,
    }
    try:
        state = run_interview_graph(runtime, initial_state)
    except Exception as exc:
        _store_failed_summary(db, user_id, session_id, runtime, exc)
        raise InterviewFlowError(
            502,
            "下一题生成失败，回答已保存，可使用相同答案重试",
        ) from exc

    decision = state["decision"]
    summary = _build_success_summary(runtime, state)
    interview_session = get_owned_session(db, user_id, session_id)
    if interview_session.status != "in_progress":
        raise InterviewFlowError(409, "会话状态已变化，请刷新后重试")
    if decision.action == "complete":
        interview_session.status = "completed"
        interview_session.completed_at = now_iso()
        interview_session.agent_execution_summary = summary
        interview_session.updated_at = interview_session.completed_at
        db.commit()
        db.refresh(current_turn)
        return InterviewAnswerResult(
            interview_session=interview_session,
            answered_turn=current_turn,
            next_turn=None,
            decision=decision,
            evidence_limited=not state["evidence"].is_sufficient,
            agent_execution_summary=summary,
        )

    generated_question = state["generated_question"]
    next_main_question = current_turn.main_question_number
    parent_turn_id = current_turn.id
    if decision.action == "next_main_question":
        next_main_question += 1
        parent_turn_id = None
    try:
        next_turn = create_interview_turn(
            db,
            user_id,
            session_id,
            question=generated_question.question,
            main_question_number=next_main_question,
            parent_turn_id=parent_turn_id,
            commit=False,
        )
        next_turn.evidence_sources = [
            item.model_dump() for item in state["evidence"].sources
        ]
        interview_session = get_owned_session(db, user_id, session_id)
        interview_session.current_main_question = next_main_question
        interview_session.agent_execution_summary = summary
        interview_session.updated_at = now_iso()
        db.commit()
        db.refresh(next_turn)
    except IntegrityError as exc:
        db.rollback()
        raise InterviewFlowError(409, "下一题已经生成，请刷新会话") from exc
    except InterviewTrainingServiceError as exc:
        db.rollback()
        raise InterviewFlowError(exc.status_code, exc.detail) from exc

    db.refresh(current_turn)
    return InterviewAnswerResult(
        interview_session=interview_session,
        answered_turn=current_turn,
        next_turn=next_turn,
        decision=decision,
        evidence_limited=generated_question.evidence_limited,
        agent_execution_summary=summary,
    )
