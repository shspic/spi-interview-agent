import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import FileRecord
from app.services.retrieval_confidence import decide_retrieval_evidence
from app.services.retrieval_query_analysis import analyze_query
from app.services.vector_store import DISTANCE_METRIC, search_evidence_candidates


logger = logging.getLogger(__name__)


def search_trusted_evidence(
    db: Session,
    *,
    query: str,
    user_id: int,
    top_k: int,
) -> dict[str, Any]:
    """检索并接受可进入 Agent Prompt 的当前用户事实证据。"""
    records = (
        db.query(FileRecord)
        .filter(FileRecord.user_id == user_id)
        .all()
    )
    records_by_id = {record.file_id: record for record in records}
    trusted_file_names = {
        file_id: record.filename for file_id, record in records_by_id.items()
    }
    analysis = analyze_query(query, trusted_file_names=trusted_file_names)
    if not records:
        return {
            "query": query,
            "top_k": top_k,
            "distance_metric": DISTANCE_METRIC,
            "chunks": [],
            "sufficient": False,
            "partial": False,
            "confidence": 0.0,
            "decision_reason": "rejected_empty_knowledge_base",
            "retrieval_stats": {
                "chroma_query_count": 0,
                "query_variant_count": 0,
                "file_record_batch_query_count": 1,
            },
        }
    candidate_result = search_evidence_candidates(
        query,
        user_id,
        top_k,
        query_variants=analysis.query_variants,
        fusion_strategy="rrf",
    )
    candidates = candidate_result.get("chunks", []) or []
    trusted_chunks = []
    ownership_filtered = 0
    category_filtered = 0
    for chunk in candidates:
        metadata = chunk.get("metadata") or {}
        file_id = metadata.get("file_id")
        chunk_index = metadata.get("chunk_index")
        record = records_by_id.get(file_id)
        if record is None:
            ownership_filtered += 1
            continue
        if record.category not in {"project", "resume"}:
            category_filtered += 1
            continue
        if (
            not isinstance(chunk_index, int)
            or isinstance(chunk_index, bool)
            or chunk_index < 0
        ):
            ownership_filtered += 1
            continue
        trusted_chunks.append(
            {
                "content": chunk.get("content"),
                "distance": chunk.get("distance"),
                "metadata": {
                    "user_id": user_id,
                    "file_id": record.file_id,
                    "filename": record.filename,
                    "file_type": record.file_type,
                    "category": record.category,
                    "chunk_index": chunk_index,
                },
            }
        )

    decision = decide_retrieval_evidence(
        query,
        trusted_chunks,
        top_k=top_k,
        high_confidence_distance=settings.evidence_max_distance,
        trusted_file_names=trusted_file_names,
        allowed_categories={"project", "resume"},
        analysis=analysis,
        use_evidence_set=True,
    )
    logger.info(
        "trusted_retrieval_decision user_id=%s sufficient=%s reason=%s "
        "candidate_count=%s accepted_count=%s",
        user_id,
        decision.sufficient,
        decision.decision_reason,
        len(trusted_chunks),
        len(decision.accepted_candidates),
    )
    return {
        "query": query,
        "top_k": top_k,
        "distance_metric": DISTANCE_METRIC,
        "chunks": decision.accepted_candidates,
        "sufficient": decision.sufficient,
        "partial": decision.partial,
        "confidence": decision.confidence,
        "decision_reason": decision.decision_reason,
        "retrieval_stats": {
            **candidate_result.get("retrieval_stats", {}),
            **decision.filtered_counts,
            "ownership_filtered_count": ownership_filtered,
            "trusted_category_filtered_count": category_filtered,
            "file_record_batch_query_count": 1,
            "query_intent": analysis.intent,
            "required_facet_count": len(analysis.required_facets),
            "covered_facet_count": len(
                decision.evidence_set_stats["covered_facets"]
            ),
            "missing_facet_count": len(
                decision.evidence_set_stats["missing_facets"]
            ),
            "independent_source_count": decision.evidence_set_stats[
                "independent_source_count"
            ],
            "project_consistency": decision.evidence_set_stats[
                "project_consistency"
            ],
        },
    }
