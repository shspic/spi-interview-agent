from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import User
from app.services.interview_service import (
    InterviewServiceError,
    evaluate_interview_answer,
    generate_interview_question,
)

router = APIRouter()


class InterviewQuestionRequest(BaseModel):
    interview_type: str = Field(default="AI 应用开发实习面试")
    job_description: str
    question_index: int = Field(default=1, ge=1)


class InterviewEvaluateRequest(BaseModel):
    interview_type: str = Field(default="AI 应用开发实习面试")
    job_description: str
    question_index: int = Field(default=1, ge=1)
    question: str
    user_answer: str


@router.post(
    "/interview/question",
    summary="生成模拟面试题",
    description="结合岗位 JD 和本地知识库，生成一条模拟面试题。",
)
def generate_question_api(
    request: InterviewQuestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return generate_interview_question(
            interview_type=request.interview_type,
            job_description=request.job_description,
            question_index=request.question_index,
            user_id=current_user.id,
            db=db,
        )
    except InterviewServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/interview/evaluate",
    summary="评价模拟面试回答",
    description="结合岗位 JD、本地知识库和用户回答，对模拟面试回答进行评分和改进建议。",
)
def evaluate_answer_api(
    request: InterviewEvaluateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return evaluate_interview_answer(
            interview_type=request.interview_type,
            job_description=request.job_description,
            question_index=request.question_index,
            question=request.question,
            user_answer=request.user_answer,
            user_id=current_user.id,
            db=db,
        )
    except InterviewServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
