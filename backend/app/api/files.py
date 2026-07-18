from datetime import datetime
from pathlib import Path
from uuid import uuid4
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import FileRecord, User
from app.services.vector_store import delete_file_vectors

router = APIRouter()

ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf"}
ALLOWED_CATEGORIES = {"resume", "project", "other"}


def get_upload_dir(user_id: int) -> Path:
    upload_dir = Path(settings.upload_dir)

    if not upload_dir.is_absolute():
        backend_dir = Path(__file__).resolve().parents[2]
        upload_dir = backend_dir / upload_dir

    user_upload_dir = upload_dir / str(user_id)
    user_upload_dir.mkdir(parents=True, exist_ok=True)
    return user_upload_dir


@router.post("/files/upload")
def upload_file(
    file: UploadFile = File(...),
    category: str = Form(default="other"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    normalized_category = category.strip().lower()

    if normalized_category not in ALLOWED_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail="文件分类只能是 resume、project 或 other",
        )

    original_filename = Path(file.filename or "").name
    suffix = Path(original_filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="只支持上传 .md / .txt / .pdf 文件",
        )

    file_id = str(uuid4())
    saved_filename = f"{file_id}{suffix}"
    upload_dir = get_upload_dir(current_user.id)
    file_path = upload_dir / saved_filename

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"文件保存失败：{exc}",
        ) from exc

    now = datetime.now().isoformat(timespec="seconds")

    record = FileRecord(
        user_id=current_user.id,
        file_id=file_id,
        filename=original_filename,
        file_type=suffix.lstrip("."),
        file_path=str(file_path),
        category=normalized_category,
        status="uploaded",
        error_message=None,
        created_at=now,
        updated_at=now,
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "file_id": record.file_id,
        "filename": record.filename,
        "file_type": record.file_type,
        "category": record.category,
        "status": record.status,
        "created_at": record.created_at,
    }


@router.get("/files")
def list_files(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    records = (
        db.query(FileRecord)
        .filter(FileRecord.user_id == current_user.id)
        .order_by(FileRecord.id.desc())
        .all()
    )

    return {
        "files": [
            {
                "file_id": record.file_id,
                "filename": record.filename,
                "file_type": record.file_type,
                "category": record.category or "other",
                "status": record.status,
                "error_message": record.error_message,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
            for record in records
        ]
    }


@router.delete("/files/{file_id}")
def delete_file(
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = (
        db.query(FileRecord)
        .filter(
            FileRecord.file_id == file_id,
            FileRecord.user_id == current_user.id,
        )
        .first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="文件不存在")

    file_path = Path(record.file_path)

    try:
        delete_file_vectors(current_user.id, record.file_id)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="文件向量删除失败，请稍后重试",
        ) from exc

    if file_path.exists():
        try:
            file_path.unlink()
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail="文件删除失败，请稍后重试",
            ) from exc

    db.delete(record)
    db.commit()

    return {
        "success": True,
        "message": "文件已删除",
    }
