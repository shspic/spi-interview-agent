import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import InterviewRecord
from app.prompts.interview_prompt import (
    build_interview_evaluation_messages,
    build_interview_question_messages,
)
from app.services.llm_service import LLMServiceError, chat_with_messages
from app.services.vector_store import search_similar_chunks


class InterviewServiceError(Exception):
    pass


def _build_context_and_sources(
    query: str,
    user_id: int,
    top_k: int = 8,
) -> tuple[str, list[dict]]:
    try:
        search_result = search_similar_chunks(
            query=query,
            user_id=user_id,
            top_k=top_k,
        )
    except Exception as exc:
        raise InterviewServiceError(f"知识库检索失败：{exc}") from exc

    chunks = search_result.get("chunks", [])

    if not chunks:
        raise InterviewServiceError("当前知识库为空或没有检索到相关内容，请先上传资料并重建知识库索引")

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


def _extract_json_object(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise InterviewServiceError("大模型返回内容不是合法 JSON，无法解析评价结果")

    json_text = text[start : end + 1]

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise InterviewServiceError(f"评价结果 JSON 解析失败：{exc}") from exc


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def generate_interview_question(
    interview_type: str,
    job_description: str,
    question_index: int,
    user_id: int,
) -> dict:
    if not interview_type.strip():
        raise InterviewServiceError("面试类型不能为空")

    if not job_description.strip():
        raise InterviewServiceError("岗位 JD 不能为空")

    query = f"{interview_type}\n{job_description}"
    context, sources = _build_context_and_sources(
        query=query,
        user_id=user_id,
        top_k=8,
    )

    messages = build_interview_question_messages(
        interview_type=interview_type,
        job_description=job_description,
        context=context,
        question_index=question_index,
    )

    try:
        question_text = chat_with_messages(messages)
    except LLMServiceError as exc:
        raise InterviewServiceError(str(exc)) from exc

    return {
        "question": question_text,
        "question_index": question_index,
        "sources": sources,
        "used_local_knowledge": True,
        "used_web_search": False,
        "web_sources": [],
    }


def evaluate_interview_answer(
    interview_type: str,
    job_description: str,
    question_index: int,
    question: str,
    user_answer: str,
    user_id: int,
    db: Session,
) -> dict:
    if not question.strip():
        raise InterviewServiceError("面试问题不能为空")

    if not user_answer.strip():
        raise InterviewServiceError("用户回答不能为空")

    query = f"{interview_type}\n{job_description}\n{question}\n{user_answer}"
    context, sources = _build_context_and_sources(
        query=query,
        user_id=user_id,
        top_k=8,
    )

    messages = build_interview_evaluation_messages(
        interview_type=interview_type,
        job_description=job_description,
        question=question,
        user_answer=user_answer,
        context=context,
    )

    try:
        raw_evaluation = chat_with_messages(messages)
    except LLMServiceError as exc:
        raise InterviewServiceError(str(exc)) from exc

    evaluation = _extract_json_object(raw_evaluation)

    session_id = str(uuid4())

    record = InterviewRecord(
        user_id=user_id,
        session_id=session_id,
        interview_type=interview_type,
        job_description=job_description,
        question_index=question_index,
        question=question,
        user_answer=user_answer,
        score_total=_safe_int(evaluation.get("score_total")),
        content_relevance=_safe_int(evaluation.get("content_relevance")),
        personal_match=_safe_int(evaluation.get("personal_match")),
        technical_accuracy=_safe_int(evaluation.get("technical_accuracy")),
        structure_score=_safe_int(evaluation.get("structure_score")),
        risk_control=_safe_int(evaluation.get("risk_control")),
        main_problems=evaluation.get("main_problems", ""),
        suggestions=evaluation.get("suggestions", ""),
        reference_answer=evaluation.get("reference_answer", ""),
        created_at=datetime.now().isoformat(timespec="seconds"),
    )

    db.add(record)
    db.commit()

    return {
        "session_id": session_id,
        "evaluation": evaluation,
        "sources": sources,
        "used_local_knowledge": True,
        "used_web_search": False,
        "web_sources": [],
    }
