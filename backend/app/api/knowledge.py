from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import FileRecord
from app.services.document_loader import DocumentLoadError, load_document_text

router = APIRouter()


class PreviewTextRequest(BaseModel):
    file_id: str


@router.post(
    "/knowledge/preview-text",
    summary="预览文档文本",
    description="根据 file_id 读取已上传文件，并返回解析后的文本预览。",
)
def preview_text(
    request: PreviewTextRequest,
    db: Session = Depends(get_db),
):
    record = db.query(FileRecord).filter(FileRecord.file_id == request.file_id).first()

    if record is None:
        raise HTTPException(status_code=404, detail="文件记录不存在")

    try:
        text = load_document_text(record.file_path, record.file_type)
    except DocumentLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    preview = text[:1000]

    return {
        "file_id": record.file_id,
        "filename": record.filename,
        "file_type": record.file_type,
        "text_length": len(text),
        "preview": preview,
    }
