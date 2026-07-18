import json

from sqlalchemy.orm import Session

from app.agents.schemas import EvidenceItem, EvidenceOutput
from app.core.config import settings
from app.db.models import FileRecord, InterviewSession, TargetJob, UserProfile
from app.services.vector_store import DISTANCE_METRIC, search_similar_chunks


def _load_profile_evidence(
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

    profile_evidence = _load_profile_evidence(db, user_id)
    job_requirements = _load_job_requirements(db, user_id, interview_session)
    search_error = None
    try:
        search_result = search_similar_chunks(
            query=query,
            user_id=user_id,
            top_k=top_k,
        )
        chunks = search_result.get("chunks", []) or []
    except Exception:
        chunks = []
        search_error = "知识库检索暂时不可用"

    distances = [
        float(chunk["distance"])
        for chunk in chunks
        if isinstance(chunk.get("distance"), (int, float))
    ]
    best_distance = min(distances) if distances else None
    file_ids = {
        str((chunk.get("metadata") or {}).get("file_id"))
        for chunk in chunks
        if (chunk.get("metadata") or {}).get("file_id")
    }
    file_records = (
        db.query(FileRecord)
        .filter(
            FileRecord.user_id == user_id,
            FileRecord.file_id.in_(file_ids),
        )
        .all()
        if file_ids
        else []
    )
    file_categories = {record.file_id: record.category for record in file_records}
    selected_projects = set(interview_session.selected_project_file_ids or [])
    project_evidence = []
    resume_evidence = []

    for chunk in chunks:
        distance = chunk.get("distance")
        if not isinstance(distance, (int, float)):
            continue
        if float(distance) > settings.evidence_max_distance:
            continue
        metadata = chunk.get("metadata") or {}
        file_id = str(metadata.get("file_id") or "")
        category = metadata.get("category") or file_categories.get(file_id, "other")
        if category == "project" and selected_projects and file_id not in selected_projects:
            continue
        if category not in {"project", "resume"}:
            continue
        item = EvidenceItem(
            evidence_type=category,
            source_id=file_id,
            filename=metadata.get("filename"),
            content=str(chunk.get("content") or "")[:2000],
            distance=float(distance),
        )
        if category == "project":
            project_evidence.append(item)
        else:
            resume_evidence.append(item)

    if interview_session.mode == "deep_dive":
        is_sufficient = bool(project_evidence)
    else:
        is_sufficient = bool(project_evidence or resume_evidence)

    if is_sufficient:
        reason = "存在距离阈值内的当前用户简历或项目证据"
    elif search_error:
        reason = search_error
    elif not chunks:
        reason = "当前用户知识库为空或没有可检索片段"
    elif best_distance is not None:
        reason = (
            "检索片段相关性不足，最佳平方 L2 距离为 "
            f"{best_distance:.4f}，阈值为 {settings.evidence_max_distance:.4f}"
        )
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
