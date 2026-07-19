import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import HistoryRecord
from app.prompts.chat_prompt import build_rag_chat_messages
from app.services.llm_service import LLMServiceError, chat_with_messages
from app.services.trusted_retrieval_service import search_trusted_evidence


class ChatServiceError(Exception):
    pass


def ask_with_rag(question: str, user_id: int, db: Session) -> dict:
    if not question.strip():
        raise ChatServiceError("问题不能为空")

    try:
        search_result = search_trusted_evidence(
            db,
            query=question,
            user_id=user_id,
            top_k=5,
        )
    except Exception as exc:
        raise ChatServiceError(f"知识库检索失败：{exc}") from exc

    chunks = search_result.get("chunks", [])

    if not chunks:
        raise ChatServiceError("当前知识库为空或没有检索到相关内容，请先上传文件并重建知识库索引")
    if search_result.get("sufficient") is not True:
        raise ChatServiceError("当前资料只能覆盖问题的一部分，无法形成有充分证据支持的完整回答")

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
    messages = build_rag_chat_messages(question=question, context=context)

    try:
        answer = chat_with_messages(messages)
    except LLMServiceError as exc:
        raise ChatServiceError(str(exc)) from exc

    record = HistoryRecord(
        user_id=user_id,
        record_id=str(uuid4()),
        mode="chat",
        user_input=question,
        ai_output=answer,
        sources=json.dumps(sources, ensure_ascii=False),
        used_web_search=0,
        web_sources=json.dumps([], ensure_ascii=False),
        created_at=datetime.now().isoformat(timespec="seconds"),
    )

    db.add(record)
    db.commit()

    return {
        "answer": answer,
        "sources": sources,
        "used_local_knowledge": True,
        "used_web_search": False,
        "web_sources": [],
        "history_record_id": record.record_id,
    }
