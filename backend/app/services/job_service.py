import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import HistoryRecord
from app.prompts.job_analysis_prompt import build_job_analysis_messages
from app.services.llm_service import LLMServiceError, chat_with_messages
from app.services.vector_store import search_similar_chunks


class JobServiceError(Exception):
    pass


def analyze_job(job_description: str, db: Session) -> dict:
    if not job_description.strip():
        raise JobServiceError("岗位 JD 不能为空")

    try:
        search_result = search_similar_chunks(query=job_description, top_k=8)
    except Exception as exc:
        raise JobServiceError(f"知识库检索失败：{exc}") from exc

    chunks = search_result.get("chunks", [])

    if not chunks:
        raise JobServiceError("当前知识库为空或没有检索到相关内容，请先上传资料并重建知识库索引")

    context_parts = []
    sources = []

    for index, chunk in enumerate(chunks, start=1):
        content = chunk.get("content", "")
        metadata = chunk.get("metadata", {}) or {}

        filename = metadata.get("filename", "未知文件")
        chunk_index = metadata.get("chunk_index", "")

        context_parts.append(
            f"【片段 {index}｜来源：{filename}｜chunk：{chunk_index}】\n{content}"
        )

        sources.append(
            {
                "filename": filename,
                "file_id": metadata.get("file_id"),
                "file_type": metadata.get("file_type"),
                "chunk_index": chunk_index,
                "distance": chunk.get("distance"),
            }
        )

    context = "\n\n".join(context_parts)
    messages = build_job_analysis_messages(
        job_description=job_description,
        context=context,
    )

    try:
        analysis = chat_with_messages(messages)
    except LLMServiceError as exc:
        raise JobServiceError(str(exc)) from exc

    record = HistoryRecord(
        record_id=str(uuid4()),
        mode="job_analysis",
        user_input=job_description,
        ai_output=analysis,
        sources=json.dumps(sources, ensure_ascii=False),
        used_web_search=0,
        web_sources=json.dumps([], ensure_ascii=False),
        created_at=datetime.now().isoformat(timespec="seconds"),
    )

    db.add(record)
    db.commit()

    return {
        "analysis": analysis,
        "sources": sources,
        "used_local_knowledge": True,
        "used_web_search": False,
        "web_sources": [],
        "history_record_id": record.record_id,
    }