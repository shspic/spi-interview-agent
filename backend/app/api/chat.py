from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import User
from app.services.chat_service import ChatServiceError, ask_with_rag

router = APIRouter()


class ChatAskRequest(BaseModel):
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
        return ask_with_rag(
            question=request.question,
            user_id=current_user.id,
            db=db,
        )
    except ChatServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
