from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import InterviewRecord, User

router = APIRouter()


def interview_record_to_dict(record: InterviewRecord) -> dict:
    return {
        "session_id": record.session_id,
        "interview_type": record.interview_type,
        "job_description": record.job_description,
        "question_index": record.question_index,
        "question": record.question,
        "user_answer": record.user_answer,
        "score_total": record.score_total,
        "content_relevance": record.content_relevance,
        "personal_match": record.personal_match,
        "technical_accuracy": record.technical_accuracy,
        "structure_score": record.structure_score,
        "risk_control": record.risk_control,
        "main_problems": record.main_problems,
        "suggestions": record.suggestions,
        "reference_answer": record.reference_answer,
        "created_at": record.created_at,
    }


@router.get(
    "/interview-records",
    summary="查看模拟面试记录列表",
    description="查看已经保存的模拟面试评价记录。",
)
def list_interview_records(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    records = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.user_id == current_user.id)
        .order_by(InterviewRecord.id.desc())
        .all()
    )

    return {
        "records": [
            {
                "session_id": record.session_id,
                "interview_type": record.interview_type,
                "question_index": record.question_index,
                "question": record.question,
                "score_total": record.score_total,
                "created_at": record.created_at,
            }
            for record in records
        ]
    }


@router.get(
    "/interview-records/{session_id}",
    summary="查看模拟面试记录详情",
    description="根据 session_id 查看某条模拟面试评价记录的完整内容。",
)
def get_interview_record_detail(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.session_id == session_id,
            InterviewRecord.user_id == current_user.id,
        )
        .first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="模拟面试记录不存在")

    return interview_record_to_dict(record)


@router.delete(
    "/interview-records/{session_id}",
    summary="删除模拟面试记录",
    description="根据 session_id 删除某条模拟面试评价记录。",
)
def delete_interview_record(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.session_id == session_id,
            InterviewRecord.user_id == current_user.id,
        )
        .first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="模拟面试记录不存在")

    db.delete(record)
    db.commit()

    return {
        "success": True,
        "message": "模拟面试记录已删除",
    }
