from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.config import settings
from app.core.input_validation import validate_safe_text
from app.db.database import get_db
from app.db.models import User
from app.services.agent_service import AgentServiceError, ask_agent

router = APIRouter()


class AgentAskRequest(BaseModel):
    question: str
    mode: Literal["auto", "local", "web", "hybrid"] = "auto"
    top_k: int = Field(default=5, ge=1, le=10)
    max_web_results: int = Field(default=5, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        return validate_safe_text(
            value,
            field_name="任务描述",
            max_chars=settings.max_task_input_chars,
            strip=True,
        )


@router.post(
    "/agent/ask",
    summary="LangGraph Agent 问答",
    description="基于 LangGraph 的 Agent 接口，可在本地知识库、联网搜索、混合模式之间进行路由。",
)
def ask_agent_api(
    request: AgentAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return ask_agent(
            question=request.question,
            user_id=current_user.id,
            mode=request.mode,
            top_k=request.top_k,
            max_web_results=request.max_web_results,
            db=db,
        )
    except AgentServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
