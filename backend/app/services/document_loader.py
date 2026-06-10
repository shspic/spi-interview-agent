from pathlib import Path

from pypdf import PdfReader


class DocumentLoadError(Exception):
    pass


def load_document_text(file_path: str, file_type: str) -> str:
    path = Path(file_path)

    if not path.exists():
        raise DocumentLoadError("文件不存在")

    normalized_type = file_type.lower().strip(".")

    if normalized_type in {"md", "txt"}:
        return _load_text_file(path)

    if normalized_type == "pdf":
        return _load_pdf_file(path)

    raise DocumentLoadError(f"不支持的文件类型：{file_type}")


def _load_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="gbk")
        except UnicodeDecodeError as exc:
            raise DocumentLoadError("文本文件编码无法识别，请使用 UTF-8 编码") from exc


def _load_pdf_file(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        pages = []

        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)

        return "\n\n".join(pages).strip()
    except Exception as exc:
        raise DocumentLoadError(f"PDF 解析失败：{exc}") from exc