from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.web_search_service import WebSearchServiceError, search_web

router = APIRouter()


class WebSearchRequest(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=10)
    search_depth: Literal["basic", "advanced", "fast", "ultra-fast"] = "basic"
    topic: Literal["general", "news", "finance"] = "general"
    include_answer: bool = True
    include_raw_content: bool = False


@router.post(
    "/web-search/test",
    summary="测试 Tavily 联网搜索",
    description="调用 Tavily Search API，返回联网搜索结果。当前接口用于后端联调。",
)
def test_web_search(request: WebSearchRequest):
    try:
        return search_web(
            query=request.query,
            max_results=request.max_results,
            search_depth=request.search_depth,
            topic=request.topic,
            include_answer=request.include_answer,
            include_raw_content=request.include_raw_content,
        )
    except WebSearchServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc