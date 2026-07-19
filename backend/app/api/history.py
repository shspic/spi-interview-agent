import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import HistoryRecord, User

router = APIRouter()


def parse_json_field(value: str | None):
    if not value:
        return []

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return []


def history_record_to_dict(record: HistoryRecord) -> dict:
    return {
        "record_id": record.record_id,
        "mode": record.mode,
        "user_input": record.user_input,
        "ai_output": record.ai_output,
        "sources": parse_json_field(record.sources),
        "used_web_search": bool(record.used_web_search),
        "web_sources": parse_json_field(record.web_sources),
        "route_reason": record.route_reason,
        "execution_steps": parse_json_field(record.execution_steps),
        "created_at": record.created_at,
    }


@router.get(
    "/history",
    summary="查看历史记录列表",
    description="查看自由问答、岗位分析等历史记录。当前主要用于查看 RAG 自由问答记录。",
)
def list_history(
    mode: str | None = Query(
        default=None,
        max_length=32,
        pattern=r"^[a-z_]*$",
        description="历史类型，例如 chat",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(HistoryRecord).filter(
        HistoryRecord.user_id == current_user.id
    )

    if mode:
        query = query.filter(HistoryRecord.mode == mode)

    records = query.order_by(HistoryRecord.id.desc()).all()

    return {
        "records": [
            {
                "record_id": record.record_id,
                "mode": record.mode,
                "user_input": record.user_input,
                "used_web_search": bool(record.used_web_search),
                "created_at": record.created_at,
            }
            for record in records
        ]
    }


@router.get(
    "/history/{record_id}",
    summary="查看历史记录详情",
    description="根据 record_id 查看某条历史记录的完整内容。",
)
def get_history_detail(
    record_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = (
        db.query(HistoryRecord)
        .filter(
            HistoryRecord.record_id == record_id,
            HistoryRecord.user_id == current_user.id,
        )
        .first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="历史记录不存在")

    return history_record_to_dict(record)


@router.delete(
    "/history/{record_id}",
    summary="删除历史记录",
    description="根据 record_id 删除某条历史记录。",
)
def delete_history(
    record_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = (
        db.query(HistoryRecord)
        .filter(
            HistoryRecord.record_id == record_id,
            HistoryRecord.user_id == current_user.id,
        )
        .first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="历史记录不存在")

    db.delete(record)
    db.commit()

    return {
        "success": True,
        "message": "历史记录已删除",
    }
