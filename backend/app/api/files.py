from datetime import datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import FileRecord, UploadReservation, User
from app.services.rate_limit_service import enforce_user_rate_limit, hash_identifier
from app.services.upload_security import (
    StagedUpload,
    UploadSecurityError,
    ensure_path_within,
    get_user_upload_dir,
    move_staged_upload,
    release_storage_reservation,
    reserve_user_storage,
    safe_unlink,
    sanitize_display_filename,
    stage_upload,
    validate_idempotency_key,
)
from app.services.vector_store import delete_file_vectors

router = APIRouter()
ALLOWED_CATEGORIES = {"resume", "project", "other"}


def _raise_upload_error(error: UploadSecurityError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"error_code": error.error_code, "message": error.message},
    ) from error


def _record_response(record: FileRecord) -> dict:
    return {
        "file_id": record.file_id,
        "filename": record.filename,
        "file_type": record.file_type,
        "category": record.category,
        "size_bytes": record.size_bytes,
        "status": record.status,
        "created_at": record.created_at,
    }


def _cleanup_staged_files(staged_files: list[StagedUpload], user_dir: Path) -> None:
    for staged in staged_files:
        safe_unlink(staged.temp_path, user_dir)
        safe_unlink(staged.final_path, user_dir)


@router.post("/files/upload")
def upload_file(
    files: list[UploadFile] = File(..., alias="file"),
    category: str = Form(default="other"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.id
    enforce_user_rate_limit(db, user_id, "upload")
    normalized_category = category.strip().lower()
    if normalized_category not in ALLOWED_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "invalid_file_category",
                "message": "文件分类只能是 resume、project 或 other",
            },
        )
    if not files or len(files) > settings.max_upload_files_per_request:
        raise HTTPException(
            status_code=413,
            detail={
                "error_code": "too_many_upload_files",
                "message": (
                    "单次最多上传 "
                    f"{settings.max_upload_files_per_request} 个文件"
                ),
            },
        )

    try:
        normalized_key = validate_idempotency_key(idempotency_key)
    except UploadSecurityError as exc:
        _raise_upload_error(exc)
    if normalized_key is not None and len(files) != 1:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "ambiguous_idempotency_key",
                "message": "多文件上传暂不接受单一 Idempotency-Key",
            },
        )
    key_hash = (
        hash_identifier("upload_idempotency", normalized_key)
        if normalized_key is not None
        else None
    )

    staged_files: list[StagedUpload] = []
    user_dir = get_user_upload_dir(user_id)
    reservation_id = None
    try:
        for upload in files:
            staged_files.append(stage_upload(upload, user_id))

        if key_hash is not None:
            existing = (
                db.query(FileRecord)
                .filter(
                    FileRecord.user_id == user_id,
                    FileRecord.upload_idempotency_key_hash == key_hash,
                )
                .first()
            )
            if existing is not None:
                staged = staged_files[0]
                if (
                    existing.content_sha256 == staged.content_sha256
                    and existing.category == normalized_category
                ):
                    _cleanup_staged_files(staged_files, user_dir)
                    return _record_response(existing)
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error_code": "idempotency_key_conflict",
                        "message": "Idempotency-Key 已用于其他上传内容",
                    },
                )

        total_size = sum(item.size_bytes for item in staged_files)
        reservation_id = reserve_user_storage(db, user_id, total_size)
        for staged in staged_files:
            move_staged_upload(staged)

        now = datetime.now().isoformat(timespec="seconds")
        records = [
            FileRecord(
                user_id=user_id,
                file_id=staged.file_id,
                filename=staged.display_filename,
                file_type=staged.file_type,
                file_path=str(staged.final_path),
                size_bytes=staged.size_bytes,
                content_sha256=staged.content_sha256,
                upload_idempotency_key_hash=key_hash,
                category=normalized_category,
                status="uploaded",
                error_message=None,
                created_at=now,
                updated_at=now,
            )
            for staged in staged_files
        ]
        db.add_all(records)
        response_payloads = [_record_response(record) for record in records]
        db.query(UploadReservation).filter(
            UploadReservation.reservation_id == reservation_id
        ).delete(synchronize_session=False)
        db.commit()
    except UploadSecurityError as exc:
        db.rollback()
        _cleanup_staged_files(staged_files, user_dir)
        release_storage_reservation(db, reservation_id)
        _raise_upload_error(exc)
    except HTTPException:
        db.rollback()
        _cleanup_staged_files(staged_files, user_dir)
        release_storage_reservation(db, reservation_id)
        raise
    except IntegrityError as exc:
        db.rollback()
        _cleanup_staged_files(staged_files, user_dir)
        release_storage_reservation(db, reservation_id)
        if key_hash is not None and len(staged_files) == 1:
            existing = (
                db.query(FileRecord)
                .filter(
                    FileRecord.user_id == user_id,
                    FileRecord.upload_idempotency_key_hash == key_hash,
                )
                .first()
            )
            if (
                existing is not None
                and existing.content_sha256 == staged_files[0].content_sha256
                and existing.category == normalized_category
            ):
                return _record_response(existing)
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "upload_conflict",
                "message": "上传请求发生冲突，请使用相同幂等键重试",
            },
        ) from exc
    except Exception as exc:
        db.rollback()
        _cleanup_staged_files(staged_files, user_dir)
        release_storage_reservation(db, reservation_id)
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "upload_failed",
                "message": "文件上传失败，请稍后重试",
            },
        ) from exc
    finally:
        for upload in files:
            upload.file.close()

    return (
        response_payloads[0]
        if len(response_payloads) == 1
        else {"files": response_payloads}
    )


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
                **_record_response(record),
                "error_message": record.error_message,
                "updated_at": record.updated_at,
            }
            for record in records
        ]
    }


@router.get("/files/{file_id}/download")
def download_file(
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
    try:
        user_dir = get_user_upload_dir(current_user.id, create=False)
        file_path = ensure_path_within(Path(record.file_path), user_dir)
        display_filename = sanitize_display_filename(record.filename)
    except UploadSecurityError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        path=file_path,
        media_type="application/octet-stream",
        filename=display_filename,
        content_disposition_type="attachment",
    )


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
    try:
        user_dir = get_user_upload_dir(current_user.id, create=False)
        file_path = ensure_path_within(Path(record.file_path), user_dir)
    except UploadSecurityError as exc:
        raise HTTPException(status_code=409, detail="文件存储状态异常") from exc

    try:
        delete_file_vectors(current_user.id, record.file_id)
        if file_path.exists():
            file_path.unlink()
        db.delete(record)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="文件删除失败，请稍后重试",
        ) from exc
    return {"success": True, "message": "文件已删除"}
