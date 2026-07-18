from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.agents.schemas import (
    EvaluationConflict,
    EvaluationOutput,
    EvaluationProblem,
    EvidenceOutput,
)
from app.db.models import InterviewSession, InterviewTurn
from app.services.interview_session_service import now_iso

SCORE_WEIGHTS = {
    "technical_accuracy_score": Decimal("0.30"),
    "evidence_consistency_score": Decimal("0.25"),
    "answer_depth_score": Decimal("0.20"),
    "expression_structure_score": Decimal("0.15"),
    "job_match_score": Decimal("0.10"),
}

DIMENSION_LABELS = {
    "technical_accuracy_score": "技术准确性",
    "evidence_consistency_score": "资料一致性",
    "answer_depth_score": "回答深度",
    "expression_structure_score": "表达结构",
    "job_match_score": "岗位匹配度",
}


def calculate_total_score(evaluation: EvaluationOutput) -> int:
    weighted_score = sum(
        Decimal(str(getattr(evaluation, field_name))) * weight
        for field_name, weight in SCORE_WEIGHTS.items()
    )
    rounded = weighted_score.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(0, min(100, int(rounded)))


def load_turn_evaluation(turn: InterviewTurn) -> EvaluationOutput | None:
    score_fields = [
        turn.technical_accuracy_score,
        turn.evidence_consistency_score,
        turn.answer_depth_score,
        turn.expression_structure_score,
        turn.job_match_score,
        turn.total_score,
    ]
    if any(value is None for value in score_fields):
        return None
    if not all(
        [
            turn.evaluation_summary,
            turn.optimized_answer,
            turn.modification_reason,
        ]
    ):
        return None
    return EvaluationOutput(
        technical_accuracy_score=turn.technical_accuracy_score,
        evidence_consistency_score=turn.evidence_consistency_score,
        answer_depth_score=turn.answer_depth_score,
        expression_structure_score=turn.expression_structure_score,
        job_match_score=turn.job_match_score,
        evaluation_summary=turn.evaluation_summary,
        problems=[
            EvaluationProblem.model_validate(item)
            for item in (turn.problems or [])
        ],
        optimized_answer=turn.optimized_answer,
        modification_reason=turn.modification_reason,
        has_evidence_conflict=bool(turn.has_evidence_conflict),
        evidence_conflicts=[
            EvaluationConflict.model_validate(item)
            for item in (turn.evidence_conflicts or [])
        ],
        evidence_source_ids=turn.evaluation_source_ids or [],
        unsupported_claims=turn.unsupported_claims or [],
        strengths=turn.strengths or [],
    )


def persist_turn_evaluation(
    db: Session,
    user_id: int,
    session_id: int,
    turn_id: int,
    evaluation: EvaluationOutput,
    evidence: EvidenceOutput,
) -> EvaluationOutput:
    total_score = calculate_total_score(evaluation)
    all_evidence = [
        *evidence.profile_evidence,
        *evidence.project_evidence,
        *evidence.resume_evidence,
        *evidence.job_requirements,
    ]
    now = now_iso()
    updated = (
        db.query(InterviewTurn)
        .filter(
            InterviewTurn.id == turn_id,
            InterviewTurn.session_id == session_id,
            InterviewTurn.user_id == user_id,
            InterviewTurn.user_answer.is_not(None),
            InterviewTurn.total_score.is_(None),
        )
        .update(
            {
                InterviewTurn.technical_accuracy_score: evaluation.technical_accuracy_score,
                InterviewTurn.evidence_consistency_score: evaluation.evidence_consistency_score,
                InterviewTurn.answer_depth_score: evaluation.answer_depth_score,
                InterviewTurn.expression_structure_score: evaluation.expression_structure_score,
                InterviewTurn.job_match_score: evaluation.job_match_score,
                InterviewTurn.total_score: total_score,
                InterviewTurn.evaluation_summary: evaluation.evaluation_summary,
                InterviewTurn.problems: [
                    item.model_dump() for item in evaluation.problems
                ],
                InterviewTurn.optimized_answer: evaluation.optimized_answer,
                InterviewTurn.modification_reason: evaluation.modification_reason,
                InterviewTurn.has_evidence_conflict: evaluation.has_evidence_conflict,
                InterviewTurn.evidence_conflicts: [
                    item.model_dump() for item in evaluation.evidence_conflicts
                ],
                InterviewTurn.evidence_sources: [
                    item.model_dump() for item in all_evidence
                ],
                InterviewTurn.evaluation_source_ids: evaluation.evidence_source_ids,
                InterviewTurn.unsupported_claims: evaluation.unsupported_claims,
                InterviewTurn.strengths: evaluation.strengths,
                InterviewTurn.updated_at: now,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    turn = db.get(InterviewTurn, turn_id)
    if updated == 0:
        existing = load_turn_evaluation(turn)
        if existing is None:
            raise ValueError("题目评价状态冲突")
        return existing
    return load_turn_evaluation(turn) or evaluation


def summarize_completed_session(
    db: Session,
    interview_session: InterviewSession,
) -> None:
    turns = (
        db.query(InterviewTurn)
        .filter(
            InterviewTurn.session_id == interview_session.id,
            InterviewTurn.user_id == interview_session.user_id,
            InterviewTurn.total_score.is_not(None),
            InterviewTurn.technical_accuracy_score.is_not(None),
            InterviewTurn.evidence_consistency_score.is_not(None),
            InterviewTurn.answer_depth_score.is_not(None),
            InterviewTurn.expression_structure_score.is_not(None),
            InterviewTurn.job_match_score.is_not(None),
        )
        .all()
    )
    if not turns:
        interview_session.overall_score = None
        interview_session.dimension_scores = None
        interview_session.summary = "会话已完成，但暂无有效评分。"
        return

    count = Decimal(len(turns))
    overall_score = (
        sum(Decimal(str(turn.total_score)) for turn in turns) / count
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    dimension_scores = {}
    for field_name in SCORE_WEIGHTS:
        average = (
            sum(Decimal(str(getattr(turn, field_name))) for turn in turns) / count
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        dimension_scores[field_name] = float(average)

    strongest = max(dimension_scores, key=dimension_scores.get)
    weakest = min(dimension_scores, key=dimension_scores.get)
    interview_session.overall_score = float(overall_score)
    interview_session.dimension_scores = dimension_scores
    interview_session.summary = (
        f"本次共统计 {len(turns)} 道已评分题目，平均总分 "
        f"{float(overall_score):.2f}；表现较好维度为"
        f"{DIMENSION_LABELS[strongest]}，优先提升维度为"
        f"{DIMENSION_LABELS[weakest]}。"
    )
