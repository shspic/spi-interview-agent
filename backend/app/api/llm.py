from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.input_validation import validate_safe_text
from app.core.security import get_current_admin
from app.db.database import get_db
from app.db.models import User
from app.services.rate_limit_service import enforce_user_rate_limit
from app.services.llm_service import LLMServiceError, chat_completion

router = APIRouter()


class LLMTestRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return validate_safe_text(
            value,
            field_name="测试消息",
            max_chars=settings.max_task_input_chars,
            strip=True,
        )


@router.post(
    "/llm/test",
    summary="测试 DeepSeek 调用",
    description="发送一段文本到 DeepSeek，验证后端是否能正常调用大模型。",
)
def test_llm(
    request: LLMTestRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    enforce_user_rate_limit(db, current_admin.id, "chat_burst")
    try:
        answer = chat_completion(request.message)

        return {
            "success": True,
            "answer": answer,
        }

    except LLMServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
