import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services import vector_store
from app.services.retrieval_confidence import decide_retrieval_evidence
from app.services.retrieval_ranking import (
    candidate_pool_size,
    extract_terms,
    rerank_chunks,
)


def _chunk(
    content,
    distance,
    file_id,
    chunk_index=0,
    *,
    user_id=1,
    category="project",
):
    return {
        "content": content,
        "distance": distance,
        "metadata": {
            "user_id": user_id,
            "file_id": file_id,
            "chunk_index": chunk_index,
            "category": category,
        },
    }


def _rank(query, chunks, top_k=3, **kwargs):
    ranked, stats = rerank_chunks(
        query,
        chunks,
        top_k=top_k,
        distance_threshold=0.8,
        **kwargs,
    )
    return [item["metadata"]["file_id"] for item in ranked], stats


class _EmbeddingResult(list):
    def tolist(self):
        return list(self)


class _EmbeddingModel:
    def encode(self, texts, normalize_embeddings=True):
        return _EmbeddingResult([[0.1, 0.2] for _ in texts])


class _Collection:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        user_id = kwargs["where"]["user_id"]
        chunks = [
            item
            for item in self.chunks
            if item["metadata"].get("user_id") == user_id
        ][:kwargs["n_results"]]
        return {
            "documents": [[item["content"] for item in chunks]],
            "metadatas": [[item["metadata"] for item in chunks]],
            "distances": [[item["distance"] for item in chunks]],
        }


def test_candidate_pool_has_a_bounded_size():
    assert candidate_pool_size(1, 3, 20) == 3
    assert candidate_pool_size(3, 3, 20) == 9
    assert candidate_pool_size(10, 3, 20) == 20
    with pytest.raises(ValueError):
        candidate_pool_size(21, 3, 20)
    with pytest.raises(ValueError):
        candidate_pool_size(3, 0, 20)


def test_retrieval_settings_reject_invalid_candidate_configuration():
    with pytest.raises(ValidationError):
        Settings(retrieval_candidate_multiplier=0)
    with pytest.raises(ValidationError):
        Settings(retrieval_max_candidates=101)


def test_search_retrieves_candidates_before_final_top_k(monkeypatch):
    collection = _Collection(
        [
            _chunk("无关内容", 0.1, "noise-1"),
            _chunk("无关内容二", 0.2, "noise-2"),
            _chunk("无关内容三", 0.3, "noise-3"),
            _chunk("BGE Embedding", 0.4, "relevant"),
        ]
    )
    monkeypatch.setattr(vector_store, "get_collection", lambda: collection)
    monkeypatch.setattr(
        vector_store,
        "get_embedding_model",
        lambda: _EmbeddingModel(),
    )

    result = vector_store.search_similar_chunks("BGE Embedding", 1, top_k=3)

    assert collection.calls[0]["n_results"] == 9
    assert len(result["chunks"]) == 3
    assert result["chunks"][0]["metadata"]["file_id"] == "relevant"
    assert result["candidate_k"] == 9


def test_search_returns_available_candidates_and_filters_invalid_metadata(
    monkeypatch,
):
    collection = _Collection(
        [
            _chunk("FastAPI", 0.1, "valid"),
            _chunk("FastAPI", 0.05, "foreign", user_id=2),
        ]
    )
    monkeypatch.setattr(vector_store, "get_collection", lambda: collection)
    monkeypatch.setattr(
        vector_store,
        "get_embedding_model",
        lambda: _EmbeddingModel(),
    )

    result = vector_store.search_similar_chunks("FastAPI", 1, top_k=5)

    assert [item["metadata"]["file_id"] for item in result["chunks"]] == [
        "valid"
    ]
    assert collection.calls[0]["where"] == {"user_id": 1}


def test_vector_distance_remains_primary_without_lexical_difference():
    ranked, _ = _rank(
        "目标词",
        [
            _chunk("普通内容甲", 0.1, "closer"),
            _chunk("普通内容乙", 0.3, "farther"),
        ],
    )
    assert ranked == ["closer", "farther"]


def test_complete_technical_phrase_can_rerank_close_candidate():
    ranked, _ = _rank(
        "FastAPI 向量检索",
        [
            _chunk("FastAPI 通用服务", 0.1, "generic"),
            _chunk("FastAPI 向量检索与来源引用", 0.22, "specific"),
        ],
    )
    assert ranked[0] == "specific"


def test_terms_support_case_unicode_and_chinese_without_spaces():
    assert "fastapi" in extract_terms("ＦａｓｔＡＰＩ")
    assert "向量" in extract_terms("中文无空格向量检索查询")
    ranked, _ = _rank(
        "fastapi中文向量检索",
        [
            _chunk("普通接口", 0.1, "generic"),
            _chunk("FASTAPI 中文向量检索", 0.2, "mixed"),
        ],
    )
    assert ranked[0] == "mixed"


def test_keyword_repetition_and_long_text_do_not_inflate_coverage():
    ranked, _ = _rank(
        "FastAPI 向量检索",
        [
            _chunk(("FastAPI " * 80) + ("普通说明 " * 80), 0.11, "stuffed"),
            _chunk("FastAPI 向量检索", 0.2, "relevant"),
        ],
    )
    assert ranked[0] == "relevant"


def test_trusted_filename_can_break_a_close_semantic_tie():
    ranked, _ = _rank(
        "星河检索项目",
        [
            _chunk("项目说明", 0.2, "generic"),
            _chunk("项目说明", 0.22, "named"),
        ],
        trusted_file_names={"named": "星河检索项目.md"},
    )
    assert ranked[0] == "named"


def test_exact_duplicates_are_removed_with_stable_tie_breaker():
    chunks = [
        _chunk("FastAPI ChromaDB", 0.1, "b"),
        _chunk("FastAPI ChromaDB", 0.1, "a"),
        _chunk("独立证据", 0.2, "c"),
    ]
    first, stats = _rank("FastAPI ChromaDB", chunks)
    second, _ = _rank("FastAPI ChromaDB", chunks)
    assert first == second == ["a", "c"]
    assert stats.duplicate_filtered_count == 1


def test_near_duplicate_penalty_preserves_source_diversity():
    ranked, stats = _rank(
        "FastAPI ChromaDB BGE",
        [
            _chunk("FastAPI ChromaDB BGE 向量检索 来源引用", 0.10, "same", 0),
            _chunk("FastAPI ChromaDB BGE 向量检索 来源引用 说明", 0.11, "same", 1),
            _chunk("FastAPI ChromaDB BGE 架构实现", 0.15, "other", 0),
        ],
    )
    assert ranked[:2] == ["same", "other"]
    assert stats.near_duplicate_penalty_count == 1


def test_independent_chunks_from_same_file_can_both_be_returned():
    chunks = [
        _chunk("FastAPI 接口实现", 0.1, "same", 0),
        _chunk("ChromaDB 向量检索", 0.12, "same", 5),
        _chunk("无关内容", 0.3, "noise", 0),
    ]
    ranked, _ = _rank("FastAPI ChromaDB 向量检索", chunks, top_k=2)
    assert ranked == ["same", "same"]


def test_distance_and_category_filters_run_before_final_selection():
    ranked, stats = _rank(
        "Kubernetes",
        [
            _chunk("Kubernetes", 0.81, "too-far"),
            _chunk("Kubernetes", 0.1, "resume", category="resume"),
            _chunk("项目证据", 0.2, "project", category="project"),
        ],
        allowed_categories={"project"},
    )
    assert ranked == ["project"]
    assert stats.distance_filtered_count == 1
    assert stats.category_filtered_count == 1


def _decide(query, chunks, top_k=3):
    return decide_retrieval_evidence(
        query,
        chunks,
        top_k=top_k,
        high_confidence_distance=0.8,
        allowed_categories={"project", "resume"},
    )


def test_no_reliable_evidence_is_insufficient():
    decision = _decide(
        "项目如何实现 GraphQL federation",
        [_chunk("FastAPI REST 接口", 0.4, "unrelated")],
    )
    assert decision.sufficient is False
    assert decision.accepted_candidates == []
    assert decision.decision_reason == "rejected_no_answer"


def test_requested_number_must_be_supported_by_evidence():
    decision = _decide(
        "接口延迟是否低于 12 毫秒",
        [_chunk("接口延迟经过了测试，但材料没有记录具体数值", 0.3, "missing")],
    )
    assert decision.sufficient is False
    assert decision.candidate_decisions[0].reason == "rejected_numeric_mismatch"


def test_explicit_negative_evidence_can_be_accepted():
    decision = _decide(
        "项目是否使用 Redis",
        [_chunk("当前版本明确未使用 Redis。", 0.9, "negative")],
    )
    assert decision.sufficient is True
    assert decision.candidate_decisions[0].reason == "accepted_borderline_with_support"


def test_keyword_stuffing_cannot_supply_evidence():
    decision = _decide(
        "项目如何实现 GraphQL federation",
        [
            _chunk(
                "GraphQL Redis Kafka Kubernetes FastAPI ChromaDB 技术词索引。",
                0.5,
                "terms",
            )
        ],
    )
    assert decision.sufficient is False
    assert decision.candidate_decisions[0].reason == "rejected_keyword_stuffing"


def test_borderline_candidate_needs_additional_support():
    rejected = _decide(
        "设备异常怎样通知值班人员",
        [_chunk("设备资料概览", 0.9, "weak")],
    )
    accepted = _decide(
        "设备异常怎样通知值班人员",
        [_chunk("设备异常通过告警通知值班人员。", 0.9, "strong")],
    )
    assert rejected.sufficient is False
    assert accepted.sufficient is True


def test_candidate_beyond_hard_boundary_is_always_rejected():
    decision = _decide(
        "FastAPI 接口",
        [_chunk("FastAPI 接口 FastAPI 接口", 1.16, "far")],
    )
    assert decision.sufficient is False


def test_evidence_candidate_pool_expands_at_most_once(monkeypatch):
    collection = _Collection(
        [_chunk(f"项目证据 {index}", 0.4 + index / 100, f"file-{index}") for index in range(30)]
    )
    monkeypatch.setattr(vector_store, "get_collection", lambda: collection)
    monkeypatch.setattr(vector_store, "get_embedding_model", lambda: _EmbeddingModel())
    monkeypatch.setattr(vector_store.settings, "retrieval_candidate_multiplier", 3)
    monkeypatch.setattr(vector_store.settings, "retrieval_max_candidates", 40)

    result = vector_store.search_evidence_candidates("项目证据", 1, top_k=3)

    assert [item["n_results"] for item in collection.calls] == [9, 18]
    assert result["retrieval_stats"]["chroma_query_count"] == 2
    assert result["retrieval_stats"]["adaptive_expanded"] is True


def test_evidence_candidate_pool_does_not_expand_empty_or_short_results(monkeypatch):
    collection = _Collection([])
    monkeypatch.setattr(vector_store, "get_collection", lambda: collection)
    monkeypatch.setattr(vector_store, "get_embedding_model", lambda: _EmbeddingModel())
    monkeypatch.setattr(vector_store.settings, "retrieval_candidate_multiplier", 3)
    monkeypatch.setattr(vector_store.settings, "retrieval_max_candidates", 40)

    result = vector_store.search_evidence_candidates("项目证据", 1, top_k=3)

    assert len(collection.calls) == 1
    assert result["retrieval_stats"]["chroma_query_count"] == 1


def test_multi_query_evidence_search_is_bounded_to_three_chroma_queries(monkeypatch):
    collection = _Collection(
        [_chunk(f"证据 {index}", 0.2 + index / 100, f"file-{index}") for index in range(12)]
    )
    monkeypatch.setattr(vector_store, "get_collection", lambda: collection)
    monkeypatch.setattr(vector_store, "get_embedding_model", lambda: _EmbeddingModel())

    result = vector_store.search_evidence_candidates(
        "原始问题",
        1,
        top_k=3,
        query_variants=("项目 属性", "技术 证据"),
    )

    assert len(collection.calls) == 3
    assert result["retrieval_stats"]["chroma_query_count"] == 3
    assert result["retrieval_stats"]["query_variant_count"] == 2
    assert len(result["chunks"]) <= vector_store.settings.retrieval_max_candidates


def test_multi_query_evidence_search_rejects_too_many_variants(monkeypatch):
    collection = _Collection([])
    monkeypatch.setattr(vector_store, "get_collection", lambda: collection)
    monkeypatch.setattr(vector_store, "get_embedding_model", lambda: _EmbeddingModel())

    with pytest.raises(ValueError, match="变体数量超过上限"):
        vector_store.search_evidence_candidates(
            "原始问题",
            1,
            top_k=3,
            query_variants=("变体 一", "变体 二", "变体 三"),
        )
    assert collection.calls == []


def test_empty_knowledge_result_does_not_run_query_variants(monkeypatch):
    collection = _Collection([])
    monkeypatch.setattr(vector_store, "get_collection", lambda: collection)
    monkeypatch.setattr(vector_store, "get_embedding_model", lambda: _EmbeddingModel())

    result = vector_store.search_evidence_candidates(
        "原始问题",
        1,
        top_k=3,
        query_variants=("项目 属性", "技术 证据"),
    )

    assert len(collection.calls) == 1
    assert result["retrieval_stats"]["chroma_query_count"] == 1
