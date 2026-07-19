from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import User
from app.services.chat_service import ChatServiceError, ask_with_rag
from app.services.usage_service import (
    UsageServiceError,
    commit_usage,
    release_usage,
    reserve_usage,
)

router = APIRouter()


class ChatAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str


@router.post(
    "/chat/ask",
    summary="RAG 自由问答",
    description="基于本地 ChromaDB 知识库检索相关片段，并调用 DeepSeek 生成面试回答。",
)
def ask_chat(
    request: ChatAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        reservation = reserve_usage(
            db,
            current_user.id,
            "chat",
            f"chat:{uuid4()}",
            related_resource_type="chat_request",
        )
    except UsageServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    try:
        result = ask_with_rag(
            question=request.question,
            user_id=current_user.id,
            db=db,
        )
    except ChatServiceError as exc:
        release_usage(db, reservation, type(exc).__name__)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        release_usage(db, reservation, type(exc).__name__)
        raise
    commit_usage(db, reservation)
    return result
