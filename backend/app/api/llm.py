from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.llm_service import LLMServiceError, chat_completion

router = APIRouter()


class LLMTestRequest(BaseModel):
    message: str


@router.post(
    "/llm/test",
    summary="测试 DeepSeek 调用",
    description="发送一段文本到 DeepSeek，验证后端是否能正常调用大模型。",
)
def test_llm(request: LLMTestRequest):
    try:
        answer = chat_completion(request.message)

        return {
            "success": True,
            "answer": answer,
        }

    except LLMServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc