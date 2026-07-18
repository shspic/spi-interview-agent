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
DISTANCE_METRIC = "l2_squared"

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


def get_user_filter(user_id: int) -> dict[str, int]:
    return {"user_id": user_id}


def delete_file_vectors(user_id: int, file_id: str) -> None:
    collection = get_collection()
    collection.delete(
        where={
            "$and": [
                {"user_id": user_id},
                {"file_id": file_id},
            ]
        }
    )


def rebuild_vector_store(db: Session, user_id: int) -> dict[str, Any]:
    collection = get_collection()
    collection.delete(where=get_user_filter(user_id))

    records = (
        db.query(FileRecord)
        .filter(FileRecord.user_id == user_id)
        .order_by(FileRecord.id.asc())
        .all()
    )

    indexed_files = 0
    failed_files = 0
    total_chunks = 0

    if not records:
        return {
            "success": True,
            "indexed_files": 0,
            "failed_files": 0,
            "total_chunks": 0,
            "status": "empty",
        }

    model = get_embedding_model()

    for record in records:
        try:
            text = load_document_text(record.file_path, record.file_type)

            chunks = split_text(
                text=text,
                metadata={
                    "user_id": user_id,
                    "file_id": record.file_id,
                    "filename": record.filename,
                    "file_type": record.file_type,
                    "category": record.category or "other",
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
                f"{user_id}_{record.file_id}_{chunk.metadata['chunk_index']}"
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


def search_similar_chunks(
    query: str,
    user_id: int,
    top_k: int = 5,
) -> dict[str, Any]:
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
        where=get_user_filter(user_id),
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
        "distance_metric": DISTANCE_METRIC,
        "chunks": chunks,
    }


def get_vector_store_status(db: Session, user_id: int) -> dict[str, Any]:
    collection = get_collection()

    total_files = db.query(FileRecord).filter(FileRecord.user_id == user_id).count()
    indexed_files = (
        db.query(FileRecord)
        .filter(
            FileRecord.user_id == user_id,
            FileRecord.status == "indexed",
        )
        .count()
    )
    failed_files = (
        db.query(FileRecord)
        .filter(
            FileRecord.user_id == user_id,
            FileRecord.status == "failed",
        )
        .count()
    )

    try:
        vector_data = collection.get(
            where=get_user_filter(user_id),
            include=["metadatas"],
        )
        total_chunks = len(vector_data.get("ids", []) or [])
    except Exception:
        total_chunks = 0

    return {
        "total_files": total_files,
        "indexed_files": indexed_files,
        "failed_files": failed_files,
        "total_chunks": total_chunks,
        "status": "ready" if total_chunks > 0 else "empty",
    }
