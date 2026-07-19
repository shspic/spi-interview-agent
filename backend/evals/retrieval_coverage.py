import hashlib
import json
import math
import os
import statistics
import subprocess
import tempfile
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.retrieval_confidence import decide_retrieval_evidence
from app.services.retrieval_query_analysis import analyze_query
from app.services.retrieval_ranking import candidate_pool_size, normalize_text
from app.services.vector_store import fuse_candidate_routes
from evals.retrieval_calibration import (
    MODEL_ID,
    RESULTS_DIR,
    _resolve_cached_snapshot,
    block_network,
    configure_offline_environment,
    model_cache_status,
)


COVERAGE_MANIFEST_PATH = Path(__file__).with_name("coverage_dataset_manifest.json")
COVERAGE_FREEZE_PATH = Path(__file__).with_name("coverage_production_freeze.json")
COVERAGE_DATASET_PATHS = {
    "development": Path(__file__).with_name("coverage_development_cases.json"),
    "validation": Path(__file__).with_name("coverage_validation_cases.json"),
    "holdout": Path(__file__).with_name("coverage_final_holdout_cases.json"),
}
COVERAGE_MANIFEST_KEYS = {
    "development": "coverage_development",
    "validation": "coverage_validation",
    "holdout": "coverage_final_holdout",
}
OLD_DATASET_PATHS = (
    Path(__file__).with_name("retrieval_calibration_cases.json"),
    Path(__file__).with_name("retrieval_validation_cases.json"),
    Path(__file__).with_name("retrieval_holdout_cases.json"),
)
STRATEGY_LABELS = {
    "A": "single_query_current_ranking",
    "B": "facets_multi_query_minimum_distance",
    "C": "facets_multi_query_rrf",
    "D": "facets_multi_query_rrf_evidence_set",
}
FINAL_STRATEGY = "D"
EVALUATION_TOP_K = 5
FACET_TOP_K = 3


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _source_id(chunk: dict[str, Any]) -> str:
    return f"{chunk['file_id']}:{chunk['chunk_index']}"


def _result_source_id(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata") or {}
    return f"{metadata.get('file_id')}:{metadata.get('chunk_index')}"


def _normalized(value: str) -> str:
    return normalize_text(value)


def _validate_dataset(payload: dict[str, Any], dataset_name: str) -> None:
    chunks = payload.get("chunks")
    queries = payload.get("queries")
    chunk_min = 50 if dataset_name == "development" else 45
    if not isinstance(chunks, list) or not chunk_min <= len(chunks) <= 75:
        raise ValueError(f"{dataset_name} chunk 数量不符合 coverage 纪律")
    query_min = 30 if dataset_name == "development" else 25
    if not isinstance(queries, list) or not query_min <= len(queries) <= 40:
        raise ValueError(f"{dataset_name} query 数量不符合 coverage 纪律")
    if len({item.get("user_id") for item in chunks}) < 3:
        raise ValueError(f"{dataset_name} 至少需要三个虚构用户")
    source_users = {}
    for chunk in chunks:
        source_id = _source_id(chunk)
        if source_id in source_users:
            raise ValueError(f"重复 source_id：{source_id}")
        source_users[source_id] = chunk.get("user_id")
    case_ids = set()
    for case in queries:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise ValueError("coverage case id 必须是唯一非空字符串")
        case_ids.add(case_id)
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError(f"coverage query 非法：{case_id}")
        required = case.get("required_facets")
        mapping = case.get("facet_source_ids")
        if not isinstance(required, list) or not required:
            raise ValueError(f"required_facets 非法：{case_id}")
        if not isinstance(mapping, dict) or set(mapping) != set(required):
            raise ValueError(f"facet_source_ids 与 required_facets 不一致：{case_id}")
        relevant = case.get("relevant_source_ids")
        if not isinstance(relevant, list):
            raise ValueError(f"relevant_source_ids 非法：{case_id}")
        referenced = set(relevant)
        for facet in required:
            sources = mapping[facet]
            if not isinstance(sources, list):
                raise ValueError(f"facet source 非法：{case_id}/{facet}")
            referenced.update(sources)
        if not referenced <= set(source_users):
            raise ValueError(f"case 引用了不存在的 source_id：{case_id}")
        if any(source_users[item] != case.get("user_id") for item in referenced):
            raise ValueError(f"case 相关来源不得属于其他用户：{case_id}")
        if not isinstance(case.get("expected_sufficient"), bool):
            raise ValueError(f"expected_sufficient 非法：{case_id}")
        if case.get("expected_answer_state") not in {
            "supported",
            "supported_with_negative",
            "explicit_negative",
            "unknown",
            "partial_unknown",
        }:
            raise ValueError(f"expected_answer_state 非法：{case_id}")


def load_coverage_dataset(
    dataset_name: str,
    *,
    manifest_path: Path = COVERAGE_MANIFEST_PATH,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if dataset_name not in COVERAGE_DATASET_PATHS:
        raise ValueError("未知 coverage 数据集")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["datasets"][COVERAGE_MANIFEST_KEYS[dataset_name]]
    path = COVERAGE_DATASET_PATHS[dataset_name]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry.get("sha256"):
        raise ValueError(f"{dataset_name} coverage 数据集 SHA-256 与 manifest 不一致")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _validate_dataset(payload, dataset_name)
    if len(payload["queries"]) != entry.get("query_count"):
        raise ValueError(f"{dataset_name} query 数量与 manifest 不一致")
    if len(payload["chunks"]) != entry.get("chunk_count"):
        raise ValueError(f"{dataset_name} chunk 数量与 manifest 不一致")
    if len({item["user_id"] for item in payload["chunks"]}) != entry.get("user_count"):
        raise ValueError(f"{dataset_name} 用户数量与 manifest 不一致")
    if entry.get("frozen_before_production_changes") is not True:
        raise ValueError(f"{dataset_name} 未在生产修改前冻结")
    return payload, {**entry, "dataset_name": dataset_name, "sha256": digest}


def verify_dataset_discipline() -> dict[str, Any]:
    query_origins: dict[str, str] = {}
    content_origins: dict[str, str] = {}
    duplicate_pairs = 0
    for dataset_name in COVERAGE_DATASET_PATHS:
        payload, _entry = load_coverage_dataset(dataset_name)
        local_contents = set()
        for case in payload["queries"]:
            key = _normalized(case["query"])
            if key in query_origins:
                raise ValueError("coverage 集合之间存在完全重复 query")
            query_origins[key] = f"{dataset_name}:{case['id']}"
        for chunk in payload["chunks"]:
            key = _normalized(chunk["content"])
            if key in local_contents:
                duplicate_pairs += 1
                continue
            local_contents.add(key)
            if key in content_origins:
                raise ValueError("coverage 集合之间存在完全重复 chunk")
            content_origins[key] = f"{dataset_name}:{_source_id(chunk)}"

    old_queries = set()
    old_contents = set()
    for path in OLD_DATASET_PATHS:
        payload = json.loads(path.read_text(encoding="utf-8"))
        old_queries.update(_normalized(item["query"]) for item in payload["queries"])
        old_contents.update(_normalized(item["content"]) for item in payload["chunks"])
    if set(query_origins) & old_queries:
        raise ValueError("coverage query 与旧集合完全重复")
    if set(content_origins) & old_contents:
        raise ValueError("coverage chunk 与旧集合完全重复")
    return {
        "dataset_count": len(COVERAGE_DATASET_PATHS),
        "query_count": len(query_origins),
        "unique_chunk_count": len(content_origins),
        "intentional_duplicate_pair_count": duplicate_pairs,
    }


def verify_coverage_production_freeze(
    path: Path = COVERAGE_FREEZE_PATH,
    *,
    require_not_completed: bool = False,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("final_holdout_frozen") is not True:
        raise ValueError("coverage 生产检索逻辑尚未冻结")
    if payload.get("network_disabled") is not True:
        raise ValueError("coverage 冻结记录必须禁用网络")
    if require_not_completed and payload.get("formal_run_completed") is True:
        raise ValueError("coverage final holdout 已完成正式运行")
    backend_root = Path(__file__).resolve().parents[1]
    for item in payload.get("production_files", []):
        relative_path = item.get("path")
        expected = item.get("sha256")
        if not isinstance(relative_path, str) or not isinstance(expected, str):
            raise ValueError("coverage 生产冻结文件记录非法")
        target = (backend_root / relative_path).resolve()
        if backend_root.resolve() not in target.parents:
            raise ValueError("coverage 生产冻结路径不得超出 backend")
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError(f"coverage 生产冻结文件已变化：{relative_path}")
    manifest_digest = hashlib.sha256(COVERAGE_MANIFEST_PATH.read_bytes()).hexdigest()
    if manifest_digest != payload.get("dataset_manifest_sha256"):
        raise ValueError("coverage manifest 在生产冻结后发生变化")
    return {
        **payload,
        "freeze_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _percentile(values: list[float], percentage: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil((percentage / 100) * len(ordered)) - 1)
    return round(ordered[index], 6)


def _trusted_records(dataset: dict[str, Any], user_id: int) -> dict[str, dict[str, Any]]:
    return {
        item["file_id"]: item
        for item in dataset["chunks"]
        if item["user_id"] == user_id and item.get("record_exists", True)
    }


def _trusted_chunks(
    chunks: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    user_id: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    trusted = []
    ownership_filtered = 0
    category_filtered = 0
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        record = records.get(str(metadata.get("file_id") or ""))
        if record is None or metadata.get("user_id") != user_id:
            ownership_filtered += 1
            continue
        if record["category"] not in {"project", "resume"}:
            category_filtered += 1
            continue
        trusted.append(
            {
                "content": chunk.get("content"),
                "distance": chunk.get("distance"),
                "metadata": {
                    "user_id": user_id,
                    "file_id": record["file_id"],
                    "filename": record["filename"],
                    "category": record["category"],
                    "chunk_index": metadata.get("chunk_index"),
                },
            }
        )
    return trusted, {
        "ownership_filtered_count": ownership_filtered,
        "trusted_category_filtered_count": category_filtered,
    }


def _chroma_chunks(result: dict[str, Any]) -> list[dict[str, Any]]:
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    return [
        {
            "content": document,
            "metadata": metadata,
            "distance": float(distance),
            "source_id": source_id,
        }
        for source_id, document, metadata, distance in zip(
            ids,
            documents,
            metadatas,
            distances,
        )
    ]


def _covered_expected_facets(case: dict[str, Any], selected_ids: list[str]) -> set[str]:
    selected = set(selected_ids[:FACET_TOP_K])
    return {
        facet
        for facet, sources in case["facet_source_ids"].items()
        if selected & set(sources)
    }


def _selected_redundant_pair_count(chunks: list[dict[str, Any]]) -> tuple[int, int]:
    redundant = 0
    pairs = 0
    for index, first in enumerate(chunks[:FACET_TOP_K]):
        for second in chunks[index + 1:FACET_TOP_K]:
            pairs += 1
            first_text = normalize_text(str(first.get("content") or ""))
            second_text = normalize_text(str(second.get("content") or ""))
            if first_text == second_text:
                redundant += 1
                continue
            ratio = SequenceMatcher(None, first_text, second_text, autojunk=False).ratio()
            first_metadata = first.get("metadata") or {}
            second_metadata = second.get("metadata") or {}
            adjacent = (
                first_metadata.get("file_id") == second_metadata.get("file_id")
                and isinstance(first_metadata.get("chunk_index"), int)
                and isinstance(second_metadata.get("chunk_index"), int)
                and abs(first_metadata["chunk_index"] - second_metadata["chunk_index"]) <= 1
            )
            if ratio >= 0.95 or adjacent and ratio >= 0.62:
                redundant += 1
    return redundant, pairs


def _strategy_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answered = [row for row in rows if row["relevant_ids"]]
    recalls = {}
    for k in (1, 3, 5):
        recalls[k] = statistics.fmean(
            len(set(row["selected_ids"][:k]) & set(row["relevant_ids"]))
            / len(row["relevant_ids"])
            for row in answered
        ) if answered else 0.0
    reciprocal_ranks = []
    for row in answered:
        relevant = set(row["relevant_ids"])
        reciprocal_ranks.append(
            next(
                (1.0 / rank for rank, source_id in enumerate(row["selected_ids"], start=1) if source_id in relevant),
                0.0,
            )
        )
    raw_precision = statistics.fmean(
        len(set(row["selected_ids"][:3]) & set(row["relevant_ids"])) / 3
        for row in answered
    ) if answered else 0.0
    normalized_precision = statistics.fmean(
        len(set(row["selected_ids"][:3]) & set(row["relevant_ids"]))
        / min(3, len(row["relevant_ids"]))
        for row in answered
    ) if answered else 0.0
    expected_insufficient = [row for row in rows if not row["expected_sufficient"]]
    false_accepts = [row for row in expected_insufficient if row["sufficient"]]
    total_relevant = sum(len(row["relevant_ids"]) for row in answered)
    missed_relevant = sum(
        len(set(row["relevant_ids"]) - set(row["selected_ids"]))
        for row in answered
    )
    supported_rows = [row for row in rows if row["expected_sufficient"]]
    supported_facet_count = sum(len(row["required_facets"]) for row in supported_rows)
    covered_facet_count = sum(len(row["covered_expected_facets"]) for row in supported_rows)
    multi_rows = [row for row in supported_rows if len(row["required_facets"]) >= 2]
    complete_rows = [
        row
        for row in multi_rows
        if len(row["covered_expected_facets"]) == len(row["required_facets"])
    ]
    partial_rows = [
        row
        for row in rows
        if 0 < len(row["covered_expected_facets"]) < len(row["required_facets"])
    ]
    partial_complete_errors = [row for row in partial_rows if row["sufficient"]]
    project_rows = [
        row
        for row in rows
        if set(row["tags"]) & {"project", "similar_project", "comparison"}
    ]
    project_correct = [
        row
        for row in project_rows
        if all(
            source_id.split(":", 1)[0] in set(row["expected_project_files"])
            for source_id in row["selected_ids"]
        )
    ]
    negative_rows = [row for row in rows if row["expected_answer_state"] == "explicit_negative"]
    negative_correct = [
        row
        for row in negative_rows
        if row["sufficient"] and set(row["selected_ids"]) & set(row["relevant_ids"])
    ]
    unknown_rows = [
        row
        for row in rows
        if row["expected_answer_state"] in {"unknown", "partial_unknown"}
    ]
    unknown_correct = [row for row in unknown_rows if not row["sufficient"]]
    redundant_pairs = sum(row["redundant_pair_count"] for row in rows)
    selected_pairs = sum(row["selected_pair_count"] for row in rows)
    latencies = [row["latency_ms"] for row in rows]
    fusion_latencies = [row["fusion_latency_ms"] for row in rows]
    selector_latencies = [row["selector_latency_ms"] for row in rows]
    return {
        "recall_at_1": recalls[1],
        "recall_at_3": recalls[3],
        "recall_at_5": recalls[5],
        "raw_precision_at_3": raw_precision,
        "available_relevance_normalized_precision_at_3": normalized_precision,
        "mrr": statistics.fmean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "no_answer_accuracy": (
            sum(not row["sufficient"] for row in expected_insufficient) / len(expected_insufficient)
            if expected_insufficient else 1.0
        ),
        "false_reject_count": missed_relevant,
        "false_reject_rate": missed_relevant / total_relevant if total_relevant else 0.0,
        "false_accept_count": len(false_accepts),
        "false_accept_rate": len(false_accepts) / len(expected_insufficient) if expected_insufficient else 0.0,
        "facet_coverage_at_3": covered_facet_count / supported_facet_count if supported_facet_count else 1.0,
        "complete_evidence_rate": len(complete_rows) / len(multi_rows) if multi_rows else 1.0,
        "partial_as_complete_error_rate": len(partial_complete_errors) / len(partial_rows) if partial_rows else 0.0,
        "project_disambiguation_accuracy": len(project_correct) / len(project_rows) if project_rows else 1.0,
        "explicit_negative_accuracy": len(negative_correct) / len(negative_rows) if negative_rows else 1.0,
        "unknown_vs_negative_accuracy": len(unknown_correct) / len(unknown_rows) if unknown_rows else 1.0,
        "evidence_redundancy_rate": redundant_pairs / selected_pairs if selected_pairs else 0.0,
        "average_query_count": statistics.fmean(row["query_count"] for row in rows),
        "max_query_count": max((row["query_count"] for row in rows), default=0),
        "average_query_variant_count": statistics.fmean(row["query_variant_count"] for row in rows),
        "average_candidate_count": statistics.fmean(row["candidate_count"] for row in rows),
        "candidate_count_p50": _percentile([row["candidate_count"] for row in rows], 50),
        "candidate_count_p95": _percentile([row["candidate_count"] for row in rows], 95),
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
        "fusion_latency_p50_ms": _percentile(fusion_latencies, 50),
        "fusion_latency_p95_ms": _percentile(fusion_latencies, 95),
        "selector_latency_p50_ms": _percentile(selector_latencies, 50),
        "selector_latency_p95_ms": _percentile(selector_latencies, 95),
        "cross_user_leakage_count": sum(row["cross_user_leakage_count"] for row in rows),
        "invalid_source_id_count": sum(row["invalid_source_id_count"] for row in rows),
        "sort_instability_count": sum(row["sort_instability_count"] for row in rows),
        "uncaught_exception_count": sum(row["exception"] is not None for row in rows),
        "ownership_batch_query_count_per_case": 1,
    }


def _target_assessment(metrics: dict[str, Any], *, final_holdout: bool) -> dict[str, Any]:
    checks = {
        "cross_user_leakage_eq_0": metrics["cross_user_leakage_count"] == 0,
        "invalid_source_id_eq_0": metrics["invalid_source_id_count"] == 0,
        "sort_instability_eq_0": metrics["sort_instability_count"] == 0,
        "uncaught_exception_eq_0": metrics["uncaught_exception_count"] == 0,
        "recall_at_3_gte_0_80": metrics["recall_at_3"] >= 0.80,
        "mrr_gte_0_80": metrics["mrr"] >= 0.80,
        "no_answer_accuracy_gte_0_85": metrics["no_answer_accuracy"] >= 0.85,
        "false_reject_rate_lte_0_20": metrics["false_reject_rate"] <= 0.20,
        "false_accept_rate_lte_0_10": metrics["false_accept_rate"] <= 0.10,
        "facet_coverage_at_3_gte_0_85": metrics["facet_coverage_at_3"] >= 0.85,
        "complete_evidence_rate_gte_0_80": metrics["complete_evidence_rate"] >= 0.80,
        "partial_as_complete_lte_0_10": metrics["partial_as_complete_error_rate"] <= 0.10,
        "project_disambiguation_gte_0_90": metrics["project_disambiguation_accuracy"] >= 0.90,
        "explicit_negative_gte_0_90": metrics["explicit_negative_accuracy"] >= 0.90,
        "unknown_vs_negative_gte_0_90": metrics["unknown_vs_negative_accuracy"] >= 0.90,
        "evidence_redundancy_lte_0_10": metrics["evidence_redundancy_rate"] <= 0.10,
    }
    return {
        "evaluated_for_final_holdout": final_holdout,
        "passed": all(checks.values()) if final_holdout else None,
        "checks": checks,
    }


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Coverage Evidence Set 评估报告",
        "",
        f"- 数据集：`{summary['dataset_name']}` / `{summary['dataset_role']}`",
        f"- 数据 SHA-256：`{summary['dataset_sha256']}`",
        f"- query / chunk：{summary['query_count']} / {summary['chunk_count']}",
        f"- 模型：`{summary['model_id']}`，本地缓存：{summary['local_cache_used']}，网络禁用：{summary['network_disabled']}",
        "- 报告不包含完整 query、chunk 或缓存绝对路径。",
        "",
        "## A-D 方案比较",
        "",
        "| 方案 | R@1 | R@3 | R@5 | raw P@3 | normalized P@3 | MRR | No-answer | FR | FA | Facet@3 | Complete | Partial→Complete | Project | Negative | Unknown | Redundancy | Query | Candidates | P50/P95 ms | 退化 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label in ("A", "B", "C", "D"):
        metrics = summary["strategies"][label]["metrics"]
        lines.append(
            "| {label} | {r1:.2%} | {r3:.2%} | {r5:.2%} | {p3:.2%} | {np3:.2%} | "
            "{mrr:.2%} | {na:.2%} | {fr:.2%} | {fa:.2%} | {facet:.2%} | {complete:.2%} | "
            "{partial:.2%} | {project:.2%} | {negative:.2%} | {unknown:.2%} | {redundancy:.2%} | "
            "{queries:.2f} | {candidates:.2f} | {p50:.2f}/{p95:.2f} | {degraded} |".format(
                label=label,
                r1=metrics["recall_at_1"],
                r3=metrics["recall_at_3"],
                r5=metrics["recall_at_5"],
                p3=metrics["raw_precision_at_3"],
                np3=metrics["available_relevance_normalized_precision_at_3"],
                mrr=metrics["mrr"],
                na=metrics["no_answer_accuracy"],
                fr=metrics["false_reject_rate"],
                fa=metrics["false_accept_rate"],
                facet=metrics["facet_coverage_at_3"],
                complete=metrics["complete_evidence_rate"],
                partial=metrics["partial_as_complete_error_rate"],
                project=metrics["project_disambiguation_accuracy"],
                negative=metrics["explicit_negative_accuracy"],
                unknown=metrics["unknown_vs_negative_accuracy"],
                redundancy=metrics["evidence_redundancy_rate"],
                queries=metrics["average_query_count"],
                candidates=metrics["average_candidate_count"],
                p50=metrics["latency_p50_ms"],
                p95=metrics["latency_p95_ms"],
                degraded=len(summary["strategies"][label]["degraded_case_ids"]),
            )
        )
    final = summary["strategies"][FINAL_STRATEGY]["metrics"]
    lines.extend(
        [
            "",
            "## 最终方案 D 的安全与成本",
            "",
            f"- 跨用户泄露：{final['cross_user_leakage_count']}",
            f"- 非法 source_id：{final['invalid_source_id_count']}",
            f"- 排序不稳定：{final['sort_instability_count']}",
            f"- 未捕获异常：{final['uncaught_exception_count']}",
            f"- query 最大次数：{final['max_query_count']}",
            f"- 候选 P50/P95：{final['candidate_count_p50']:.2f} / {final['candidate_count_p95']:.2f}",
            f"- 融合 P50/P95：{final['fusion_latency_p50_ms']:.3f} / {final['fusion_latency_p95_ms']:.3f} ms",
            f"- 集合选择 P50/P95：{final['selector_latency_p50_ms']:.3f} / {final['selector_latency_p95_ms']:.3f} ms",
            "",
            "## 提升与退化",
            "",
        ]
    )
    for label in ("B", "C", "D"):
        lines.append(
            f"- {label} 相比 A：提升 {len(summary['strategies'][label]['improved_case_ids'])} 个，"
            f"退化 {len(summary['strategies'][label]['degraded_case_ids'])} 个。"
        )
    lines.extend(["", "## 目标判定", ""])
    assessment = summary["target_assessment"]
    lines.append(f"- 正式 final holdout：{assessment['evaluated_for_final_holdout']}")
    lines.append(f"- passed：{assessment['passed']}")
    for name, passed in assessment["checks"].items():
        lines.append(f"- {name}：{passed}")
    return "\n".join(lines) + "\n"


def run_coverage_evaluation(
    *,
    dataset_name: str,
    output_base: Path = RESULTS_DIR,
    final_holdout: bool = False,
) -> tuple[dict[str, Any], Path]:
    if dataset_name == "holdout" and not final_holdout:
        raise ValueError("coverage final holdout 只能在生产冻结后正式运行")
    if final_holdout and dataset_name != "holdout":
        raise ValueError("--final-holdout 只能用于 coverage holdout")
    freeze = (
        verify_coverage_production_freeze(require_not_completed=True)
        if final_holdout
        else None
    )
    configure_offline_environment()
    discipline = verify_dataset_discipline()
    dataset, entry = load_coverage_dataset(dataset_name)
    cache = model_cache_status()
    snapshot = _resolve_cached_snapshot()
    if snapshot is None:
        raise RuntimeError("本地 BGE 模型缓存不存在；不会尝试下载")
    started_at = datetime.now().astimezone()
    candidate_k = candidate_pool_size(
        EVALUATION_TOP_K,
        settings.retrieval_candidate_multiplier,
        settings.retrieval_max_candidates,
    )
    with tempfile.TemporaryDirectory(prefix="spi-coverage-eval-") as temp_dir:
        temp_root = Path(temp_dir).resolve()
        chroma_path = temp_root / "chroma"
        with block_network():
            import chromadb
            from chromadb.config import Settings
            from sentence_transformers import SentenceTransformer

            model_started = time.perf_counter()
            model = SentenceTransformer(str(snapshot), local_files_only=True)
            model_load_ms = (time.perf_counter() - model_started) * 1000
            documents = [item["content"] for item in dataset["chunks"]]
            embedding_started = time.perf_counter()
            document_embeddings = model.encode(
                documents,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).tolist()
            document_embedding_ms = (time.perf_counter() - embedding_started) * 1000
            client = chromadb.PersistentClient(
                path=str(chroma_path),
                settings=Settings(anonymized_telemetry=False),
            )
            collection = client.create_collection(
                name=f"coverage_{dataset_name}_{started_at.strftime('%H%M%S%f')}",
            )
            collection.add(
                ids=[_source_id(item) for item in dataset["chunks"]],
                documents=documents,
                metadatas=[
                    {
                        "user_id": item["user_id"],
                        "file_id": item["file_id"],
                        "filename": item["filename"],
                        "category": item["category"],
                        "chunk_index": item["chunk_index"],
                    }
                    for item in dataset["chunks"]
                ],
                embeddings=document_embeddings,
            )
            all_source_ids = {_source_id(item) for item in dataset["chunks"]}
            strategy_rows = {label: [] for label in STRATEGY_LABELS}
            for case in dataset["queries"]:
                records = _trusted_records(dataset, case["user_id"])
                trusted_file_names = {
                    file_id: item["filename"] for file_id, item in records.items()
                }
                analysis = analyze_query(
                    case["query"],
                    trusted_file_names=trusted_file_names,
                )
                routes = [analysis.normalized_query, *analysis.query_variants]
                route_chunks = []
                route_latencies = []
                for route in routes:
                    route_started = time.perf_counter()
                    query_embedding = model.encode(
                        [route],
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    ).tolist()
                    result = collection.query(
                        query_embeddings=query_embedding,
                        n_results=candidate_k,
                        where={"user_id": case["user_id"]},
                        include=["documents", "metadatas", "distances"],
                    )
                    route_latencies.append((time.perf_counter() - route_started) * 1000)
                    chunks = _chroma_chunks(result)
                    route_chunks.append(chunks)
                    if len(route_chunks) == 1 and not chunks:
                        break

                candidate_sets: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]] = {
                    "A": (
                        route_chunks[0] if route_chunks else [],
                        {"fusion_latency_ms": 0.0},
                    )
                }
                minimum, minimum_stats = fuse_candidate_routes(
                    route_chunks,
                    strategy="minimum_distance",
                    max_candidates=settings.retrieval_max_candidates,
                )
                rrf, rrf_stats = fuse_candidate_routes(
                    route_chunks,
                    strategy="rrf",
                    max_candidates=settings.retrieval_max_candidates,
                )
                candidate_sets["B"] = (minimum, minimum_stats)
                candidate_sets["C"] = (rrf, rrf_stats)
                candidate_sets["D"] = (rrf, rrf_stats)

                for label in STRATEGY_LABELS:
                    exception = None
                    decision = None
                    candidates, fusion_stats = candidate_sets[label]
                    trusted, filter_stats = _trusted_chunks(
                        candidates,
                        records,
                        case["user_id"],
                    )
                    decision_started = time.perf_counter()
                    try:
                        decision = decide_retrieval_evidence(
                            case["query"],
                            trusted,
                            top_k=EVALUATION_TOP_K,
                            high_confidence_distance=settings.evidence_max_distance,
                            trusted_file_names=trusted_file_names,
                            allowed_categories={"project", "resume"},
                            analysis=analysis,
                            use_evidence_set=(label == "D"),
                        )
                        repeated = decide_retrieval_evidence(
                            case["query"],
                            trusted,
                            top_k=EVALUATION_TOP_K,
                            high_confidence_distance=settings.evidence_max_distance,
                            trusted_file_names=trusted_file_names,
                            allowed_categories={"project", "resume"},
                            analysis=analysis,
                            use_evidence_set=(label == "D"),
                        )
                    except Exception as exc:
                        exception = type(exc).__name__
                        repeated = None
                    decision_ms = (time.perf_counter() - decision_started) * 1000
                    selected = decision.accepted_candidates if decision else []
                    selected_ids = [_result_source_id(item) for item in selected]
                    repeated_ids = (
                        [_result_source_id(item) for item in repeated.accepted_candidates]
                        if repeated else []
                    )
                    covered = _covered_expected_facets(case, selected_ids)
                    redundant_pairs, selected_pairs = _selected_redundant_pair_count(selected)
                    query_count = 1 if label == "A" else len(route_chunks)
                    query_latency = sum(route_latencies[:query_count])
                    selector_latency = (
                        float(decision.evidence_set_stats.get("selector_latency_ms", 0.0))
                        if decision else 0.0
                    )
                    strategy_rows[label].append(
                        {
                            "case_id": case["id"],
                            "selected_ids": selected_ids,
                            "relevant_ids": list(case["relevant_source_ids"]),
                            "required_facets": list(case["required_facets"]),
                            "covered_expected_facets": sorted(covered),
                            "expected_sufficient": case["expected_sufficient"],
                            "expected_answer_state": case["expected_answer_state"],
                            "expected_project_files": list(case["expected_project_files"]),
                            "tags": list(case["tags"]),
                            "sufficient": bool(decision and decision.sufficient),
                            "partial": bool(decision and decision.partial),
                            "decision_reason": decision.decision_reason if decision else "exception",
                            "query_count": query_count,
                            "query_variant_count": max(0, query_count - 1),
                            "candidate_count": len(trusted),
                            "latency_ms": round(query_latency + decision_ms + float(fusion_stats.get("fusion_latency_ms", 0.0)), 6),
                            "fusion_latency_ms": float(fusion_stats.get("fusion_latency_ms", 0.0)),
                            "selector_latency_ms": selector_latency,
                            "cross_user_leakage_count": sum(
                                (item.get("metadata") or {}).get("user_id") != case["user_id"]
                                for item in selected
                            ),
                            "invalid_source_id_count": sum(source_id not in all_source_ids for source_id in selected_ids),
                            "sort_instability_count": int(
                                decision is not None
                                and repeated is not None
                                and (
                                    selected_ids != repeated_ids
                                    or decision.sufficient != repeated.sufficient
                                )
                            ),
                            "redundant_pair_count": redundant_pairs,
                            "selected_pair_count": selected_pairs,
                            "ownership_filtered_count": filter_stats["ownership_filtered_count"],
                            "category_filtered_count": filter_stats["trusted_category_filtered_count"],
                            "exception": exception,
                            "candidate_decisions": (
                                [item.as_dict() for item in decision.candidate_decisions]
                                if decision else []
                            ),
                        }
                    )

            strategies = {}
            baseline_by_id = {row["case_id"]: row for row in strategy_rows["A"]}
            for label in STRATEGY_LABELS:
                improved = []
                degraded = []
                for row in strategy_rows[label]:
                    baseline = baseline_by_id[row["case_id"]]
                    baseline_hits = len(set(baseline["selected_ids"][:3]) & set(row["relevant_ids"]))
                    current_hits = len(set(row["selected_ids"][:3]) & set(row["relevant_ids"]))
                    baseline_correct = baseline["sufficient"] == baseline["expected_sufficient"]
                    current_correct = row["sufficient"] == row["expected_sufficient"]
                    if current_hits > baseline_hits or current_correct and not baseline_correct:
                        improved.append(row["case_id"])
                    if current_hits < baseline_hits or baseline_correct and not current_correct:
                        degraded.append(row["case_id"])
                strategies[label] = {
                    "name": STRATEGY_LABELS[label],
                    "metrics": _strategy_metrics(strategy_rows[label]),
                    "improved_case_ids": improved,
                    "degraded_case_ids": degraded,
                }

            final_metrics = strategies[FINAL_STRATEGY]["metrics"]
            summary = {
                "status": "completed",
                "run_mode": "real_embedding_coverage",
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now().astimezone().isoformat(),
                "git_commit": _git_commit(),
                "model_id": MODEL_ID,
                "embedding_dimension": 512,
                "normalized_embeddings": True,
                "local_cache_used": bool(cache.get("cache_found")),
                "network_disabled": True,
                "download_attempted": False,
                "dataset_name": dataset_name,
                "dataset_role": dataset.get("dataset_role"),
                "dataset_sha256": entry["sha256"],
                "query_count": len(dataset["queries"]),
                "chunk_count": len(dataset["chunks"]),
                "final_holdout_frozen": final_holdout,
                "production_freeze_sha256": (freeze or {}).get("freeze_sha256"),
                "dataset_discipline": discipline,
                "strategies": strategies,
                "selected_strategy": FINAL_STRATEGY,
                "target_assessment": _target_assessment(final_metrics, final_holdout=final_holdout),
                "performance_ms": {
                    "model_load": round(model_load_ms, 3),
                    "document_embedding": round(document_embedding_ms, 3),
                },
                "isolation": {
                    "temporary_chroma": True,
                    "production_paths_accessed": False,
                    "real_user_data_used": False,
                    "dotenv_loaded": False,
                    "deepseek_called": False,
                    "tavily_called": False,
                    "ownership_batch_query_count_per_case": 1,
                },
            }
            output_dir = output_base / (
                f"retrieval-coverage-{dataset_name}-{started_at.strftime('%Y-%m-%dT%H%M%S-%f')}"
            )
            output_dir.mkdir(parents=True, exist_ok=False)
            (output_dir / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            sanitized_cases = {
                label: [
                    {
                        key: value
                        for key, value in row.items()
                        if key not in {"tags", "expected_project_files"}
                    }
                    for row in rows
                ]
                for label, rows in strategy_rows.items()
            }
            (output_dir / "cases.json").write_text(
                json.dumps(sanitized_cases, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (output_dir / "report.md").write_text(
                _render_report(summary),
                encoding="utf-8",
            )
            if final_holdout:
                (output_dir / "final-holdout-marker.json").write_text(
                    json.dumps(
                        {
                            "final_holdout_frozen": True,
                            "dataset_sha256": entry["sha256"],
                            "production_freeze_sha256": (freeze or {}).get("freeze_sha256"),
                            "status": "completed",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            system = getattr(client, "_system", None)
            if system is not None and hasattr(system, "stop"):
                system.stop()
            return summary, output_dir
