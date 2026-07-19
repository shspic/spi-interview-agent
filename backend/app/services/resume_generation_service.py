import json

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents.interview_graph import InterviewAgentRuntime
from app.agents.resume_agent import ResumeAgent
from app.agents.schemas import (
    EvaluationConflict,
    EvaluationProblem,
    ResumeGenerationInput,
    ResumeInterviewTurnInput,
    ResumeProfileInput,
    ResumeProjectFileInput,
    ResumeSessionInput,
    ResumeTargetJobInput,
)
from app.db.models import (
    FileRecord,
    InterviewSession,
    InterviewTurn,
    ResumeProjectDescription,
    TargetJob,
    UserProfile,
)
from app.services.interview_session_service import now_iso
from app.services.resume_evidence_service import retrieve_resume_evidence


class ResumeGenerationError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def generate_resume_project_description(
    db: Session,
    user_id: int,
    *,
    session_id: int,
    target_job_id: int | None,
    project_file_ids: list[str] | None,
) -> ResumeProjectDescription:
    interview_session = _get_completed_session(db, user_id, session_id)
    project_files = _get_project_files(
        db,
        user_id,
        project_file_ids or interview_session.selected_project_file_ids or [],
    )
    target_job = _get_target_job(
        db,
        user_id,
        target_job_id,
        interview_session,
    )
    turns = _get_evaluated_turns(db, user_id, interview_session.id)
    evidence = retrieve_resume_evidence(
        db,
        user_id,
        interview_session,
        project_files,
        target_job,
    )
    payload = _build_input(
        db,
        user_id,
        interview_session,
        project_files,
        target_job,
        turns,
        evidence,
    )

    agent = ResumeAgent()
    runtime = InterviewAgentRuntime(db, user_id, interview_session.id)
    try:
        output = runtime.execute(agent, lambda: agent.generate(payload))
    except Exception as exc:
        raise ResumeGenerationError(
            502,
            "简历项目描述生成失败，请核对资料后重试",
        ) from exc

    now = now_iso()
    description = ResumeProjectDescription(
        user_id=user_id,
        session_id=interview_session.id,
        target_job_id=target_job.id if target_job is not None else None,
        project_file_ids=[record.file_id for record in project_files],
        project_name=output.project_name,
        one_line_summary=output.one_line_summary,
        concise_bullets=output.concise_bullets,
        detailed_description=output.detailed_description,
        technical_stack=output.technical_stack,
        responsibilities=output.responsibilities,
        challenges=output.challenges,
        solutions=output.solutions,
        outcomes=output.outcomes,
        interview_talking_points=output.interview_talking_points,
        warnings=output.warnings,
        evidence_source_ids=output.evidence_source_ids,
        prompt_version=agent.prompt_version,
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(description)
        db.commit()
        db.refresh(description)
    except SQLAlchemyError as exc:
        db.rollback()
        raise ResumeGenerationError(500, "简历项目描述保存失败") from exc
    return description


def list_resume_project_descriptions(
    db: Session,
    user_id: int,
) -> list[ResumeProjectDescription]:
    return (
        db.query(ResumeProjectDescription)
        .filter(ResumeProjectDescription.user_id == user_id)
        .order_by(ResumeProjectDescription.id.desc())
        .all()
    )


def get_owned_resume_project_description(
    db: Session,
    user_id: int,
    description_id: int,
) -> ResumeProjectDescription:
    description = (
        db.query(ResumeProjectDescription)
        .filter(
            ResumeProjectDescription.id == description_id,
            ResumeProjectDescription.user_id == user_id,
        )
        .first()
    )
    if description is None:
        raise ResumeGenerationError(404, "简历项目描述不存在")
    return description


def delete_resume_project_description(
    db: Session,
    user_id: int,
    description_id: int,
) -> None:
    description = get_owned_resume_project_description(
        db,
        user_id,
        description_id,
    )
    db.delete(description)
    db.commit()


def _get_completed_session(
    db: Session,
    user_id: int,
    session_id: int,
) -> InterviewSession:
    interview_session = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.id == session_id,
            InterviewSession.user_id == user_id,
        )
        .first()
    )
    if interview_session is None:
        raise ResumeGenerationError(404, "面试会话不存在")
    if interview_session.status != "completed":
        raise ResumeGenerationError(409, "只有已完成面试可以生成项目描述")
    return interview_session


def _get_project_files(
    db: Session,
    user_id: int,
    file_ids: list[str],
) -> list[FileRecord]:
    normalized_ids = list(dict.fromkeys(file_ids))
    if not normalized_ids:
        raise ResumeGenerationError(400, "至少需要选择一个项目文件")
    records = (
        db.query(FileRecord)
        .filter(
            FileRecord.user_id == user_id,
            FileRecord.file_id.in_(normalized_ids),
            FileRecord.category == "project",
        )
        .all()
    )
    records_by_id = {record.file_id: record for record in records}
    if set(records_by_id) != set(normalized_ids):
        raise ResumeGenerationError(404, "项目文件不存在")
    return [records_by_id[file_id] for file_id in normalized_ids]


def _get_target_job(
    db: Session,
    user_id: int,
    target_job_id: int | None,
    interview_session: InterviewSession,
) -> TargetJob | None:
    resolved_id = target_job_id or interview_session.target_job_id
    query = db.query(TargetJob).filter(TargetJob.user_id == user_id)
    if resolved_id is not None:
        job = query.filter(TargetJob.id == resolved_id).first()
        if job is None:
            raise ResumeGenerationError(404, "目标岗位不存在")
        return job
    return query.filter(TargetJob.is_active.is_(True)).first()


def _get_evaluated_turns(
    db: Session,
    user_id: int,
    session_id: int,
) -> list[InterviewTurn]:
    turns = (
        db.query(InterviewTurn)
        .filter(
            InterviewTurn.session_id == session_id,
            InterviewTurn.user_id == user_id,
            InterviewTurn.total_score.is_not(None),
            InterviewTurn.optimized_answer.is_not(None),
        )
        .order_by(InterviewTurn.sequence_number.asc())
        .all()
    )
    if not turns:
        raise ResumeGenerationError(409, "面试缺少有效评价结果")
    return turns


def _build_input(
    db: Session,
    user_id: int,
    interview_session: InterviewSession,
    project_files: list[FileRecord],
    target_job: TargetJob | None,
    turns: list[InterviewTurn],
    evidence,
) -> ResumeGenerationInput:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    profile_input = None
    if profile is not None:
        try:
            technical_skills = json.loads(profile.technical_skills or "[]")
        except json.JSONDecodeError:
            technical_skills = []
        profile_input = ResumeProfileInput(
            display_name=profile.display_name,
            target_direction=profile.target_direction,
            self_introduction=profile.self_introduction,
            technical_skills=(
                [str(item) for item in technical_skills]
                if isinstance(technical_skills, list)
                else []
            ),
        )

    return ResumeGenerationInput(
        project_files=[
            ResumeProjectFileInput(
                file_id=record.file_id,
                filename=record.filename,
                file_type=record.file_type,
            )
            for record in project_files
        ],
        project_evidence=evidence.project_evidence,
        resume_evidence=evidence.resume_evidence,
        profile_evidence=evidence.profile_evidence,
        profile=profile_input,
        target_job=(
            ResumeTargetJobInput(
                job_title=target_job.job_title,
                company_name=target_job.company_name,
                jd_text=target_job.jd_text,
            )
            if target_job is not None
            else None
        ),
        job_requirements=evidence.job_requirements,
        interview_session=ResumeSessionInput(
            session_id=interview_session.id,
            title=interview_session.title,
            mode=interview_session.mode,
            overall_score=interview_session.overall_score,
            dimension_scores=interview_session.dimension_scores,
            summary=interview_session.summary,
        ),
        interview_turns=[
            ResumeInterviewTurnInput(
                turn_id=turn.id,
                question=turn.question,
                total_score=turn.total_score,
                evaluation_summary=turn.evaluation_summary or "暂无评价摘要",
                strengths=turn.strengths or [],
                problems=_validated_items(turn.problems, EvaluationProblem),
                optimized_answer=turn.optimized_answer,
                unsupported_claims=turn.unsupported_claims or [],
                evidence_conflicts=_validated_items(
                    turn.evidence_conflicts,
                    EvaluationConflict,
                ),
            )
            for turn in turns
        ],
        evidence_is_sufficient=evidence.is_sufficient,
        evidence_reason=evidence.reason,
    )


def _validated_items(values: list | None, model_type):
    results = []
    for value in values or []:
        try:
            results.append(model_type.model_validate(value))
        except Exception:
            continue
    return results
