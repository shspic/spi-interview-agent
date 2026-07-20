import codecs
import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from time import time
from uuid import uuid4

from fastapi import UploadFile, status
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import FileRecord, UploadReservation, User

ALLOWED_FILE_RULES = {
    ".pdf": {
        "file_type": "pdf",
        "mime_types": {"application/pdf", "application/octet-stream", ""},
    },
    ".txt": {
        "file_type": "txt",
        "mime_types": {"text/plain", "application/octet-stream", ""},
    },
    ".md": {
        "file_type": "md",
        "mime_types": {
            "text/markdown",
            "text/plain",
            "text/x-markdown",
            "application/octet-stream",
            "",
        },
    },
}

DANGEROUS_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".html",
    ".htm",
    ".js",
    ".msi",
    ".ps1",
    ".svg",
    ".zip",
}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
UPLOAD_CHUNK_BYTES = 1024 * 1024
KNOWN_BINARY_SIGNATURES = (
    b"%PDF-",
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    b"PK\x03\x04",
    b"MZ",
)
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class UploadSecurityError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


@dataclass
class StagedUpload:
    file_id: str
    display_filename: str
    file_type: str
    suffix: str
    declared_mime: str
    size_bytes: int
    content_sha256: str
    temp_path: Path
    final_path: Path


def get_upload_root() -> Path:
    upload_root = Path(settings.upload_dir)
    if not upload_root.is_absolute():
        upload_root = Path(__file__).resolve().parents[2] / upload_root
    return upload_root.resolve()


def get_user_upload_dir(user_id: int, *, create: bool = True) -> Path:
    user_dir = (get_upload_root() / str(user_id)).resolve()
    ensure_path_within(user_dir, get_upload_root())
    if create:
        user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def resolve_owned_storage_path(user_id: int, file_path: str | Path) -> Path:
    user_dir = get_user_upload_dir(user_id, create=False)
    return ensure_path_within(Path(file_path), user_dir)


def ensure_path_within(candidate: Path, parent: Path) -> Path:
    resolved_candidate = candidate.resolve()
    resolved_parent = parent.resolve()
    if not resolved_candidate.is_relative_to(resolved_parent):
        raise UploadSecurityError(
            status.HTTP_400_BAD_REQUEST,
            "unsafe_storage_path",
            "文件存储路径无效",
        )
    return resolved_candidate


def sanitize_display_filename(filename: str) -> str:
    normalized = unicodedata.normalize("NFKC", filename or "")
    if not normalized or normalized in {".", ".."}:
        raise UploadSecurityError(415, "invalid_filename", "文件名无效")
    if "/" in normalized or "\\" in normalized or ":" in normalized:
        raise UploadSecurityError(415, "unsafe_filename", "文件名包含不安全路径")
    if PurePosixPath(normalized).is_absolute() or ".." in normalized.split("."):
        raise UploadSecurityError(415, "unsafe_filename", "文件名包含不安全路径")

    cleaned = "".join(
        "_" if unicodedata.category(character) == "Cc" else character
        for character in normalized
    ).rstrip(" .")
    if not cleaned:
        raise UploadSecurityError(415, "invalid_filename", "文件名无效")
    if len(cleaned) > settings.max_filename_chars:
        raise UploadSecurityError(
            415,
            "filename_too_long",
            f"文件名不能超过 {settings.max_filename_chars} 个字符",
        )

    path = Path(cleaned)
    suffix = path.suffix.lower()
    stem_for_windows = path.name[: -len(suffix)] if suffix else path.name
    if stem_for_windows.rstrip(" .").upper() in WINDOWS_RESERVED_NAMES:
        raise UploadSecurityError(415, "reserved_filename", "文件名为系统保留名称")
    if any(item.lower() in DANGEROUS_EXTENSIONS for item in path.suffixes[:-1]):
        raise UploadSecurityError(415, "dangerous_double_extension", "文件名包含危险扩展名")
    return cleaned


def validate_idempotency_key(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(normalized):
        raise UploadSecurityError(
            422,
            "invalid_idempotency_key",
            "Idempotency-Key 格式无效",
        )
    return normalized


def _validate_declared_type(filename: str, content_type: str | None) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    rule = ALLOWED_FILE_RULES.get(suffix)
    if rule is None:
        raise UploadSecurityError(
            415,
            "unsupported_file_type",
            "仅支持 .md、.txt 和 .pdf 文件",
        )
    declared_mime = (content_type or "").split(";", 1)[0].strip().lower()
    if declared_mime not in rule["mime_types"]:
        raise UploadSecurityError(
            415,
            "mime_type_mismatch",
            "文件扩展名与声明类型不匹配",
        )
    return suffix, declared_mime


def stage_upload(upload: UploadFile, user_id: int) -> StagedUpload:
    display_filename = sanitize_display_filename(upload.filename or "")
    suffix, declared_mime = _validate_declared_type(
        display_filename,
        upload.content_type,
    )
    file_id = str(uuid4())
    user_dir = get_user_upload_dir(user_id)
    temp_dir = ensure_path_within(user_dir / ".tmp", user_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = ensure_path_within(temp_dir / f"{uuid4()}.part", temp_dir)
    final_path = ensure_path_within(user_dir / f"{file_id}{suffix}", user_dir)
    max_bytes = settings.max_upload_file_size_mb * 1024 * 1024
    size_bytes = 0
    digest = hashlib.sha256()

    try:
        with temp_path.open("xb") as buffer:
            while True:
                chunk = upload.file.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise UploadSecurityError(
                        413,
                        "file_too_large",
                        f"单个文件不能超过 {settings.max_upload_file_size_mb} MB",
                    )
                digest.update(chunk)
                buffer.write(chunk)
        if size_bytes == 0:
            raise UploadSecurityError(415, "empty_file", "不能上传空文件")
        validate_staged_content(temp_path, suffix)
    except Exception:
        safe_unlink(temp_path, temp_dir)
        raise

    return StagedUpload(
        file_id=file_id,
        display_filename=display_filename,
        file_type=ALLOWED_FILE_RULES[suffix]["file_type"],
        suffix=suffix,
        declared_mime=declared_mime,
        size_bytes=size_bytes,
        content_sha256=digest.hexdigest(),
        temp_path=temp_path,
        final_path=final_path,
    )


def validate_staged_content(path: Path, suffix: str) -> None:
    if suffix == ".pdf":
        _validate_pdf(path)
        return
    _validate_text(path)


def _validate_pdf(path: Path) -> None:
    with path.open("rb") as source:
        if source.read(5) != b"%PDF-":
            raise UploadSecurityError(
                415,
                "invalid_pdf_signature",
                "PDF 文件签名无效",
            )
    try:
        reader = PdfReader(str(path), strict=True)
        if reader.is_encrypted:
            raise UploadSecurityError(
                415,
                "encrypted_pdf_unsupported",
                "暂不支持加密 PDF",
            )
        page_count = len(reader.pages)
    except UploadSecurityError:
        raise
    except (PdfReadError, OSError, ValueError, TypeError) as exc:
        raise UploadSecurityError(
            415,
            "invalid_pdf_structure",
            "PDF 文件损坏或结构无效",
        ) from exc
    if page_count > settings.max_pdf_pages:
        raise UploadSecurityError(
            413,
            "pdf_page_limit_exceeded",
            f"PDF 页数不能超过 {settings.max_pdf_pages} 页",
        )


def _validate_text(path: Path) -> None:
    with path.open("rb") as source:
        sample = source.read(4096)
    if any(sample.startswith(signature) for signature in KNOWN_BINARY_SIGNATURES):
        raise UploadSecurityError(
            415,
            "binary_file_disguised_as_text",
            "文本文件内容与扩展名不匹配",
        )
    if b"\x00" in sample:
        raise UploadSecurityError(415, "text_contains_nul", "文本文件包含 NUL 字节")
    control_bytes = sum(
        1 for value in sample if value < 32 and value not in {9, 10, 13}
    )
    if sample and control_bytes / len(sample) > 0.02:
        raise UploadSecurityError(
            415,
            "binary_file_disguised_as_text",
            "文本文件包含过多二进制控制字节",
        )

    for encoding in ("utf-8-sig", "gb18030"):
        try:
            _validate_text_encoding(path, encoding)
            return
        except UnicodeDecodeError:
            continue
    raise UploadSecurityError(
        415,
        "unsupported_text_encoding",
        "文本文件编码无法识别，请使用 UTF-8 或 GB18030",
    )


def _validate_text_encoding(path: Path, encoding: str) -> None:
    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    current_line_length = 0
    with path.open("rb") as source:
        while True:
            chunk = source.read(UPLOAD_CHUNK_BYTES)
            is_final = not chunk
            decoded = decoder.decode(chunk, final=is_final)
            for character in decoded:
                if character == "\x00":
                    raise UploadSecurityError(
                        415,
                        "text_contains_nul",
                        "文本文件包含 NUL 字节",
                    )
                if character in {"\n", "\r"}:
                    current_line_length = 0
                    continue
                current_line_length += 1
                if current_line_length > settings.max_text_line_chars:
                    raise UploadSecurityError(
                        413,
                        "text_line_too_long",
                        f"文本单行不能超过 {settings.max_text_line_chars} 个字符",
                    )
            if is_final:
                break


def reserve_user_storage(db: Session, user_id: int, size_bytes: int) -> str:
    reservation_id = str(uuid4())
    now_value = int(time())
    expires_at = now_value + 15 * 60
    max_storage_bytes = settings.max_user_storage_mb * 1024 * 1024

    db.commit()
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    else:
        db.query(User.id).filter(User.id == user_id).with_for_update().one()
    try:
        db.query(UploadReservation).filter(
            UploadReservation.expires_at <= now_value
        ).delete(synchronize_session=False)
        used_bytes = (
            db.query(func.coalesce(func.sum(FileRecord.size_bytes), 0))
            .filter(FileRecord.user_id == user_id)
            .scalar()
            or 0
        )
        reserved_bytes = (
            db.query(func.coalesce(func.sum(UploadReservation.size_bytes), 0))
            .filter(
                UploadReservation.user_id == user_id,
                UploadReservation.expires_at > now_value,
            )
            .scalar()
            or 0
        )
        if used_bytes + reserved_bytes + size_bytes > max_storage_bytes:
            db.rollback()
            raise UploadSecurityError(
                413,
                "user_storage_limit_exceeded",
                f"用户总存储不能超过 {settings.max_user_storage_mb} MB",
            )
        db.add(
            UploadReservation(
                reservation_id=reservation_id,
                user_id=user_id,
                size_bytes=size_bytes,
                expires_at=expires_at,
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
        )
        db.commit()
        return reservation_id
    except UploadSecurityError:
        raise
    except Exception:
        db.rollback()
        raise


def release_storage_reservation(db: Session, reservation_id: str | None) -> None:
    if not reservation_id:
        return
    try:
        db.query(UploadReservation).filter(
            UploadReservation.reservation_id == reservation_id
        ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()


def move_staged_upload(staged: StagedUpload) -> None:
    ensure_path_within(staged.temp_path, staged.temp_path.parent)
    ensure_path_within(staged.final_path, staged.final_path.parent)
    os.replace(staged.temp_path, staged.final_path)


def safe_unlink(path: Path, allowed_root: Path) -> None:
    try:
        resolved = ensure_path_within(path, allowed_root)
    except UploadSecurityError:
        return
    try:
        resolved.unlink(missing_ok=True)
    except OSError:
        return
