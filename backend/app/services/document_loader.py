from pathlib import Path

from pypdf import PdfReader

from app.core.config import settings
from app.services.upload_security import (
    UploadSecurityError,
    resolve_owned_storage_path,
    validate_staged_content,
)


class DocumentLoadError(Exception):
    pass


def load_document_text(file_path: str, file_type: str, user_id: int) -> str:
    try:
        path = resolve_owned_storage_path(user_id, file_path)
    except UploadSecurityError as exc:
        raise DocumentLoadError("文件存储路径无效") from exc
    if not path.is_file():
        raise DocumentLoadError("文件不存在")
    try:
        if path.stat().st_size > settings.max_upload_file_size_mb * 1024 * 1024:
            raise DocumentLoadError("文件超过允许的安全大小")
    except OSError as exc:
        raise DocumentLoadError("文件无法安全读取") from exc

    normalized_type = file_type.lower().strip(".")
    if normalized_type in {"md", "txt"}:
        return _load_text_file(path, normalized_type)
    if normalized_type == "pdf":
        return _load_pdf_file(path)
    raise DocumentLoadError("不支持的文件类型")


def _load_text_file(path: Path, file_type: str) -> str:
    try:
        validate_staged_content(path, f".{file_type}")
    except UploadSecurityError as exc:
        raise DocumentLoadError(exc.message) from exc
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="gb18030")
        except UnicodeDecodeError as exc:
            raise DocumentLoadError(
                "文本文件编码无法识别，请使用 UTF-8 或 GB18030"
            ) from exc
    except OSError as exc:
        raise DocumentLoadError("文本文件读取失败") from exc


def _load_pdf_file(path: Path) -> str:
    try:
        validate_staged_content(path, ".pdf")
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(pages).strip()
    except UploadSecurityError as exc:
        raise DocumentLoadError(exc.message) from exc
    except Exception as exc:
        raise DocumentLoadError("PDF 解析失败") from exc
