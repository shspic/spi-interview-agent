import pytest

from app.services.evidence_set_selector import select_evidence_set
from app.services.retrieval_confidence import decide_retrieval_evidence
from app.services.retrieval_query_analysis import (
    MAX_QUERY_VARIANTS,
    MAX_SEMANTIC_QUERIES,
    analyze_query,
)
from app.services.vector_store import RRF_K, fuse_candidate_routes


def _chunk(content, distance, file_id, chunk_index=0, *, category="project", user_id=1):
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


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("FastAPI 提供哪些接口", "fact"),
        ("项目是否使用 Redis", "existence"),
        ("项目明确没有 Redis 吗", "negative"),
        ("接口 P95 延迟是多少毫秒", "numeric"),
        ("框架是什么，以及怎样隔离用户", "multi_part"),
        ("文件上传后如何切块并进入向量库", "multi_hop"),
        ("项目甲与项目乙相比有什么区别", "comparison"),
        ("是否有资料证明用户做过 OCR", "evidence_check"),
    ],
)
def test_query_analysis_supports_required_intents(query, intent):
    assert analyze_query(query).intent == intent


def test_query_analysis_extracts_mixed_terms_and_trusted_project_constraints():
    analysis = analyze_query(
        "星舟 multi-tenant vector retrieval 如何用 user_id 隔离",
        trusted_file_names={
            "star": "星舟知识助理-技术架构.md",
            "ink": "墨池票据平台-技术架构.md",
        },
    )
    assert analysis.project_constraints == ("星舟",)
    assert "isolation" in analysis.attribute_terms
    assert "user_id" in analysis.entity_terms


def test_query_analysis_is_stable_and_does_not_mark_plain_technical_fact_as_multihop():
    first = analyze_query("Chroma 的 distance metric 是什么")
    second = analyze_query("Chroma 的 distance metric 是什么")
    assert first == second
    assert first.intent not in {"multi_hop", "multi_part"}


def test_query_variants_are_bounded_unique_and_do_not_inject_unmentioned_jd_terms():
    analysis = analyze_query("星舟怎样隔离不同用户的向量资料")
    assert len(analysis.query_variants) <= MAX_QUERY_VARIANTS
    assert len(set(analysis.query_variants)) == len(analysis.query_variants)
    assert all(len(item.split()) >= 2 for item in analysis.query_variants)
    assert all("kubernetes" not in item.casefold() for item in analysis.query_variants)


def test_query_limits_are_centrally_bounded():
    assert MAX_QUERY_VARIANTS == 2
    assert MAX_SEMANTIC_QUERIES == 3


def test_minimum_distance_fusion_keeps_best_distance_for_same_chunk():
    routes = [
        [_chunk("证据", 0.4, "same"), _chunk("其他", 0.2, "other")],
        [_chunk("证据", 0.1, "same")],
    ]
    fused, stats = fuse_candidate_routes(
        routes,
        strategy="minimum_distance",
        max_candidates=10,
    )
    assert fused[0]["metadata"]["file_id"] == "same"
    assert fused[0]["distance"] == 0.1
    assert len(fused) == 2
    assert stats["merged_candidate_count"] == 2


def test_rrf_calculation_and_tie_breaking_are_stable():
    routes = [
        [_chunk("甲", 0.3, "a"), _chunk("乙", 0.2, "b")],
        [_chunk("乙", 0.25, "b"), _chunk("甲", 0.35, "a")],
    ]
    first, _ = fuse_candidate_routes(routes, strategy="rrf", max_candidates=10)
    second, _ = fuse_candidate_routes(routes, strategy="rrf", max_candidates=10)
    assert [item["metadata"]["file_id"] for item in first] == ["b", "a"]
    assert first == second
    assert first[0]["_fusion_score"] == round(
        1 / (RRF_K + 2) + 1 / (RRF_K + 1),
        9,
    )


def test_fusion_respects_total_candidate_limit():
    routes = [[_chunk(str(index), 0.2, f"f-{index}") for index in range(8)]]
    fused, stats = fuse_candidate_routes(routes, strategy="rrf", max_candidates=3)
    assert len(fused) == 3
    assert stats["fused_candidate_count"] == 3


def test_evidence_set_prefers_complementary_facets_over_duplicate_chunks():
    names = {
        "stack": "星舟知识助理-架构.md",
        "isolation": "星舟知识助理-隔离.md",
        "copy": "星舟知识助理-架构副本.md",
    }
    analysis = analyze_query(
        "星舟的 API framework 是什么，以及怎样隔离用户向量",
        trusted_file_names=names,
    )
    candidates = [
        _chunk("星舟使用 FastAPI 提供接口。", 0.1, "stack"),
        _chunk("星舟使用 FastAPI 提供接口。", 0.11, "copy"),
        _chunk("星舟以 user_id 过滤向量并核验文件所有权。", 0.2, "isolation"),
    ]
    selected, stats = select_evidence_set(
        candidates,
        analysis=analysis,
        top_k=3,
        trusted_file_names=names,
    )
    assert [item["metadata"]["file_id"] for item in selected] == [
        "stack",
        "isolation",
    ]
    assert not stats.missing_facets
    assert stats.duplicate_filtered_count == 1


def test_adjacent_near_duplicate_does_not_replace_independent_same_file_fact():
    names = {"one": "星舟资料链路.md"}
    analysis = analyze_query(
        "星舟如何解析文件以及写入用户向量",
        trusted_file_names=names,
    )
    candidates = [
        _chunk("文件解析后生成文本片段。", 0.1, "one", 0),
        _chunk("解析文件后形成若干文本片段。", 0.11, "one", 1),
        _chunk("向量写入时保存 user_id。", 0.2, "one", 7),
    ]
    selected, _ = select_evidence_set(
        candidates,
        analysis=analysis,
        top_k=3,
        trusted_file_names=names,
    )
    assert [item["metadata"]["chunk_index"] for item in selected] == [0, 7]


def test_project_constraint_filters_similar_project_pollution():
    names = {
        "star": "星舟知识助理-架构.md",
        "ink": "墨池票据平台-架构.md",
    }
    analysis = analyze_query("星舟使用什么框架", trusted_file_names=names)
    selected, stats = select_evidence_set(
        [
            _chunk("墨池使用 FastAPI。", 0.05, "ink"),
            _chunk("星舟使用 FastAPI。", 0.2, "star"),
        ],
        analysis=analysis,
        top_k=2,
        trusted_file_names=names,
    )
    assert [item["metadata"]["file_id"] for item in selected] == ["star"]
    assert stats.project_filtered_count == 1


def test_project_name_mentioned_only_in_another_project_body_is_not_trusted_identity():
    names = {
        "snow": "雪原备忘录-说明.md",
        "overview": "通用项目周报.md",
    }
    analysis = analyze_query("雪原部署在哪里", trusted_file_names=names)
    selected, stats = select_evidence_set(
        [
            _chunk("周报提到了雪原，但没有该项目部署事实。", 0.1, "overview"),
            _chunk("雪原部署在本地开发机。", 0.2, "snow"),
        ],
        analysis=analysis,
        top_k=2,
        trusted_file_names=names,
    )
    assert [item["metadata"]["file_id"] for item in selected] == ["snow"]
    assert stats.project_filtered_count == 1


def _decide(query, chunks, names):
    analysis = analyze_query(query, trusted_file_names=names)
    return decide_retrieval_evidence(
        query,
        chunks,
        top_k=3,
        high_confidence_distance=0.8,
        trusted_file_names=names,
        allowed_categories={"project", "resume"},
        analysis=analysis,
    )


def test_multi_part_missing_facet_is_partial_and_insufficient():
    names = {"stack": "星舟知识助理-架构.md"}
    decision = _decide(
        "星舟的 API framework 是什么，以及怎样隔离用户向量",
        [_chunk("星舟使用 FastAPI 提供接口。", 0.2, "stack")],
        names,
    )
    assert decision.partial is True
    assert decision.sufficient is False
    assert decision.decision_reason == "rejected_missing_facets"


def test_multi_hop_complete_facets_are_sufficient():
    names = {
        "parse": "星舟资料导入.md",
        "embed": "星舟文本向量.md",
        "store": "星舟用户索引.md",
    }
    decision = _decide(
        "星舟文件上传后如何解析、切块 embedding 并写入隔离向量库？",
        [
            _chunk("上传文件先校验归属并解析正文。", 0.2, "parse"),
            _chunk("文本切块后由 BGE 生成 embedding。", 0.25, "embed"),
            _chunk("向量写入 Chroma 时附带 user_id。", 0.3, "store"),
        ],
        names,
    )
    assert decision.sufficient is True
    assert decision.partial is False
    assert len(decision.evidence_set_stats["covered_facets"]) == 3


def test_unknown_property_is_not_converted_to_explicit_negative():
    names = {"release": "松塔发布手册.md"}
    decision = _decide(
        "松塔部署在哪个云平台？",
        [_chunk("发布手册未指出任何云平台。", 0.2, "release")],
        names,
    )
    assert decision.sufficient is False
    assert decision.accepted_candidates == []
    assert decision.candidate_decisions[0].reason == "rejected_missing_information"


def test_only_jd_or_hard_rejected_candidate_cannot_supply_fact():
    names = {"jd": "岗位JD.md", "far": "星舟项目.md"}
    decision = _decide(
        "用户是否做过 Kubernetes",
        [
            _chunk("岗位要求 Kubernetes。", 0.1, "jd", category="other"),
            _chunk("用户做过 Kubernetes。", 1.16, "far"),
        ],
        names,
    )
    assert decision.sufficient is False
    assert decision.accepted_candidates == []


def test_specific_message_broker_cannot_be_replaced_by_negative_for_another_broker():
    names = {"choice": "晴川组件边界.md"}
    decision = _decide(
        "晴川是否使用 NATS",
        [_chunk("晴川明确未接入 RabbitMQ。", 0.2, "choice")],
        names,
    )
    assert decision.sufficient is False
    assert decision.candidate_decisions[0].reason == "rejected_specific_technical_mismatch"


def test_generic_message_queue_negative_can_answer_specific_broker_existence():
    names = {"choice": "星舟技术取舍.md"}
    decision = _decide(
        "星舟是否使用 Kafka",
        [_chunk("星舟明确没有使用任何消息队列。", 0.2, "choice")],
        names,
    )
    assert decision.sufficient is True
