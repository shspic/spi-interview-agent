import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import HistoryRecord
from app.prompts.job_analysis_prompt import build_job_analysis_messages
from app.services.llm_service import LLMServiceError, chat_with_messages
from app.services.trusted_retrieval_service import search_trusted_evidence
from app.services.web_search_service import WebSearchServiceError, search_web


class JobServiceError(Exception):
    pass


def build_local_context_and_sources(chunks: list[dict]) -> tuple[str, list[dict]]:
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

    return "\n\n".join(context_parts), sources


def build_web_context_and_sources(job_description: str) -> tuple[str, list[dict]]:
    search_query = f"AI 实习 岗位要求 大模型应用 RAG FastAPI Python {job_description[:300]}"

    try:
        web_result = search_web(
            query=search_query,
            max_results=5,
            search_depth="basic",
            topic="general",
            include_answer=True,
            include_raw_content=False,
        )
    except WebSearchServiceError as exc:
        raise JobServiceError(str(exc)) from exc

    answer = web_result.get("answer", "")
    results = web_result.get("results", []) or []

    web_context_parts = []

    if answer:
        web_context_parts.append(f"【联网摘要】\n{answer}")

    web_sources = []

    for index, result in enumerate(results, start=1):
        title = result.get("title", "")
        url = result.get("url", "")
        content = result.get("content", "")
        score = result.get("score")
        published_date = result.get("published_date")

        web_context_parts.append(
            f"【联网结果 {index}】\n标题：{title}\n链接：{url}\n内容：{content}"
        )

        web_sources.append(
            {
                "title": title,
                "url": url,
                "content": content,
                "score": score,
                "published_date": published_date,
            }
        )

    return "\n\n".join(web_context_parts), web_sources


def analyze_job(
    job_description: str,
    user_id: int,
    db: Session,
    use_web_search: bool = False,
) -> dict:
    if not job_description.strip():
        raise JobServiceError("岗位 JD 不能为空")

    try:
        search_result = search_trusted_evidence(
            db,
            query=job_description,
            user_id=user_id,
            top_k=8,
        )
    except Exception as exc:
        raise JobServiceError(f"知识库检索失败：{exc}") from exc

    chunks = search_result.get("chunks", [])

    if not chunks:
        raise JobServiceError("当前知识库为空或没有检索到相关内容，请先上传资料并重建知识库索引")
    if search_result.get("sufficient") is not True:
        raise JobServiceError("当前用户资料不足以完整支持岗位分析")

    context, sources = build_local_context_and_sources(chunks)

    web_context = ""
    web_sources = []

    if use_web_search:
        web_context, web_sources = build_web_context_and_sources(job_description)

    messages = build_job_analysis_messages(
        job_description=job_description,
        context=context,
        web_context=web_context,
        use_web_search=use_web_search,
    )

    try:
        analysis = chat_with_messages(messages)
    except LLMServiceError as exc:
        raise JobServiceError(str(exc)) from exc

    record = HistoryRecord(
        user_id=user_id,
        record_id=str(uuid4()),
        mode="job_analysis",
        user_input=job_description,
        ai_output=analysis,
        sources=json.dumps(sources, ensure_ascii=False),
        used_web_search=1 if use_web_search else 0,
        web_sources=json.dumps(web_sources, ensure_ascii=False),
        created_at=datetime.now().isoformat(timespec="seconds"),
    )

    db.add(record)
    db.commit()

    return {
        "analysis": analysis,
        "sources": sources,
        "used_local_knowledge": True,
        "used_web_search": use_web_search,
        "web_sources": web_sources,
        "history_record_id": record.record_id,
    }
