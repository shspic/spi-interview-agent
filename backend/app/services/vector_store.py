from pathlib import Path
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import FileRecord
from app.services.document_loader import load_document_text
from app.services.text_splitter import split_text

COLLECTION_NAME = "personal_knowledge_base"

_embedding_model: SentenceTransformer | None = None
_chroma_client: Any | None = None


def get_backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_backend_path(path_value: str) -> Path:
    path = Path(path_value)

    if path.is_absolute():
        return path

    return get_backend_dir() / path


def get_embedding_model() -> SentenceTransformer:
    global _embedding_model

    if _embedding_model is None:
        _embedding_model = SentenceTransformer(settings.embedding_model_name)

    return _embedding_model


def get_chroma_client() -> chromadb.PersistentClient:
    global _chroma_client

    if _chroma_client is None:
        persist_dir = resolve_backend_path(settings.chroma_persist_dir)
        persist_dir.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=str(persist_dir))

    return _chroma_client


def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(name=COLLECTION_NAME)


def reset_collection():
    client = get_chroma_client()

    try:
        client.delete_collection(name=COLLECTION_NAME)
    except Exception:
        pass

    return client.get_or_create_collection(name=COLLECTION_NAME)


def rebuild_vector_store(db: Session) -> dict[str, Any]:
    collection = reset_collection()
    model = get_embedding_model()

    records = db.query(FileRecord).order_by(FileRecord.id.asc()).all()

    indexed_files = 0
    failed_files = 0
    total_chunks = 0

    for record in records:
        try:
            text = load_document_text(record.file_path, record.file_type)

            chunks = split_text(
                text=text,
                metadata={
                    "file_id": record.file_id,
                    "filename": record.filename,
                    "file_type": record.file_type,
                },
                chunk_size=800,
                chunk_overlap=120,
            )

            if not chunks:
                record.status = "failed"
                record.error_message = "文件内容为空或无法切分"
                failed_files += 1
                continue

            documents = [chunk.content for chunk in chunks]
            metadatas = [chunk.metadata for chunk in chunks]
            ids = [
                f"{record.file_id}_{chunk.metadata['chunk_index']}"
                for chunk in chunks
            ]

            embeddings = model.encode(
                documents,
                normalize_embeddings=True,
            ).tolist()

            collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )

            record.status = "indexed"
            record.error_message = None
            indexed_files += 1
            total_chunks += len(chunks)

        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            failed_files += 1

    db.commit()

    return {
        "success": True,
        "indexed_files": indexed_files,
        "failed_files": failed_files,
        "total_chunks": total_chunks,
        "status": "ready" if total_chunks > 0 else "empty",
    }


def search_similar_chunks(query: str, top_k: int = 5) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("query 不能为空")

    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")

    collection = get_collection()
    model = get_embedding_model()

    query_embedding = model.encode(
        [query],
        normalize_embeddings=True,
    ).tolist()

    result = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    chunks = []

    for index, document in enumerate(documents):
        chunks.append(
            {
                "content": document,
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "distance": distances[index] if index < len(distances) else None,
            }
        )

    return {
        "query": query,
        "top_k": top_k,
        "chunks": chunks,
    }


def get_vector_store_status(db: Session) -> dict[str, Any]:
    collection = get_collection()

    total_files = db.query(FileRecord).count()
    indexed_files = db.query(FileRecord).filter(FileRecord.status == "indexed").count()
    failed_files = db.query(FileRecord).filter(FileRecord.status == "failed").count()

    try:
        total_chunks = collection.count()
    except Exception:
        total_chunks = 0

    return {
        "total_files": total_files,
        "indexed_files": indexed_files,
        "failed_files": failed_files,
        "total_chunks": total_chunks,
        "status": "ready" if total_chunks > 0 else "empty",
    }