from sqlalchemy.orm import Session

from app.agents.schemas import EvidenceItem, EvidenceOutput
from app.core.config import settings
from app.db.models import FileRecord, InterviewSession, InterviewTurn, TargetJob
from app.services.evidence_retrieval_service import load_profile_evidence
from app.services.retrieval_confidence import decide_retrieval_evidence
from app.services.vector_store import DISTANCE_METRIC, search_evidence_candidates


# 保留既有测试注入点，避免测试为了内部重命名而改变。
search_similar_chunks = search_evidence_candidates


def retrieve_resume_evidence(
    db: Session,
    user_id: int,
    interview_session: InterviewSession,
    project_files: list[FileRecord],
    target_job: TargetJob | None,
    top_k: int = 20,
) -> EvidenceOutput:
    project_ids = {record.file_id for record in project_files}
    resume_records = (
        db.query(FileRecord)
        .filter(
            FileRecord.user_id == user_id,
            FileRecord.category == "resume",
        )
        .all()
    )
    resume_ids = {record.file_id for record in resume_records}
    file_records = {
        record.file_id: record for record in [*project_files, *resume_records]
    }
    query_parts = [
        "项目背景 核心功能 技术架构 个人职责 难点 解决方案 可证明成果",
        " ".join(record.filename for record in project_files),
        target_job.job_title if target_job is not None else "",
    ]
    search_error = None
    try:
        result = search_similar_chunks(
            query=" ".join(part for part in query_parts if part),
            user_id=user_id,
            top_k=top_k,
        )
        chunks = result.get("chunks", []) or []
    except Exception:
        chunks = []
        search_error = "知识库检索暂时不可用"

    project_evidence = []
    resume_evidence = []
    distances = []
    trusted_chunks = []
    for chunk in chunks:
        distance = chunk.get("distance")
        if not isinstance(distance, (int, float)):
            continue
        distances.append(float(distance))
        metadata = chunk.get("metadata") or {}
        file_id = str(metadata.get("file_id") or "")
        if file_id in project_ids:
            evidence_type = "project"
        elif file_id in resume_ids:
            evidence_type = "resume"
        else:
            continue
        record = file_records[file_id]
        chunk_index = metadata.get("chunk_index")
        if (
            not isinstance(chunk_index, int)
            or isinstance(chunk_index, bool)
            or chunk_index < 0
        ):
            continue
        trusted_chunks.append(
            {
                "content": chunk.get("content"),
                "distance": distance,
                "metadata": {
                    "user_id": user_id,
                    "file_id": file_id,
                    "chunk_index": chunk_index,
                    "category": evidence_type,
                },
            }
        )

    evidence_query = " ".join(part for part in query_parts if part)
    decision = decide_retrieval_evidence(
        evidence_query,
        trusted_chunks,
        top_k=top_k,
        high_confidence_distance=settings.evidence_max_distance,
        trusted_file_names={
            file_id: record.filename for file_id, record in file_records.items()
        },
        allowed_categories={"project", "resume"},
    )
    for chunk in decision.accepted_candidates:
        metadata = chunk.get("metadata") or {}
        file_id = str(metadata.get("file_id") or "")
        evidence_type = str(metadata.get("category") or "")
        record = file_records[file_id]
        item = EvidenceItem(
            evidence_type=evidence_type,
            source_id=_source_id(file_id, metadata.get("chunk_index")),
            filename=record.filename,
            chunk_index=metadata.get("chunk_index"),
            content=str(chunk.get("content") or "")[:2000],
            distance=float(chunk["distance"]),
        )
        _append_unique(
            project_evidence if evidence_type == "project" else resume_evidence,
            item,
        )

    turns = (
        db.query(InterviewTurn)
        .filter(
            InterviewTurn.session_id == interview_session.id,
            InterviewTurn.user_id == user_id,
        )
        .all()
    )
    for turn in turns:
        for raw_item in turn.evidence_sources or []:
            try:
                item = EvidenceItem.model_validate(raw_item)
            except Exception:
                continue
            if item.evidence_type == "project" and _belongs_to_files(
                item.source_id,
                project_ids,
            ):
                _append_unique(project_evidence, item)
            elif item.evidence_type == "resume" and _belongs_to_files(
                item.source_id,
                resume_ids,
            ):
                _append_unique(resume_evidence, item)

    profile_evidence = load_profile_evidence(db, user_id)
    job_requirements = []
    if target_job is not None:
        job_requirements.append(
            EvidenceItem(
                evidence_type="job_requirement",
                source_id=f"target_job:{target_job.id}",
                content=(
                    f"岗位：{target_job.job_title}\n公司：{target_job.company_name}\n"
                    f"JD：{target_job.jd_text[:5000]}"
                ),
            )
        )

    best_distance = min(distances) if distances else None
    # 此处 query 是广泛收集素材的内部检索串，不是要求逐 facet 完整回答的用户问题。
    # 候选仍经过集合选择与事实校验；只要存在当前用户项目证据即可进入 Resume 的受控生成。
    is_sufficient = bool(project_evidence)
    if is_sufficient:
        reason = "存在距离阈值内或面试时已确认的当前用户项目证据"
    elif search_error:
        reason = search_error
    elif not chunks:
        reason = "所选项目没有可检索的知识库片段"
    elif best_distance is not None:
        reason = (
            "项目片段相关性不足，最佳平方 L2 距离为 "
            f"{best_distance:.4f}，阈值为 {settings.evidence_max_distance:.4f}"
        )
    else:
        reason = "没有可靠项目证据"

    sources = [*project_evidence, *resume_evidence]
    return EvidenceOutput(
        is_sufficient=is_sufficient,
        reason=reason,
        best_distance=best_distance,
        distance_metric=DISTANCE_METRIC,
        sources=sources,
        context="\n\n".join(
            [
                *(f"【个人资料】\n{item.content}" for item in profile_evidence),
                *(f"【项目证据】\n{item.content}" for item in project_evidence),
                *(f"【简历证据】\n{item.content}" for item in resume_evidence),
                *(f"【岗位要求】\n{item.content}" for item in job_requirements),
            ]
        ),
        profile_evidence=profile_evidence,
        project_evidence=project_evidence,
        resume_evidence=resume_evidence,
        job_requirements=job_requirements,
    )


def _source_id(file_id: str, chunk_index) -> str:
    return f"{file_id}:{chunk_index}" if chunk_index is not None else file_id


def _belongs_to_files(source_id: str, file_ids: set[str]) -> bool:
    return any(
        source_id == file_id or source_id.startswith(f"{file_id}:")
        for file_id in file_ids
    )


def _append_unique(items: list[EvidenceItem], item: EvidenceItem) -> None:
    if all(existing.source_id != item.source_id for existing in items):
        items.append(item)
