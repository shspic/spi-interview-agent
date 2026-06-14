from typing import Literal

from tavily import TavilyClient

from app.core.config import settings


class WebSearchServiceError(Exception):
    pass


SearchDepth = Literal["basic", "advanced", "fast", "ultra-fast"]
SearchTopic = Literal["general", "news", "finance"]


def get_tavily_client() -> TavilyClient:
    if not settings.tavily_api_key:
        raise WebSearchServiceError("缺少 TAVILY_API_KEY，请检查 backend/.env")

    return TavilyClient(api_key=settings.tavily_api_key)


def normalize_tavily_result(result: dict) -> dict:
    return {
        "title": result.get("title", ""),
        "url": result.get("url", ""),
        "content": result.get("content", ""),
        "score": result.get("score"),
        "published_date": result.get("published_date"),
        "raw_content": result.get("raw_content"),
    }


def search_web(
    query: str,
    max_results: int = 5,
    search_depth: SearchDepth = "basic",
    topic: SearchTopic = "general",
    include_answer: bool = True,
    include_raw_content: bool = False,
) -> dict:
    cleaned_query = query.strip()

    if not cleaned_query:
        raise WebSearchServiceError("搜索关键词不能为空")

    if max_results < 1 or max_results > 10:
        raise WebSearchServiceError("max_results 必须在 1 到 10 之间")

    try:
        client = get_tavily_client()

        response = client.search(
            query=cleaned_query,
            max_results=max_results,
            search_depth=search_depth,
            topic=topic,
            include_answer=include_answer,
            include_raw_content=include_raw_content,
            include_images=False,
            include_favicon=True,
        )
    except Exception as exc:
        raise WebSearchServiceError(f"Tavily 搜索失败：{exc}") from exc

    results = response.get("results", []) or []

    normalized_results = [
        normalize_tavily_result(result)
        for result in results
    ]

    return {
        "query": cleaned_query,
        "answer": response.get("answer", ""),
        "results": normalized_results,
        "result_count": len(normalized_results),
    }