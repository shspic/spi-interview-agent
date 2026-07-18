from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import FileRecord, User
from app.services.document_loader import DocumentLoadError, load_document_text
from app.services.text_splitter import split_text

from app.services.vector_store import (
    get_vector_store_status,
    rebuild_vector_store,
    search_similar_chunks,
)

router = APIRouter()


class PreviewTextRequest(BaseModel):
    file_id: str

class PreviewChunksRequest(BaseModel):
    file_id: str
    chunk_size: int = 800
    chunk_overlap: int = 120

class SearchKnowledgeRequest(BaseModel):
    query: str
    top_k: int = 5

@router.post(
    "/knowledge/preview-text",
    summary="预览文档文本",
    description="根据 file_id 读取已上传文件，并返回解析后的文本预览。",
)
def preview_text(
    request: PreviewTextRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = (
        db.query(FileRecord)
        .filter(
            FileRecord.file_id == request.file_id,
            FileRecord.user_id == current_user.id,
        )
        .first()
    )

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


@router.post(
    "/knowledge/preview-chunks",
    summary="预览文档切分结果",
    description="根据 file_id 读取已上传文件，解析文本并切分为 chunks，返回前 5 个 chunk 预览。",
)
def preview_chunks(
    request: PreviewChunksRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = (
        db.query(FileRecord)
        .filter(
            FileRecord.file_id == request.file_id,
            FileRecord.user_id == current_user.id,
        )
        .first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="文件记录不存在")

    try:
        text = load_document_text(record.file_path, record.file_type)
        chunks = split_text(
            text=text,
            metadata={
                "user_id": current_user.id,
                "file_id": record.file_id,
                "filename": record.filename,
                "file_type": record.file_type,
            },
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap,
        )
    except DocumentLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "file_id": record.file_id,
        "filename": record.filename,
        "file_type": record.file_type,
        "text_length": len(text),
        "chunk_count": len(chunks),
        "chunks": [
            {
                "chunk_index": chunk.metadata["chunk_index"],
                "content": chunk.content,
                "metadata": chunk.metadata,
            }
            for chunk in chunks[:5]
        ],
    }


@router.post(
    "/knowledge/rebuild",
    summary="重建知识库索引",
    description="读取所有已上传文件，解析文本、切分 chunks、生成向量，并写入 ChromaDB。",
)
def rebuild_knowledge(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return rebuild_vector_store(db, current_user.id)


@router.get(
    "/knowledge/status",
    summary="查看知识库状态",
    description="查看已索引文件数量、失败文件数量和 ChromaDB 中的 chunk 数量。",
)
def knowledge_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_vector_store_status(db, current_user.id)


@router.post(
    "/knowledge/search",
    summary="检索知识库",
    description="根据用户输入的问题，从 ChromaDB 中检索最相似的文本片段。",
)
def search_knowledge(
    request: SearchKnowledgeRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        return search_similar_chunks(
            query=request.query,
            user_id=current_user.id,
            top_k=request.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
