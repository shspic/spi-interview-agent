import hashlib
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.improvement_agent import ImprovementAgent
from app.agents.interview_graph import InterviewAgentRuntime
from app.agents.schemas import (
    EvaluationConflict,
    EvaluationProblem,
    ExistingImprovementTaskInput,
    ImprovementInput,
    ImprovementOutput,
    ImprovementTurnInput,
)
from app.db.models import ImprovementTask, InterviewSession, InterviewTurn, TargetJob
from app.services.interview_session_service import (
    InterviewTrainingServiceError,
    get_owned_session,
    now_iso,
)


class ImprovementGenerationError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class ImprovementGenerationResult:
    interview_session: InterviewSession
    tasks: list[ImprovementTask]
    generated: bool


def _validated_items(values: list | None, model_type):
    results = []
    for value in values or []:
        try:
            results.append(model_type.model_validate(value))
        except Exception:
            continue
    return results


def _build_input(
    db: Session,
    user_id: int,
    interview_session: InterviewSession,
) -> ImprovementInput:
    turns = (
        db.query(InterviewTurn)
        .filter(
            InterviewTurn.session_id == interview_session.id,
            InterviewTurn.user_id == user_id,
            InterviewTurn.total_score.is_not(None),
        )
        .order_by(InterviewTurn.sequence_number.asc())
        .all()
    )
    if not turns:
        raise ImprovementGenerationError(409, "会话没有可用于生成改进任务的评分")

    target_job = None
    if interview_session.target_job_id is not None:
        target_job = (
            db.query(TargetJob)
            .filter(
                TargetJob.id == interview_session.target_job_id,
                TargetJob.user_id == user_id,
            )
            .first()
        )
    existing_tasks = (
        db.query(ImprovementTask)
        .filter(
            ImprovementTask.session_id == interview_session.id,
            ImprovementTask.user_id == user_id,
        )
        .all()
    )

    return ImprovementInput(
        mode=interview_session.mode,
        target_job_title=target_job.job_title if target_job else None,
        target_company_name=target_job.company_name if target_job else None,
        overall_score=interview_session.overall_score,
        dimension_scores=interview_session.dimension_scores,
        turns=[
            ImprovementTurnInput(
                turn_id=turn.id,
                question=turn.question,
                technical_accuracy_score=turn.technical_accuracy_score,
                evidence_consistency_score=turn.evidence_consistency_score,
                answer_depth_score=turn.answer_depth_score,
                expression_structure_score=turn.expression_structure_score,
                job_match_score=turn.job_match_score,
                total_score=turn.total_score,
                problems=_validated_items(turn.problems, EvaluationProblem),
                strengths=turn.strengths or [],
                unsupported_claims=turn.unsupported_claims or [],
                evidence_conflicts=_validated_items(
                    turn.evidence_conflicts,
                    EvaluationConflict,
                ),
                evaluation_summary=turn.evaluation_summary or "暂无评价摘要",
            )
            for turn in turns
        ],
        existing_tasks=[
            ExistingImprovementTaskInput(
                title=task.title,
                category=task.category,
                source_turn_id=task.turn_id,
                status=task.status,
            )
            for task in existing_tasks
        ],
    )


def _dedupe_key(
    session_id: int,
    title: str,
    category: str,
    source_turn_id: int | None,
) -> str:
    normalized_title = " ".join(title.split()).casefold()
    raw_key = f"{session_id}|{category}|{source_turn_id}|{normalized_title}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _persist_output(
    db: Session,
    user_id: int,
    interview_session: InterviewSession,
    output: ImprovementOutput,
) -> list[ImprovementTask]:
    allowed_turn_ids = {
        item.id
        for item in db.query(InterviewTurn.id)
        .filter(
            InterviewTurn.session_id == interview_session.id,
            InterviewTurn.user_id == user_id,
        )
        .all()
    }
    existing_tasks = (
        db.query(ImprovementTask)
        .filter(
            ImprovementTask.session_id == interview_session.id,
            ImprovementTask.user_id == user_id,
        )
        .order_by(ImprovementTask.id.asc())
        .all()
    )
    remaining_slots = max(8 - len(existing_tasks), 0)
    now = now_iso()
    generated = []
    for proposal in output.tasks[:remaining_slots]:
        if (
            proposal.source_turn_id is not None
            and proposal.source_turn_id not in allowed_turn_ids
        ):
            raise ImprovementGenerationError(502, "改进任务引用了无效题目")
        generated.append(
            ImprovementTask(
                user_id=user_id,
                session_id=interview_session.id,
                turn_id=proposal.source_turn_id,
                title=proposal.title.strip(),
                description=proposal.description.strip(),
                completion_criteria=proposal.completion_criteria.strip(),
                category=proposal.category,
                priority=proposal.priority,
                status="pending",
                dedupe_key=_dedupe_key(
                    interview_session.id,
                    proposal.title,
                    proposal.category,
                    proposal.source_turn_id,
                ),
                created_at=now,
                updated_at=now,
            )
        )
    if len(existing_tasks) + len(generated) < 3:
        raise ImprovementGenerationError(502, "改进任务数量不足")

    db.add_all(generated)
    interview_session.improvement_status = "completed"
    interview_session.improvement_summary = output.overall_diagnosis
    interview_session.next_round_strategy = output.next_round_strategy
    interview_session.improvement_generated_at = now
    interview_session.improvement_error = None
    interview_session.updated_at = now
    db.commit()
    for task in generated:
        db.refresh(task)
    return [*existing_tasks, *generated]


def _mark_failed(
    db: Session,
    user_id: int,
    session_id: int,
    error: Exception,
) -> None:
    db.rollback()
    interview_session = get_owned_session(db, user_id, session_id)
    interview_session.improvement_status = "failed"
    interview_session.improvement_error = (
        f"{type(error).__name__}: 改进任务生成失败"
    )
    interview_session.updated_at = now_iso()
    db.commit()


def generate_improvements_for_session(
    db: Session,
    user_id: int,
    session_id: int,
) -> ImprovementGenerationResult:
    try:
        interview_session = get_owned_session(db, user_id, session_id)
    except InterviewTrainingServiceError as exc:
        raise ImprovementGenerationError(exc.status_code, exc.detail) from exc
    if interview_session.status != "completed":
        raise ImprovementGenerationError(409, "只有已完成会话可以生成改进任务")
    if interview_session.improvement_status == "completed":
        tasks = (
            db.query(ImprovementTask)
            .filter(
                ImprovementTask.session_id == session_id,
                ImprovementTask.user_id == user_id,
            )
            .order_by(ImprovementTask.id.asc())
            .all()
        )
        return ImprovementGenerationResult(interview_session, tasks, False)

    updated = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.id == session_id,
            InterviewSession.user_id == user_id,
            InterviewSession.status == "completed",
            InterviewSession.improvement_status.in_(["pending", "failed"]),
        )
        .update(
            {
                InterviewSession.improvement_status: "generating",
                InterviewSession.improvement_error: None,
                InterviewSession.updated_at: now_iso(),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if updated != 1:
        raise ImprovementGenerationError(409, "改进任务正在生成，请稍后重试")

    interview_session = get_owned_session(db, user_id, session_id)
    try:
        payload = _build_input(db, user_id, interview_session)
        agent = ImprovementAgent()
        runtime = InterviewAgentRuntime(db, user_id, session_id)
        output = runtime.execute(agent, lambda: agent.generate(payload))
        tasks = _persist_output(db, user_id, interview_session, output)
    except IntegrityError as exc:
        _mark_failed(db, user_id, session_id, exc)
        raise ImprovementGenerationError(409, "改进任务已生成，请刷新后查看") from exc
    except Exception as exc:
        _mark_failed(db, user_id, session_id, exc)
        if isinstance(exc, ImprovementGenerationError):
            raise
        raise ImprovementGenerationError(
            502,
            "改进任务生成失败，可稍后重试",
        ) from exc

    interview_session = get_owned_session(db, user_id, session_id)
    return ImprovementGenerationResult(interview_session, tasks, True)
