import json
from datetime import datetime
from typing import Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.db.models import HistoryRecord
from app.prompts.agent_prompt import (
    build_agent_answer_messages,
    build_agent_router_messages,
)
from app.services.llm_service import LLMServiceError, chat_with_messages
from app.services.vector_store import search_similar_chunks
from app.services.web_search_service import WebSearchServiceError, search_web


AgentMode = Literal["auto", "local", "web", "hybrid"]
AgentRoute = Literal["local", "web", "hybrid"]


class AgentServiceError(Exception):
    pass


class AgentState(TypedDict, total=False):
    question: str
    user_id: int
    mode: AgentMode
    route: AgentRoute
    route_reason: str
    top_k: int
    max_web_results: int

    local_context: str
    local_sources: list[dict]

    web_context: str
    web_sources: list[dict]

    answer: str
    execution_steps: list[str]


WEB_INTENT_KEYWORDS = [
    "最新",
    "当前",
    "现在",
    "趋势",
    "市场",
    "招聘",
    "岗位",
    "JD",
    "要求",
    "联网",
    "搜索",
    "新闻",
    "2025",
    "2026",
]


def _append_step(state: AgentState, step: str) -> list[str]:
    execution_steps = state.get("execution_steps", []) or []
    next_index = len(execution_steps) + 1
    return execution_steps + [f"{next_index}. {step}"]


def _build_local_context_and_sources(chunks: list[dict]) -> tuple[str, list[dict]]:
    context_parts = []
    sources = []

    for index, chunk in enumerate(chunks, start=1):
        content = chunk.get("content", "")
        metadata = chunk.get("metadata", {}) or {}

        filename = metadata.get("filename", "未知文件")
        chunk_index = metadata.get("chunk_index", "")

        context_parts.append(
            f"【本地片段 {index}｜来源：{filename}｜chunk：{chunk_index}】\n{content}"
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


def _build_web_context_and_sources(question: str, max_results: int) -> tuple[str, list[dict]]:
    try:
        web_result = search_web(
            query=question,
            max_results=max_results,
            search_depth="basic",
            topic="general",
            include_answer=True,
            include_raw_content=False,
        )
    except WebSearchServiceError as exc:
        raise AgentServiceError(str(exc)) from exc

    answer = web_result.get("answer", "")
    results = web_result.get("results", []) or []

    context_parts = []

    if answer:
        context_parts.append(f"【联网摘要】\n{answer}")

    web_sources = []

    for index, result in enumerate(results, start=1):
        title = result.get("title", "")
        url = result.get("url", "")
        content = result.get("content", "")
        score = result.get("score")
        published_date = result.get("published_date")

        context_parts.append(
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

    return "\n\n".join(context_parts), web_sources


def _extract_json_object(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise AgentServiceError("LLM Router 返回内容不是合法 JSON")

    json_text = text[start : end + 1]

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise AgentServiceError(f"LLM Router JSON 解析失败：{exc}") from exc


def _fallback_route(question: str) -> tuple[AgentRoute, str]:
    should_use_web = any(keyword in question for keyword in WEB_INTENT_KEYWORDS)

    if should_use_web:
        return "hybrid", "LLM Router 失败，已根据关键词回退到 hybrid 路由"

    return "local", "LLM Router 失败，已根据关键词回退到 local 路由"


def _select_route_with_llm(question: str) -> tuple[AgentRoute, str]:
    messages = build_agent_router_messages(question)

    try:
        raw_result = chat_with_messages(messages)
        parsed = _extract_json_object(raw_result)
    except (LLMServiceError, AgentServiceError):
        return _fallback_route(question)

    route = parsed.get("route", "local")
    reason = parsed.get("reason", "")

    if route not in ["local", "web", "hybrid"]:
        return _fallback_route(question)

    return route, reason or "LLM Router 已完成路由判断"


def select_route_node(state: AgentState) -> dict:
    question = state.get("question", "")
    mode = state.get("mode", "auto")

    if mode in ["local", "web", "hybrid"]:
        route = mode
        reason = f"用户手动选择 {mode} 模式"
    else:
        route, reason = _select_route_with_llm(question)

    return {
        "route": route,
        "route_reason": reason,
        "execution_steps": [
            f"1. LLM Router 完成路由判断：route={route}，原因：{reason}"
        ],
    }


def retrieve_local_node(state: AgentState) -> dict:
    question = state.get("question", "")
    user_id = state.get("user_id", 0)
    top_k = state.get("top_k", 5)

    try:
        search_result = search_similar_chunks(
            query=question,
            user_id=user_id,
            top_k=top_k,
        )
    except Exception as exc:
        raise AgentServiceError(f"本地知识库检索失败：{exc}") from exc

    chunks = search_result.get("chunks", []) or []
    local_context, local_sources = _build_local_context_and_sources(chunks)

    return {
        "local_context": local_context,
        "local_sources": local_sources,
        "execution_steps": _append_step(
            state,
            f"执行本地知识库检索：返回 {len(local_sources)} 个相关片段",
        ),
    }


def web_search_node(state: AgentState) -> dict:
    question = state.get("question", "")
    max_web_results = state.get("max_web_results", 5)

    web_context, web_sources = _build_web_context_and_sources(
        question=question,
        max_results=max_web_results,
    )

    return {
        "web_context": web_context,
        "web_sources": web_sources,
        "execution_steps": _append_step(
            state,
            f"执行 Tavily 联网搜索：返回 {len(web_sources)} 条联网结果",
        ),
    }


def generate_answer_node(state: AgentState) -> dict:
    question = state.get("question", "")
    route = state.get("route", "local")
    local_context = state.get("local_context", "")
    web_context = state.get("web_context", "")

    if not local_context and not web_context:
        raise AgentServiceError("本地知识库和联网搜索均未提供可用上下文，无法生成可靠回答")

    messages = build_agent_answer_messages(
        question=question,
        route=route,
        local_context=local_context,
        web_context=web_context,
    )

    try:
        answer = chat_with_messages(messages)
    except LLMServiceError as exc:
        raise AgentServiceError(str(exc)) from exc

    return {
        "answer": answer,
        "execution_steps": _append_step(
            state,
            "调用 DeepSeek 生成最终回答",
        ),
    }


def route_after_selection(state: AgentState) -> str:
    route = state.get("route", "local")

    if route == "web":
        return "web_search"

    return "retrieve_local"


def route_after_local_retrieval(state: AgentState) -> str:
    route = state.get("route", "local")

    if route == "hybrid":
        return "web_search"

    return "generate_answer"


def build_agent_graph():
    builder = StateGraph(AgentState)

    builder.add_node("select_route", select_route_node)
    builder.add_node("retrieve_local", retrieve_local_node)
    builder.add_node("web_search", web_search_node)
    builder.add_node("generate_answer", generate_answer_node)

    builder.add_edge(START, "select_route")

    builder.add_conditional_edges(
        "select_route",
        route_after_selection,
        {
            "retrieve_local": "retrieve_local",
            "web_search": "web_search",
        },
    )

    builder.add_conditional_edges(
        "retrieve_local",
        route_after_local_retrieval,
        {
            "web_search": "web_search",
            "generate_answer": "generate_answer",
        },
    )

    builder.add_edge("web_search", "generate_answer")
    builder.add_edge("generate_answer", END)

    return builder.compile()


AGENT_GRAPH = build_agent_graph()


def ask_agent(
    question: str,
    user_id: int,
    db: Session,
    mode: AgentMode = "auto",
    top_k: int = 5,
    max_web_results: int = 5,
) -> dict:
    cleaned_question = question.strip()

    if not cleaned_question:
        raise AgentServiceError("问题不能为空")

    if top_k < 1 or top_k > 10:
        raise AgentServiceError("top_k 必须在 1 到 10 之间")

    if max_web_results < 1 or max_web_results > 10:
        raise AgentServiceError("max_web_results 必须在 1 到 10 之间")

    try:
        result = AGENT_GRAPH.invoke(
            {
                "question": cleaned_question,
                "user_id": user_id,
                "mode": mode,
                "top_k": top_k,
                "max_web_results": max_web_results,
            }
        )
    except AgentServiceError:
        raise
    except Exception as exc:
        raise AgentServiceError(f"LangGraph Agent 执行失败：{exc}") from exc

    route = result.get("route", "local")
    route_reason = result.get("route_reason", "")
    answer = result.get("answer", "")
    local_sources = result.get("local_sources", []) or []
    web_sources = result.get("web_sources", []) or []
    execution_steps = result.get("execution_steps", []) or []

    record = HistoryRecord(
        user_id=user_id,
        record_id=str(uuid4()),
        mode="agent",
        user_input=cleaned_question,
        ai_output=answer,
        sources=json.dumps(local_sources, ensure_ascii=False),
        used_web_search=1 if route in ["web", "hybrid"] else 0,
        web_sources=json.dumps(web_sources, ensure_ascii=False),
        route_reason=route_reason,
        execution_steps=json.dumps(execution_steps, ensure_ascii=False),
        created_at=datetime.now().isoformat(timespec="seconds"),
    )

    db.add(record)
    db.commit()

    return {
        "answer": answer,
        "route": route,
        "route_reason": route_reason,
        "execution_steps": execution_steps,
        "sources": local_sources,
        "web_sources": web_sources,
        "used_local_knowledge": route in ["local", "hybrid"],
        "used_web_search": route in ["web", "hybrid"],
        "history_record_id": record.record_id,
    }
