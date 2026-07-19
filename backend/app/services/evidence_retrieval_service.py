import json
import logging

from sqlalchemy.orm import Session

from app.agents.schemas import EvidenceItem, EvidenceOutput
from app.core.config import settings
from app.db.models import FileRecord, InterviewSession, TargetJob, UserProfile
from app.services.retrieval_confidence import decide_retrieval_evidence
from app.services.vector_store import DISTANCE_METRIC, search_evidence_candidates


# 保留既有测试与调用注入点；实际实现已切换为证据候选检索。
def search_candidate_chunks(query: str, user_id: int, candidate_k: int):
    return search_evidence_candidates(query, user_id, candidate_k)


logger = logging.getLogger(__name__)

INVALID_EVIDENCE_REASONS = {
    "missing_file_id",
    "invalid_file_id",
    "file_not_found",
    "metadata_user_mismatch",
    "file_owner_mismatch",
    "unsupported_source_type",
}


def _filter_owned_file_chunks(
    db: Session,
    user_id: int,
    session_id: int,
    chunks: list[dict],
) -> list[tuple[dict, FileRecord]]:
    candidate_file_ids = {
        metadata["file_id"]
        for chunk in chunks
        if isinstance((metadata := chunk.get("metadata")), dict)
        and isinstance(metadata.get("file_id"), str)
        and metadata["file_id"].strip()
        and len(metadata["file_id"]) <= 255
    }
    records = (
        db.query(FileRecord)
        .filter(FileRecord.file_id.in_(candidate_file_ids))
        .all()
        if candidate_file_ids
        else []
    )
    records_by_id = {record.file_id: record for record in records}
    rejected: dict[str, int] = {}
    valid: list[tuple[dict, FileRecord]] = []

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    for chunk in chunks:
        metadata = chunk.get("metadata")
        if not isinstance(metadata, dict) or "file_id" not in metadata:
            reject("missing_file_id")
            continue
        file_id = metadata.get("file_id")
        if (
            not isinstance(file_id, str)
            or not file_id.strip()
            or len(file_id) > 255
        ):
            reject("invalid_file_id")
            continue
        metadata_user_id = metadata.get("user_id")
        if metadata_user_id is not None and (
            not isinstance(metadata_user_id, int)
            or isinstance(metadata_user_id, bool)
            or metadata_user_id != user_id
        ):
            reject("metadata_user_mismatch")
            continue
        record = records_by_id.get(file_id)
        if record is None:
            reject("file_not_found")
            continue
        if record.user_id != user_id:
            reject("file_owner_mismatch")
            continue
        if record.category not in {"project", "resume"}:
            reject("unsupported_source_type")
            continue
        valid.append((chunk, record))

    if rejected:
        logger.warning(
            "evidence_chunks_rejected user_id=%s session_id=%s rejected_count=%s reasons=%s",
            user_id,
            session_id,
            sum(rejected.values()),
            ",".join(
                f"{reason}:{rejected[reason]}"
                for reason in sorted(rejected)
                if reason in INVALID_EVIDENCE_REASONS
            ),
        )
    return valid


def load_profile_evidence(
    db: Session,
    user_id: int,
) -> list[EvidenceItem]:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if profile is None:
        return []
    try:
        skills = json.loads(profile.technical_skills or "[]")
    except json.JSONDecodeError:
        skills = []
    content_parts = [
        f"目标方向：{profile.target_direction}" if profile.target_direction else "",
        f"技术栈：{', '.join(str(item) for item in skills)}" if skills else "",
        f"自我介绍：{profile.self_introduction[:2000]}"
        if profile.self_introduction
        else "",
    ]
    content = "\n".join(item for item in content_parts if item)
    if not content:
        return []
    return [
        EvidenceItem(
            evidence_type="profile",
            source_id=f"profile:{profile.id}",
            content=content,
        )
    ]


def _load_job_requirements(
    db: Session,
    user_id: int,
    interview_session: InterviewSession,
) -> list[EvidenceItem]:
    query = db.query(TargetJob).filter(TargetJob.user_id == user_id)
    if interview_session.target_job_id is not None:
        query = query.filter(TargetJob.id == interview_session.target_job_id)
    else:
        query = query.filter(TargetJob.is_active.is_(True))
    job = query.first()
    if job is None:
        return []
    return [
        EvidenceItem(
            evidence_type="job_requirement",
            source_id=f"target_job:{job.id}",
            content=(
                f"岗位：{job.job_title}\n公司：{job.company_name}\n"
                f"JD：{job.jd_text[:5000]}"
            ),
        )
    ]


def retrieve_interview_evidence(
    db: Session,
    user_id: int,
    session_id: int,
    query: str,
    top_k: int = 6,
) -> EvidenceOutput:
    interview_session = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.id == session_id,
            InterviewSession.user_id == user_id,
        )
        .first()
    )
    if interview_session is None:
        raise ValueError("面试会话不存在")

    profile_evidence = load_profile_evidence(db, user_id)
    job_requirements = _load_job_requirements(db, user_id, interview_session)
    search_error = None
    try:
        search_result = search_candidate_chunks(
            query=query,
            user_id=user_id,
            candidate_k=top_k,
        )
        chunks = search_result.get("chunks", []) or []
    except Exception:
        chunks = []
        search_error = "知识库检索暂时不可用"

    owned_chunks = _filter_owned_file_chunks(db, user_id, session_id, chunks)
    distances = [
        float(chunk["distance"])
        for chunk, _record in owned_chunks
        if isinstance(chunk.get("distance"), (int, float))
        and not isinstance(chunk.get("distance"), bool)
    ]
    best_distance = min(distances) if distances else None
    selected_projects = set(interview_session.selected_project_file_ids or [])
    trusted_chunks = []
    records_by_id = {}
    for chunk, record in owned_chunks:
        metadata = chunk.get("metadata") or {}
        chunk_index = metadata.get("chunk_index")
        if (
            not isinstance(chunk_index, int)
            or isinstance(chunk_index, bool)
            or chunk_index < 0
        ):
            continue
        if (
            record.category == "project"
            and selected_projects
            and record.file_id not in selected_projects
        ):
            continue
        records_by_id[record.file_id] = record
        trusted_chunks.append(
            {
                "content": chunk.get("content"),
                "distance": chunk.get("distance"),
                "metadata": {
                    "user_id": user_id,
                    "file_id": record.file_id,
                    "filename": record.filename,
                    "file_type": record.file_type,
                    "category": record.category,
                    "chunk_index": chunk_index,
                },
            }
        )

    decision = decide_retrieval_evidence(
        query,
        trusted_chunks,
        top_k=top_k,
        high_confidence_distance=settings.evidence_max_distance,
        trusted_file_names={
            file_id: record.filename
            for file_id, record in records_by_id.items()
        },
        allowed_categories={"project", "resume"},
    )
    ranked_chunks = decision.accepted_candidates
    logger.info(
        "evidence_retrieval_decision user_id=%s session_id=%s sufficient=%s "
        "reason=%s candidate_count=%s accepted_count=%s",
        user_id,
        session_id,
        decision.sufficient,
        decision.decision_reason,
        len(trusted_chunks),
        len(ranked_chunks),
    )
    project_evidence = []
    resume_evidence = []

    for chunk in ranked_chunks:
        metadata = chunk.get("metadata") or {}
        file_id = metadata["file_id"]
        record = records_by_id[file_id]
        distance = float(chunk["distance"])
        chunk_index = metadata.get("chunk_index")
        category = record.category
        item = EvidenceItem(
            evidence_type=category,
            source_id=(
                f"{file_id}:{chunk_index}"
                if chunk_index is not None
                else file_id
            ),
            filename=record.filename,
            chunk_index=chunk_index,
            content=str(chunk.get("content") or "")[:2000],
            distance=distance,
        )
        if category == "project":
            project_evidence.append(item)
        else:
            resume_evidence.append(item)

    if interview_session.mode == "deep_dive":
        is_sufficient = bool(project_evidence) and decision.sufficient
    else:
        is_sufficient = bool(project_evidence or resume_evidence) and decision.sufficient

    if is_sufficient:
        reason = "存在经安全校验且足以支持回答的当前用户证据"
    elif search_error:
        reason = search_error
    elif not owned_chunks:
        reason = "当前用户知识库为空或没有可检索片段"
    elif best_distance is not None:
        reason = "当前用户候选片段不足以作为可靠事实证据"
    else:
        reason = "没有可用于证明用户经历的可靠证据"

    sources = [*project_evidence, *resume_evidence]
    context_items = [
        *(f"【个人资料】\n{item.content}" for item in profile_evidence),
        *(f"【项目证据】\n{item.content}" for item in project_evidence),
        *(f"【简历证据】\n{item.content}" for item in resume_evidence),
        *(f"【岗位要求】\n{item.content}" for item in job_requirements),
    ]
    return EvidenceOutput(
        is_sufficient=is_sufficient,
        reason=reason,
        best_distance=best_distance,
        distance_metric=DISTANCE_METRIC,
        sources=sources,
        context="\n\n".join(context_items),
        profile_evidence=profile_evidence,
        project_evidence=project_evidence,
        resume_evidence=resume_evidence,
        job_requirements=job_requirements,
    )
