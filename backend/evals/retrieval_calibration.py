import json
import hashlib
import math
import os
import socket
import sqlite3
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.config import RESULTS_DIR
from evals.metrics import mean, reciprocal_rank
from evals.reporters import create_result_dir, write_json


MODEL_ID = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")
DISTANCE_THRESHOLD = float(os.getenv("EVIDENCE_MAX_DISTANCE", "0.8"))
CANDIDATE_MULTIPLIER = int(os.getenv("RETRIEVAL_CANDIDATE_MULTIPLIER", "3"))
MAX_CANDIDATES = int(os.getenv("RETRIEVAL_MAX_CANDIDATES", "40"))
DATASET_PATH = Path(__file__).with_name("retrieval_calibration_cases.json")
VALIDATION_DATASET_PATH = Path(__file__).with_name("retrieval_validation_cases.json")
HOLDOUT_DATASET_PATH = Path(__file__).with_name("retrieval_holdout_cases.json")
DATASET_MANIFEST_PATH = Path(__file__).with_name("retrieval_validation_manifest.json")
PRODUCTION_FREEZE_PATH = Path(__file__).with_name("retrieval_production_freeze.json")
DATASET_PATHS = {
    "development": DATASET_PATH,
    "validation": VALIDATION_DATASET_PATH,
    "holdout": HOLDOUT_DATASET_PATH,
}


def configure_offline_environment() -> None:
    os.environ["SKIP_DOTENV"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    os.environ["DEEPSEEK_API_KEY"] = ""
    os.environ["TAVILY_API_KEY"] = ""


def _resolve_cached_snapshot(model_id: str = MODEL_ID) -> Path | None:
    configure_offline_environment()
    from huggingface_hub import snapshot_download

    try:
        return Path(
            snapshot_download(
                repo_id=model_id,
                local_files_only=True,
            )
        )
    except Exception:
        return None


def model_cache_status(model_id: str = MODEL_ID) -> dict[str, Any]:
    snapshot = _resolve_cached_snapshot(model_id)
    return {
        "model_id": model_id,
        "cache_found": snapshot is not None,
        "offline_loading_allowed": True,
        "network_disabled": True,
        "download_will_be_attempted": False,
        "calibration_runnable": snapshot is not None,
    }


@contextmanager
def block_network():
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked(*args, **kwargs):
        raise RuntimeError("真实 Embedding 校准禁止网络访问")

    socket.socket.connect = blocked
    socket.create_connection = blocked
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create_connection


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_dataset(path: Path = DATASET_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    chunks = payload.get("chunks")
    queries = payload.get("queries")
    if not isinstance(chunks, list) or not 40 <= len(chunks) <= 80:
        raise ValueError("真实校准 chunk 数量必须在 40 到 80 之间")
    if not isinstance(queries, list) or not 25 <= len(queries) <= 40:
        raise ValueError("真实校准 query 数量必须在 25 到 40 之间")
    source_ids = set()
    source_users = {}
    for chunk in chunks:
        source_id = _source_id(chunk)
        if source_id in source_ids:
            raise ValueError(f"重复 source_id：{source_id}")
        source_ids.add(source_id)
        source_users[source_id] = chunk.get("user_id")
    case_ids = set()
    for case in queries:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise ValueError("校准 case id 必须是非空且唯一的字符串")
        case_ids.add(case_id)
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError(f"case query 非法：{case_id}")
        if not isinstance(case.get("user_id"), int) or isinstance(case.get("user_id"), bool):
            raise ValueError(f"case user_id 非法：{case_id}")
        if not isinstance(case.get("relevant_source_ids"), list):
            raise ValueError(f"case relevant_source_ids 非法：{case_id}")
        if not isinstance(case.get("obvious_irrelevant_source_ids"), list):
            raise ValueError(f"case obvious_irrelevant_source_ids 非法：{case_id}")
        if not isinstance(case.get("tags"), list) or not all(
            isinstance(item, str) and item for item in case["tags"]
        ):
            raise ValueError(f"case tags 非法：{case_id}")
        expected = set(case["relevant_source_ids"])
        obvious = set(case["obvious_irrelevant_source_ids"])
        if len(expected) != len(case["relevant_source_ids"]) or len(obvious) != len(
            case["obvious_irrelevant_source_ids"]
        ):
            raise ValueError(f"case source_id 不得重复：{case_id}")
        if expected & obvious:
            raise ValueError(f"case 相关与明显无关 source_id 不得重叠：{case_id}")
        if not expected <= source_ids or not obvious <= source_ids:
            raise ValueError(f"case 引用了不存在的 source_id：{case.get('id')}")
        if any(source_users[item] != case["user_id"] for item in expected):
            raise ValueError(f"case 相关 source_id 不得属于其他用户：{case_id}")
    return payload


def load_frozen_dataset(
    dataset_name: str,
    manifest_path: Path = DATASET_MANIFEST_PATH,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if dataset_name not in DATASET_PATHS:
        raise ValueError(f"未知检索数据集：{dataset_name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_key = "final_holdout" if dataset_name == "holdout" else dataset_name
    entry = manifest["datasets"][manifest_key]
    dataset_path = DATASET_PATHS[dataset_name]
    digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        raise ValueError(f"{dataset_name} 数据集 SHA-256 与 manifest 不一致")
    dataset = load_dataset(dataset_path)
    if len(dataset["queries"]) != entry["query_count"]:
        raise ValueError(f"{dataset_name} query 数量与 manifest 不一致")
    if len(dataset["chunks"]) != entry["chunk_count"]:
        raise ValueError(f"{dataset_name} chunk 数量与 manifest 不一致")
    if len({item["user_id"] for item in dataset["chunks"]}) != entry["user_count"]:
        raise ValueError(f"{dataset_name} 用户数量与 manifest 不一致")
    if sum(not item["relevant_source_ids"] for item in dataset["queries"]) != entry["no_answer_count"]:
        raise ValueError(f"{dataset_name} 无答案数量与 manifest 不一致")
    return dataset, {**entry, "dataset_name": dataset_name, "sha256": digest}


def verify_production_freeze(
    path: Path = PRODUCTION_FREEZE_PATH,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("final_holdout_frozen") is not True:
        raise ValueError("生产检索逻辑尚未冻结")
    backend_root = Path(__file__).resolve().parents[1]
    for item in payload.get("production_files", []):
        relative_path = item.get("path")
        expected = item.get("sha256")
        if not isinstance(relative_path, str) or not isinstance(expected, str):
            raise ValueError("生产冻结文件记录非法")
        target = (backend_root / relative_path).resolve()
        if backend_root.resolve() not in target.parents:
            raise ValueError("生产冻结文件不得超出 backend")
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"生产冻结文件已变化：{relative_path}")
    manifest_digest = hashlib.sha256(DATASET_MANIFEST_PATH.read_bytes()).hexdigest()
    if manifest_digest != payload.get("dataset_manifest_sha256"):
        raise ValueError("数据集 manifest 在生产冻结后发生变化")
    return {
        **payload,
        "freeze_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _source_id(chunk: dict[str, Any]) -> str:
    return f"{chunk['file_id']}:{chunk['chunk_index']}"


def _chunk_from_result(
    source_id: str,
    document: str,
    metadata: dict[str, Any],
    distance: float,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "content": document,
        "metadata": metadata,
        "distance": float(distance),
    }


def _nearest_rank_percentile(values: list[float], percentage: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil((percentage / 100) * len(ordered)) - 1)
    return round(ordered[index], 6)


def _precision_at_k(
    ranked_ids: list[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    return len(set(ranked_ids[:k]) & relevant_ids) / k


def _recall_at_k(
    ranked_ids: list[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    if not relevant_ids:
        return 1.0 if not ranked_ids else 0.0
    return len(set(ranked_ids[:k]) & relevant_ids) / len(relevant_ids)


def _normalized_duplicate_ratio(chunks: list[dict[str, Any]]) -> float:
    from app.services.retrieval_ranking import normalize_text

    if not chunks:
        return 0.0
    fingerprints = [normalize_text(str(item.get("content") or "")) for item in chunks]
    return (len(fingerprints) - len(set(fingerprints))) / len(fingerprints)


def _lexical_rank(
    query: str,
    chunks: list[dict[str, Any]],
    *,
    top_k: int,
    distance_threshold: float,
    trusted_file_names: dict[str, str],
    semantic_weight: float = 0.70,
    allowed_categories: set[str] | None = None,
) -> list[dict[str, Any]]:
    from app.services.retrieval_ranking import extract_terms, normalize_text

    query_terms = extract_terms(query)
    normalized_query = normalize_text(query)
    scored = []
    for chunk in chunks:
        distance = float(chunk["distance"])
        metadata = chunk.get("metadata") or {}
        if distance > distance_threshold:
            continue
        if allowed_categories is not None and metadata.get("category") not in allowed_categories:
            continue
        content = str(chunk.get("content") or "")
        content_terms = extract_terms(content)
        filename_terms = extract_terms(
            trusted_file_names.get(str(metadata.get("file_id") or ""), "")
        )
        content_coverage = (
            len(query_terms & content_terms) / len(query_terms)
            if query_terms
            else 0.0
        )
        filename_coverage = (
            len(query_terms & filename_terms) / len(query_terms)
            if query_terms
            else 0.0
        )
        exact_phrase = float(
            bool(normalized_query) and normalized_query in normalize_text(content)
        )
        lexical_score = min(
            1.0,
            0.75 * content_coverage
            + 0.15 * exact_phrase
            + 0.10 * filename_coverage,
        )
        semantic_score = max(
            0.0,
            min(1.0, 1.0 - max(distance, 0.0) / distance_threshold),
        )
        combined = semantic_weight * semantic_score + (1 - semantic_weight) * lexical_score
        scored.append(
            (
                -combined,
                distance,
                chunk["source_id"],
                normalize_text(content),
                chunk,
            )
        )
    scored.sort(key=lambda item: item[:4])
    return [item[4] for item in scored[:top_k]]


def _vector_rank(
    chunks: list[dict[str, Any]],
    *,
    top_k: int,
    distance_threshold: float,
    allowed_categories: set[str],
) -> list[dict[str, Any]]:
    eligible = [
        item
        for item in chunks
        if float(item["distance"]) <= distance_threshold
        and (item.get("metadata") or {}).get("category") in allowed_categories
    ]
    eligible.sort(key=lambda item: (float(item["distance"]), item["source_id"]))
    return eligible[:top_k]


def _production_rank(
    query: str,
    chunks: list[dict[str, Any]],
    *,
    top_k: int,
    distance_threshold: float,
    trusted_file_names: dict[str, str],
    allowed_categories: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.services.retrieval_ranking import rerank_chunks

    ranked, stats = rerank_chunks(
        query,
        chunks,
        top_k=top_k,
        distance_threshold=distance_threshold,
        trusted_file_names=trusted_file_names,
        allowed_categories=allowed_categories,
    )
    return ranked, stats.as_dict()


def _dual_threshold_rank(
    query: str,
    chunks: list[dict[str, Any]],
    *,
    top_k: int,
    trusted_file_names: dict[str, str],
) -> list[dict[str, Any]]:
    from app.services.retrieval_confidence import HARD_REJECT_DISTANCE, STRONG_LEXICAL
    from app.services.retrieval_ranking import extract_terms, normalize_text

    query_terms = extract_terms(query)
    normalized_query = normalize_text(query)
    eligible = []
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        if metadata.get("category") not in {"project", "resume"}:
            continue
        distance = float(chunk["distance"])
        if distance > HARD_REJECT_DISTANCE:
            continue
        content = str(chunk.get("content") or "")
        content_coverage = (
            len(query_terms & extract_terms(content)) / len(query_terms)
            if query_terms
            else 0.0
        )
        file_id = str(metadata.get("file_id") or "")
        filename_coverage = (
            len(query_terms & extract_terms(trusted_file_names.get(file_id, "")))
            / len(query_terms)
            if query_terms
            else 0.0
        )
        exact_phrase = float(
            bool(normalized_query) and normalized_query in normalize_text(content)
        )
        lexical_score = (
            0.75 * content_coverage
            + 0.15 * exact_phrase
            + 0.10 * filename_coverage
        )
        if distance <= DISTANCE_THRESHOLD or lexical_score >= STRONG_LEXICAL:
            eligible.append(chunk)
    ranked, _stats = _production_rank(
        query,
        eligible,
        top_k=top_k,
        distance_threshold=HARD_REJECT_DISTANCE,
        trusted_file_names=trusted_file_names,
        allowed_categories={"project", "resume"},
    )
    return ranked


def _create_sqlite(
    path: Path,
    chunks: list[dict[str, Any]],
) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE files (file_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, "
        "filename TEXT NOT NULL, category TEXT NOT NULL)"
    )
    records = {}
    for chunk in chunks:
        if chunk.get("record_exists", True) is False:
            continue
        records[chunk["file_id"]] = (
            chunk["file_id"],
            chunk["user_id"],
            chunk["filename"],
            chunk["category"],
        )
    connection.executemany(
        "INSERT INTO files (file_id, user_id, filename, category) VALUES (?, ?, ?, ?)",
        records.values(),
    )
    connection.commit()
    return connection


def _verify_owned_candidates(
    connection: sqlite3.Connection,
    candidates: list[dict[str, Any]],
    user_id: int,
) -> tuple[list[dict[str, Any]], dict[str, str], int, int]:
    valid = []
    metadata_filtered = 0
    for chunk in candidates:
        metadata = chunk.get("metadata") or {}
        if (
            metadata.get("user_id") != user_id
            or not isinstance(metadata.get("file_id"), str)
            or not isinstance(metadata.get("chunk_index"), int)
        ):
            metadata_filtered += 1
            continue
        valid.append(chunk)
    file_ids = sorted({item["metadata"]["file_id"] for item in valid})
    rows = []
    if file_ids:
        placeholders = ",".join("?" for _ in file_ids)
        rows = connection.execute(
            f"SELECT file_id, filename, category FROM files "
            f"WHERE user_id = ? AND file_id IN ({placeholders})",
            [user_id, *file_ids],
        ).fetchall()
    owned = {row[0]: (row[1], row[2]) for row in rows}
    output = []
    ownership_filtered = 0
    for chunk in valid:
        file_id = chunk["metadata"]["file_id"]
        if file_id not in owned:
            ownership_filtered += 1
            continue
        filename, category = owned[file_id]
        chunk["metadata"] = {**chunk["metadata"], "filename": filename, "category": category}
        output.append(chunk)
    trusted_names = {file_id: values[0] for file_id, values in owned.items()}
    return output, trusted_names, metadata_filtered, ownership_filtered


def _strategy_metrics(
    case_rows: list[dict[str, Any]],
    strategy: str,
) -> dict[str, Any]:
    positive = [row for row in case_rows if row["relevant_source_ids"]]
    empty = [row for row in case_rows if not row["relevant_source_ids"]]
    rankings = [row["rankings"][strategy] for row in case_rows]
    return {
        "recall_at_1": mean(
            _recall_at_k(row["rankings"][strategy], set(row["relevant_source_ids"]), 1)
            for row in positive
        ),
        "recall_at_3": mean(
            _recall_at_k(row["rankings"][strategy], set(row["relevant_source_ids"]), 3)
            for row in positive
        ),
        "recall_at_5": mean(
            _recall_at_k(row["rankings"][strategy], set(row["relevant_source_ids"]), 5)
            for row in positive
        ),
        "mrr": mean(
            reciprocal_rank(row["rankings"][strategy], set(row["relevant_source_ids"]))
            for row in positive
        ),
        "precision_at_3": mean(
            _precision_at_k(row["rankings"][strategy], set(row["relevant_source_ids"]), 3)
            for row in case_rows
        ),
        "irrelevant_ratio": mean(
            (
                sum(source_id not in set(row["relevant_source_ids"]) for source_id in row["rankings"][strategy])
                / len(row["rankings"][strategy])
                if row["rankings"][strategy]
                else 0.0
            )
            for row in case_rows
        ),
        "duplicate_ratio": mean(
            row["duplicate_ratios"][strategy] for row in case_rows
        ),
        "empty_result_accuracy": mean(
            not row["rankings"][strategy] for row in empty
        ),
        "query_count": len(rankings),
    }


def _reliability_metrics(
    case_rows: list[dict[str, Any]],
    strategy: str,
) -> dict[str, Any]:
    base = _strategy_metrics(case_rows, strategy)
    relevant_count = sum(len(row["relevant_source_ids"]) for row in case_rows)
    obvious_count = sum(len(row["obvious_irrelevant_source_ids"]) for row in case_rows)
    false_rejects = sum(
        len(set(row["relevant_source_ids"]) - set(row["rankings"][strategy]))
        for row in case_rows
    )
    false_accepts = sum(
        len(set(row["obvious_irrelevant_source_ids"]) & set(row["rankings"][strategy]))
        for row in case_rows
    )
    candidate_counts = [row["strategy_candidate_counts"][strategy] for row in case_rows]
    return {
        **base,
        "no_answer_accuracy": base["empty_result_accuracy"],
        "false_reject_count": false_rejects,
        "false_reject_rate": false_rejects / relevant_count if relevant_count else 0.0,
        "false_accept_count": false_accepts,
        "false_accept_rate": false_accepts / obvious_count if obvious_count else 0.0,
        "candidate_truncation_count": sum(
            row["strategy_candidate_truncated"][strategy] for row in case_rows
        ),
        "average_candidate_count": mean(candidate_counts),
        "candidate_count_p50": _nearest_rank_percentile(candidate_counts, 50),
        "candidate_count_p95": _nearest_rank_percentile(candidate_counts, 95),
        "adaptive_expansion_count": sum(
            row["strategy_adaptive_expanded"].get(strategy, False)
            for row in case_rows
        ),
    }


def _target_assessment(
    metrics: dict[str, Any],
    *,
    final_holdout_frozen: bool,
) -> dict[str, Any]:
    checks = {
        "no_answer_accuracy_gte_0_80": metrics["no_answer_accuracy"] >= 0.80,
        "false_reject_rate_lte_0_20": metrics["false_reject_rate"] <= 0.20,
        "false_accept_rate_lte_0_12": metrics["false_accept_rate"] <= 0.12,
        "recall_at_3_gte_0_80": metrics["recall_at_3"] >= 0.80,
        "precision_at_3_gte_0_35": metrics["precision_at_3"] >= 0.35,
        "mrr_gte_0_80": metrics["mrr"] >= 0.80,
    }
    return {
        "evaluated_for_final_holdout": final_holdout_frozen,
        "passed": all(checks.values()) if final_holdout_frozen else None,
        "checks": checks,
    }


def _distance_summary(
    relevant_distances: list[float],
    irrelevant_distances: list[float],
    case_rows: list[dict[str, Any]],
    false_reject_count: int,
    relevant_pair_count: int,
    false_accept_count: int,
    obvious_pair_count: int,
) -> dict[str, Any]:
    return {
        "relevant": {
            "min": round(min(relevant_distances, default=0.0), 6),
            "p50": _nearest_rank_percentile(relevant_distances, 50),
            "p95": _nearest_rank_percentile(relevant_distances, 95),
            "count": len(relevant_distances),
        },
        "irrelevant": {
            "min": round(min(irrelevant_distances, default=0.0), 6),
            "p50": _nearest_rank_percentile(irrelevant_distances, 50),
            "p95": _nearest_rank_percentile(irrelevant_distances, 95),
            "count": len(irrelevant_distances),
        },
        "overlap_case_count": sum(row["distance_overlap"] for row in case_rows),
        "false_reject_count": false_reject_count,
        "false_reject_rate": false_reject_count / relevant_pair_count if relevant_pair_count else 0.0,
        "false_accept_count": false_accept_count,
        "false_accept_rate": false_accept_count / obvious_pair_count if obvious_pair_count else 0.0,
    }


def _parameter_comparison(case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    combinations = [
        (DISTANCE_THRESHOLD, CANDIDATE_MULTIPLIER, 0.70, "current"),
        (max(0.1, DISTANCE_THRESHOLD - 0.1), CANDIDATE_MULTIPLIER, 0.70, "stricter_threshold"),
        (DISTANCE_THRESHOLD + 0.1, CANDIDATE_MULTIPLIER, 0.70, "wider_threshold"),
        (DISTANCE_THRESHOLD, 2, 0.70, "multiplier_2"),
        (DISTANCE_THRESHOLD, 4, 0.70, "multiplier_4"),
        (DISTANCE_THRESHOLD, CANDIDATE_MULTIPLIER, 0.60, "semantic_0_6"),
        (DISTANCE_THRESHOLD, CANDIDATE_MULTIPLIER, 0.80, "semantic_0_8"),
    ]
    output = []
    for threshold, multiplier, semantic_weight, label in combinations:
        recalls = []
        precisions = []
        false_rejects = 0
        false_accepts = 0
        truncations = 0
        for row in case_rows:
            relevant = set(row["relevant_source_ids"])
            obvious = set(row["obvious_irrelevant_source_ids"])
            candidate_k = min(MAX_CANDIDATES, max(5, 5 * multiplier))
            candidates = row["all_owned_chunks"][:candidate_k]
            ranked = _lexical_rank(
                row["query"],
                candidates,
                top_k=5,
                distance_threshold=threshold,
                trusted_file_names=row["trusted_file_names"],
                semantic_weight=semantic_weight,
                allowed_categories={"project", "resume"},
            )
            ranked_ids = [item["source_id"] for item in ranked]
            if relevant:
                recalls.append(_recall_at_k(ranked_ids, relevant, 3))
                false_rejects += sum(
                    item["source_id"] in relevant and float(item["distance"]) > threshold
                    for item in row["all_owned_chunks"]
                )
                truncations += int(
                    not relevant <= {item["source_id"] for item in candidates}
                )
            false_accepts += sum(
                item["source_id"] in obvious and float(item["distance"]) <= threshold
                for item in candidates
            )
            precisions.append(_precision_at_k(ranked_ids, relevant, 3))
        output.append(
            {
                "label": label,
                "distance_threshold": threshold,
                "candidate_multiplier": multiplier,
                "semantic_weight": semantic_weight,
                "recall_at_3": mean(recalls),
                "precision_at_3": mean(precisions),
                "false_reject_count": false_rejects,
                "false_accept_count": false_accepts,
                "candidate_truncation_count": truncations,
            }
        )
    return output


def _render_report(summary: dict[str, Any]) -> str:
    metrics = summary["strategy_metrics"]
    distance = summary["distance_distribution"]
    lines = [
        "# 真实 BGE / Chroma 检索校准报告",
        "",
        f"- 运行状态：`{summary['status']}`",
        f"- 运行模式：`{summary['run_mode']}`",
        f"- Git Commit：`{summary['git_commit']}`",
        f"- 模型：`{summary['model_id']}`（仅本地缓存）",
        f"- 数据集：`{summary['dataset_name']}` / `{summary['dataset_role']}`",
        f"- 数据集 SHA-256：`{summary['dataset_sha256']}`",
        f"- 评估阶段：`{summary['evaluation_stage']}`",
        "- 网络：禁用；未调用 DeepSeek 或 Tavily",
        f"- 数据集：{summary['query_count']} 个 query / {summary['chunk_count']} 个 chunk",
        "- 环境：临时 SQLite、临时 Chroma、临时上传目录，与生产路径隔离",
        "",
        "## 排序方案比较",
        "",
        "| 方案 | Recall@1 | Recall@3 | Recall@5 | Precision@3 | MRR | 空结果准确率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, label in [
        ("vector", "纯向量距离"),
        ("lexical", "距离 + 当前词项"),
        ("final", "距离 + 词项 + 去重/多样性"),
    ]:
        item = metrics[key]
        lines.append(
            f"| {label} | {item['recall_at_1']:.2%} | {item['recall_at_3']:.2%} | "
            f"{item['recall_at_5']:.2%} | {item['precision_at_3']:.2%} | "
            f"{item['mrr']:.2%} | {item['empty_result_accuracy']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 检索可靠性方案比较",
            "",
            "| 方案 | Recall@3 | Precision@3 | MRR | 无答案准确率 | False reject | False accept | 截断 | 扩展 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for key, label in [
        ("fixed_current", "A 固定阈值 + 固定候选池"),
        ("dual_threshold", "B 双阈值 + 固定候选池"),
        ("confidence_fixed_pool", "C 置信度 + 固定候选池"),
        ("confidence_adaptive_pool", "D 置信度 + 受控扩展"),
    ]:
        item = summary["reliability_strategy_comparison"][key]
        lines.append(
            f"| {label} | {item['recall_at_3']:.2%} | {item['precision_at_3']:.2%} | "
            f"{item['mrr']:.2%} | {item['no_answer_accuracy']:.2%} | "
            f"{item['false_reject_count']} ({item['false_reject_rate']:.2%}) | "
            f"{item['false_accept_count']} ({item['false_accept_rate']:.2%}) | "
            f"{item['candidate_truncation_count']} | {item['adaptive_expansion_count']} |"
        )
    if summary["target_assessment"]["evaluated_for_final_holdout"]:
        failed_checks = [
            key
            for key, passed in summary["target_assessment"]["checks"].items()
            if not passed
        ]
        lines.extend(
            [
                "",
                "## Final holdout 目标判定",
                "",
                f"- 全部目标通过：{summary['target_assessment']['passed']}",
                f"- 未达到目标：{', '.join(failed_checks) or '无'}",
                "- `status=completed` 只表示校准执行完成，不表示指标全部达标。",
            ]
        )
    lines.extend(
        [
            "",
            "## 距离分布与阈值",
            "",
            f"- 相关距离 min/P50/P95：{distance['relevant']['min']:.4f} / {distance['relevant']['p50']:.4f} / {distance['relevant']['p95']:.4f}",
            f"- 无关距离 min/P50/P95：{distance['irrelevant']['min']:.4f} / {distance['irrelevant']['p50']:.4f} / {distance['irrelevant']['p95']:.4f}",
            f"- 距离重叠 case：{distance['overlap_case_count']}",
            f"- 当前阈值 false reject：{distance['false_reject_count']}（{distance['false_reject_rate']:.2%}）",
            f"- 当前阈值明显 false accept：{distance['false_accept_count']}（{distance['false_accept_rate']:.2%}）",
            "",
            "## 候选池与重排",
            "",
            f"- 候选池截断漏召回：{summary['candidate_truncation_count']}",
            f"- 候选池截断 case：{', '.join(summary['candidate_truncation_case_ids']) or '无'}",
            f"- 重排提升 case：{len(summary['rerank_improved_case_ids'])}",
            f"- 重排退化 case：{len(summary['rerank_degraded_case_ids'])}",
            f"- 退化 case：{', '.join(summary['rerank_degraded_case_ids']) or '无'}",
            f"- 跨用户泄露：{summary['cross_user_leakage_count']}",
            f"- 非法 source_id：{summary['invalid_source_id_count']}",
            f"- 排序不稳定：{summary['sort_instability_count']}",
            f"- 所有权/metadata/距离/category/去重过滤总数："
            f"{summary['filter_totals']['ownership_filtered_count']} / "
            f"{summary['filter_totals']['metadata_filtered_count']} / "
            f"{summary['filter_totals']['distance_filtered_count']} / "
            f"{summary['filter_totals']['category_filtered_count']} / "
            f"{summary['filter_totals']['duplicate_filtered_count']}",
            "",
            "## 参数模拟",
            "",
            "| 组合 | Recall@3 | Precision@3 | False reject | False accept | 候选截断 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary["parameter_comparison"]:
        lines.append(
            f"| {row['label']} | {row['recall_at_3']:.2%} | {row['precision_at_3']:.2%} | "
            f"{row['false_reject_count']} | {row['false_accept_count']} | "
            f"{row['candidate_truncation_count']} |"
        )
    lines.extend(
        [
            "",
            "## 参数建议",
            "",
            f"{summary['parameter_recommendation']}",
            "",
            "## 性能",
            "",
            f"- 文档 Embedding：{summary['performance_ms']['document_embedding']:.1f} ms",
            f"- Query Embedding：{summary['performance_ms']['query_embedding']:.1f} ms",
            f"- Chroma 写入：{summary['performance_ms']['chroma_index']:.1f} ms",
            f"- 检索与重排总计：{summary['performance_ms']['retrieval_and_rerank']:.1f} ms",
            "",
            "## 已知局限",
            "",
            "- 语料完全合成，不能代表真实用户表达和生产规模。",
            "- 数据集规模适合参数诊断，不适合据此直接修改生产参数。",
            "- BGE 未使用额外 query instruction，与当前生产调用保持一致。",
            "- Chroma 使用当前默认平方 L2；不同版本或显式 collection metadata 可能改变距离。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_skipped_result(output_base: Path, cache: dict[str, Any]) -> Path:
    run_id = "retrieval-calibration-" + datetime.now().strftime("%Y-%m-%dT%H%M%S-%f")
    output_dir = create_result_dir(output_base, run_id)
    summary = {
        "status": "skipped_model_cache_missing",
        "run_mode": "real_embedding",
        "git_commit": _git_commit(),
        "model_id": cache["model_id"],
        "local_cache_used": False,
        "network_disabled": True,
        "download_attempted": False,
    }
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "cases.json", [])
    write_json(output_dir / "distance-distribution.json", {})
    (output_dir / "report.md").write_text(
        "# 真实 BGE / Chroma 检索校准报告\n\n"
        "本地未发现所需 Embedding 模型缓存，校准未执行。未发起网络下载。\n",
        encoding="utf-8",
    )
    return output_dir


def run_real_calibration(
    output_base: Path = RESULTS_DIR,
    dataset_path: Path | None = None,
    *,
    dataset_name: str = "development",
    evaluation_stage: str = "calibration",
    suppress_case_details: bool = False,
    final_holdout_frozen: bool = False,
    production_freeze_sha256: str | None = None,
) -> tuple[dict[str, Any], Path]:
    configure_offline_environment()
    cache = model_cache_status()
    snapshot = _resolve_cached_snapshot()
    if snapshot is None:
        output_dir = _write_skipped_result(output_base, cache)
        return {
            "status": "skipped_model_cache_missing",
            "model_id": MODEL_ID,
            "download_attempted": False,
        }, output_dir

    if dataset_path is None:
        dataset, dataset_entry = load_frozen_dataset(dataset_name)
    else:
        dataset = load_dataset(dataset_path)
        dataset_entry = {
            "dataset_name": dataset_name,
            "role": dataset.get("dataset_role", "ad_hoc_test"),
            "sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        }
    started_at = datetime.now().astimezone()
    with tempfile.TemporaryDirectory(prefix="spi-retrieval-calibration-") as temp_dir:
        temp_root = Path(temp_dir).resolve()
        sqlite_path = temp_root / "calibration.sqlite3"
        chroma_path = temp_root / "chroma"
        upload_path = temp_root / "uploads"
        upload_path.mkdir()
        backend_root = Path(__file__).resolve().parents[1]
        production_paths = {
            (backend_root / "data" / "app.db").resolve(),
            (backend_root / "data" / "chroma_db").resolve(),
            (backend_root / "data" / "uploads").resolve(),
        }
        if {sqlite_path.resolve(), chroma_path.resolve(), upload_path.resolve()} & production_paths:
            raise RuntimeError("校准临时路径不得指向生产配置")

        connection = _create_sqlite(sqlite_path, dataset["chunks"])
        client = None
        try:
            with block_network():
                import chromadb
                from chromadb.config import Settings
                from sentence_transformers import SentenceTransformer

                model_started = time.perf_counter()
                model = SentenceTransformer(
                    str(snapshot),
                    local_files_only=True,
                )
                documents = [item["content"] for item in dataset["chunks"]]
                document_embeddings = model.encode(
                    documents,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ).tolist()
                document_embedding_ms = (time.perf_counter() - model_started) * 1000

                query_started = time.perf_counter()
                query_embeddings = model.encode(
                    [item["query"] for item in dataset["queries"]],
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ).tolist()
                query_embedding_ms = (time.perf_counter() - query_started) * 1000

                client = chromadb.PersistentClient(
                    path=str(chroma_path),
                    settings=Settings(anonymized_telemetry=False),
                )
                collection = client.create_collection(
                    name=f"retrieval_calibration_{started_at.strftime('%H%M%S%f')}",
                )
                ids = [_source_id(item) for item in dataset["chunks"]]
                metadatas = [
                    {
                        "user_id": item["user_id"],
                        "file_id": item["file_id"],
                        "filename": item["filename"],
                        "category": item["category"],
                        "chunk_index": item["chunk_index"],
                    }
                    for item in dataset["chunks"]
                ]
                index_started = time.perf_counter()
                collection.add(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas,
                    embeddings=document_embeddings,
                )
                index_ms = (time.perf_counter() - index_started) * 1000

                retrieval_started = time.perf_counter()
                case_rows = []
                relevant_distances = []
                irrelevant_distances = []
                false_reject_count = 0
                relevant_pair_count = 0
                false_accept_count = 0
                obvious_pair_count = 0
                truncation_count = 0
                truncation_case_ids = []
                invalid_source_ids = 0
                cross_user_leakage = 0
                instability_count = 0
                for case, query_embedding in zip(dataset["queries"], query_embeddings):
                    user_count = sum(item["user_id"] == case["user_id"] for item in dataset["chunks"])
                    result = collection.query(
                        query_embeddings=[query_embedding],
                        n_results=user_count,
                        where={"user_id": case["user_id"]},
                        include=["documents", "metadatas", "distances"],
                    )
                    full_chunks = [
                        _chunk_from_result(source_id, document, metadata, distance)
                        for source_id, document, metadata, distance in zip(
                            result["ids"][0],
                            result["documents"][0],
                            result["metadatas"][0],
                            result["distances"][0],
                        )
                    ]
                    all_owned, all_names, _, _ = _verify_owned_candidates(
                        connection,
                        full_chunks,
                        case["user_id"],
                    )
                    candidate_k = min(MAX_CANDIDATES, max(5, 5 * CANDIDATE_MULTIPLIER))
                    candidates = full_chunks[:candidate_k]
                    owned, trusted_names, metadata_filtered, ownership_filtered = _verify_owned_candidates(
                        connection,
                        candidates,
                        case["user_id"],
                    )
                    from app.services.retrieval_confidence import (
                        ADAPTIVE_EXPANSION_DISTANCE,
                        HARD_REJECT_DISTANCE,
                        decide_retrieval_evidence,
                    )

                    boundary_is_open = bool(
                        candidates
                        and isinstance(candidates[-1].get("distance"), (int, float))
                        and float(candidates[-1]["distance"])
                        <= ADAPTIVE_EXPANSION_DISTANCE
                    )
                    adaptive_expanded = (
                        len(candidates) == candidate_k
                        and candidate_k < MAX_CANDIDATES
                        and boundary_is_open
                    )
                    expanded_k = (
                        min(MAX_CANDIDATES, max(candidate_k + 5, candidate_k * 2))
                        if adaptive_expanded
                        else candidate_k
                    )
                    expanded_candidates = full_chunks[:expanded_k]
                    expanded_owned, expanded_names, _, _ = _verify_owned_candidates(
                        connection,
                        expanded_candidates,
                        case["user_id"],
                    )
                    relevant = set(case["relevant_source_ids"])
                    obvious = set(case["obvious_irrelevant_source_ids"])
                    distance_by_id = {item["source_id"]: float(item["distance"]) for item in all_owned}
                    case_relevant_distances = [distance_by_id[item] for item in relevant if item in distance_by_id]
                    case_irrelevant_distances = [
                        float(item["distance"])
                        for item in all_owned
                        if item["source_id"] not in relevant
                    ]
                    relevant_distances.extend(case_relevant_distances)
                    irrelevant_distances.extend(case_irrelevant_distances)
                    case_false_rejects = sum(value > DISTANCE_THRESHOLD for value in case_relevant_distances)
                    case_false_accepts = sum(
                        distance_by_id[item] <= DISTANCE_THRESHOLD
                        for item in obvious
                        if item in distance_by_id
                    )
                    false_reject_count += case_false_rejects
                    relevant_pair_count += len(case_relevant_distances)
                    false_accept_count += case_false_accepts
                    obvious_pair_count += sum(item in distance_by_id for item in obvious)
                    truncated = bool(relevant and not relevant <= {item["source_id"] for item in candidates})
                    truncation_count += int(truncated)
                    if truncated:
                        truncation_case_ids.append(case["id"])

                    vector = _vector_rank(
                        owned,
                        top_k=5,
                        distance_threshold=DISTANCE_THRESHOLD,
                        allowed_categories={"project", "resume"},
                    )
                    lexical = _lexical_rank(
                        case["query"],
                        owned,
                        top_k=5,
                        distance_threshold=DISTANCE_THRESHOLD,
                        trusted_file_names=trusted_names,
                        allowed_categories={"project", "resume"},
                    )
                    final, ranking_stats = _production_rank(
                        case["query"],
                        owned,
                        top_k=5,
                        distance_threshold=DISTANCE_THRESHOLD,
                        trusted_file_names=trusted_names,
                        allowed_categories={"project", "resume"},
                    )
                    dual_threshold = _dual_threshold_rank(
                        case["query"],
                        owned,
                        top_k=5,
                        trusted_file_names=trusted_names,
                    )
                    confidence = decide_retrieval_evidence(
                        case["query"],
                        owned,
                        top_k=5,
                        high_confidence_distance=DISTANCE_THRESHOLD,
                        trusted_file_names=trusted_names,
                        allowed_categories={"project", "resume"},
                    )
                    adaptive_confidence = decide_retrieval_evidence(
                        case["query"],
                        expanded_owned,
                        top_k=5,
                        high_confidence_distance=DISTANCE_THRESHOLD,
                        trusted_file_names=expanded_names,
                        allowed_categories={"project", "resume"},
                    )
                    repeated, _ = _production_rank(
                        case["query"],
                        owned,
                        top_k=5,
                        distance_threshold=DISTANCE_THRESHOLD,
                        trusted_file_names=trusted_names,
                        allowed_categories={"project", "resume"},
                    )
                    rankings = {
                        "vector": [item["source_id"] for item in vector],
                        "lexical": [item["source_id"] for item in lexical],
                        "final": [item["source_id"] for item in final],
                        "fixed_current": [item["source_id"] for item in final],
                        "dual_threshold": [item["source_id"] for item in dual_threshold],
                        "confidence_fixed_pool": [
                            item["source_id"] for item in confidence.accepted_candidates
                        ],
                        "confidence_adaptive_pool": [
                            item["source_id"]
                            for item in adaptive_confidence.accepted_candidates
                        ],
                    }
                    instability_count += int(rankings["final"] != [item["source_id"] for item in repeated])
                    allowed_sources = {
                        _source_id(item)
                        for item in dataset["chunks"]
                        if item["user_id"] == case["user_id"] and item.get("record_exists", True)
                    }
                    invalid_source_ids += sum(item not in allowed_sources for item in rankings["final"])
                    foreign_sources = {
                        _source_id(item)
                        for item in dataset["chunks"]
                        if item["user_id"] != case["user_id"]
                    }
                    cross_user_leakage += sum(item in foreign_sources for item in rankings["final"])
                    best_relevant = min(case_relevant_distances, default=None)
                    best_irrelevant = min(case_irrelevant_distances, default=None)
                    sorted_relevant = sorted(case_relevant_distances)
                    case_rows.append(
                        {
                            "case_id": case["id"],
                            "query": case["query"],
                            "tags": case["tags"],
                            "relevant_source_ids": sorted(relevant),
                            "obvious_irrelevant_source_ids": sorted(obvious),
                            "rankings": rankings,
                            "relevant_distances": [
                                {"source_id": item, "distance": round(distance_by_id[item], 6)}
                                for item in sorted(relevant)
                                if item in distance_by_id
                            ],
                            "irrelevant_distances": [
                                {"source_id": item["source_id"], "distance": round(float(item["distance"]), 6)}
                                for item in all_owned
                                if item["source_id"] not in relevant
                            ],
                            "best_relevant_distance": round(best_relevant, 6) if best_relevant is not None else None,
                            "third_relevant_distance": round(sorted_relevant[2], 6) if len(sorted_relevant) >= 3 else None,
                            "best_irrelevant_distance": round(best_irrelevant, 6) if best_irrelevant is not None else None,
                            "distance_margin": (
                                round(best_irrelevant - best_relevant, 6)
                                if best_relevant is not None and best_irrelevant is not None
                                else None
                            ),
                            "distance_overlap": bool(
                                best_relevant is not None
                                and best_irrelevant is not None
                                and best_irrelevant < best_relevant
                            ),
                            "threshold_kept_relevant": case_false_rejects == 0,
                            "threshold_false_accept_count": case_false_accepts,
                            "candidate_pool_size": len(candidates),
                            "final_result_count": len(final),
                            "ownership_filtered_count": (
                                ownership_filtered
                                + sum(
                                    item["user_id"] != case["user_id"]
                                    for item in dataset["chunks"]
                                )
                            ),
                            "metadata_filtered_count": metadata_filtered,
                            "distance_filtered_count": ranking_stats["distance_filtered_count"],
                            "category_filtered_count": ranking_stats["category_filtered_count"],
                            "duplicate_filtered_count": ranking_stats["duplicate_filtered_count"],
                            "near_duplicate_penalty_count": ranking_stats["near_duplicate_penalty_count"],
                            "candidate_truncated_relevant": truncated,
                            "duplicate_ratios": {
                                "vector": _normalized_duplicate_ratio(vector),
                                "lexical": _normalized_duplicate_ratio(lexical),
                                "final": _normalized_duplicate_ratio(final),
                                "fixed_current": _normalized_duplicate_ratio(final),
                                "dual_threshold": _normalized_duplicate_ratio(dual_threshold),
                                "confidence_fixed_pool": _normalized_duplicate_ratio(
                                    confidence.accepted_candidates
                                ),
                                "confidence_adaptive_pool": _normalized_duplicate_ratio(
                                    adaptive_confidence.accepted_candidates
                                ),
                            },
                            "strategy_candidate_counts": {
                                "fixed_current": len(owned),
                                "dual_threshold": len(owned),
                                "confidence_fixed_pool": len(owned),
                                "confidence_adaptive_pool": len(expanded_owned),
                            },
                            "strategy_candidate_truncated": {
                                "fixed_current": truncated,
                                "dual_threshold": truncated,
                                "confidence_fixed_pool": truncated,
                                "confidence_adaptive_pool": bool(
                                    relevant
                                    and not relevant
                                    <= {item["source_id"] for item in expanded_candidates}
                                ),
                            },
                            "strategy_adaptive_expanded": {
                                "fixed_current": False,
                                "dual_threshold": False,
                                "confidence_fixed_pool": False,
                                "confidence_adaptive_pool": adaptive_expanded,
                            },
                            "confidence_decision_reason": adaptive_confidence.decision_reason,
                            "all_owned_chunks": all_owned,
                            "trusted_file_names": all_names,
                        }
                    )
                retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
        finally:
            connection.close()
            if client is not None:
                system = getattr(client, "_system", None)
                if system is not None and hasattr(system, "stop"):
                    system.stop()

        strategy_metrics = {
            strategy: _strategy_metrics(case_rows, strategy)
            for strategy in ("vector", "lexical", "final")
        }
        reliability_strategy_comparison = {
            strategy: _reliability_metrics(case_rows, strategy)
            for strategy in (
                "fixed_current",
                "dual_threshold",
                "confidence_fixed_pool",
                "confidence_adaptive_pool",
            )
        }
        selected_reliability = reliability_strategy_comparison[
            "confidence_adaptive_pool"
        ]
        target_assessment = _target_assessment(
            selected_reliability,
            final_holdout_frozen=final_holdout_frozen,
        )
        improved = []
        degraded = []
        for row in case_rows:
            relevant = set(row["relevant_source_ids"])
            if not relevant:
                continue
            vector_rr = reciprocal_rank(row["rankings"]["vector"], relevant)
            final_rr = reciprocal_rank(row["rankings"]["final"], relevant)
            vector_recall = _recall_at_k(row["rankings"]["vector"], relevant, 3)
            final_recall = _recall_at_k(row["rankings"]["final"], relevant, 3)
            if (final_recall, final_rr) > (vector_recall, vector_rr):
                improved.append(row["case_id"])
            elif (final_recall, final_rr) < (vector_recall, vector_rr):
                degraded.append(row["case_id"])
        distance_summary = _distance_summary(
            relevant_distances,
            irrelevant_distances,
            case_rows,
            false_reject_count,
            relevant_pair_count,
            false_accept_count,
            obvious_pair_count,
        )
        parameter_comparison = _parameter_comparison(case_rows)
        current = parameter_comparison[0]
        best_recall = max(item["recall_at_3"] for item in parameter_comparison)
        if (
            current["recall_at_3"] >= best_recall - 0.02
            and distance_summary["false_reject_rate"] <= 0.05
            and truncation_count == 0
        ):
            recommendation = "建议保持当前生产参数不变；当前组合接近受控模拟中的最佳 Recall，且未发现候选池截断。"
        else:
            recommendation = "本阶段不修改生产参数；真实分布暴露了 Recall、阈值或候选截断问题，建议下一阶段基于失败与截断 case 单独评审参数。"

        serializable_cases = []
        if not suppress_case_details:
            for row in case_rows:
                serializable_cases.append(
                    {
                        key: value
                        for key, value in row.items()
                        if key not in {"all_owned_chunks", "trusted_file_names", "query"}
                    }
                )
        summary = {
            "status": "completed",
            "run_mode": "real_embedding",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now().astimezone().isoformat(),
            "git_commit": _git_commit(),
            "model_id": MODEL_ID,
            "dataset_name": dataset_entry["dataset_name"],
            "dataset_role": dataset_entry["role"],
            "dataset_sha256": dataset_entry["sha256"],
            "evaluation_stage": evaluation_stage,
            "case_details_suppressed": suppress_case_details,
            "final_holdout_frozen": final_holdout_frozen,
            "production_freeze_sha256": production_freeze_sha256,
            "embedding_dimension": len(document_embeddings[0]),
            "local_cache_used": True,
            "network_disabled": True,
            "download_attempted": False,
            "distance_metric": "l2_squared",
            "normalized_embeddings": True,
            "query_count": len(dataset["queries"]),
            "chunk_count": len(dataset["chunks"]),
            "isolation": {
                "temporary_sqlite": True,
                "temporary_chroma": True,
                "temporary_upload_directory": True,
                "production_paths_accessed": False,
                "real_user_data_used": False,
                "dotenv_loaded": False,
                "deepseek_called": False,
                "tavily_called": False,
                "ownership_batch_query_count_per_case": 1,
            },
            "current_parameters": {
                "distance_threshold": DISTANCE_THRESHOLD,
                "candidate_multiplier": CANDIDATE_MULTIPLIER,
                "max_candidates": MAX_CANDIDATES,
                "semantic_weight": 0.70,
                "lexical_weight": 0.30,
                "diversity_penalty": 0.12,
            },
            "strategy_metrics": strategy_metrics,
            "reliability_strategy_comparison": reliability_strategy_comparison,
            "target_assessment": target_assessment,
            "distance_distribution": distance_summary,
            "candidate_truncation_count": truncation_count,
            "candidate_truncation_case_ids": truncation_case_ids,
            "rerank_improved_case_ids": [] if suppress_case_details else improved,
            "rerank_degraded_case_ids": [] if suppress_case_details else degraded,
            "cross_user_leakage_count": cross_user_leakage,
            "invalid_source_id_count": invalid_source_ids,
            "sort_instability_count": instability_count,
            "filter_totals": {
                "ownership_filtered_count": sum(
                    row["ownership_filtered_count"] for row in case_rows
                ),
                "metadata_filtered_count": sum(
                    row["metadata_filtered_count"] for row in case_rows
                ),
                "distance_filtered_count": sum(
                    row["distance_filtered_count"] for row in case_rows
                ),
                "category_filtered_count": sum(
                    row["category_filtered_count"] for row in case_rows
                ),
                "duplicate_filtered_count": sum(
                    row["duplicate_filtered_count"] for row in case_rows
                ),
            },
            "parameter_comparison": parameter_comparison,
            "parameter_recommendation": recommendation,
            "performance_ms": {
                "document_embedding": round(document_embedding_ms, 3),
                "query_embedding": round(query_embedding_ms, 3),
                "chroma_index": round(index_ms, 3),
                "retrieval_and_rerank": round(retrieval_ms, 3),
            },
            "known_limitations": [
                "完全合成语料不能代表真实用户分布。",
                "样本规模只适合诊断，不适合直接调生产参数。",
                "不包含 Cross Encoder 或 LLM reranker。",
            ],
        }
        run_id = (
            f"retrieval-calibration-{dataset_name}-"
            + started_at.strftime("%Y-%m-%dT%H%M%S-%f")
        )
        output_dir = create_result_dir(output_base, run_id)
        write_json(output_dir / "summary.json", summary)
        if final_holdout_frozen:
            write_json(
                output_dir / "final-holdout-marker.json",
                {
                    "final_holdout_frozen": True,
                    "dataset_sha256": dataset_entry["sha256"],
                    "production_freeze_sha256": production_freeze_sha256,
                    "status": summary["status"],
                },
            )
        write_json(output_dir / "cases.json", serializable_cases)
        write_json(
            output_dir / "distance-distribution.json",
            {
                "summary": distance_summary,
                "cases": [] if suppress_case_details else [
                    {
                        "case_id": row["case_id"],
                        "relevant_distances": row["relevant_distances"],
                        "irrelevant_distances": row["irrelevant_distances"],
                        "best_relevant_distance": row["best_relevant_distance"],
                        "third_relevant_distance": row["third_relevant_distance"],
                        "best_irrelevant_distance": row["best_irrelevant_distance"],
                        "distance_margin": row["distance_margin"],
                    }
                    for row in case_rows
                ],
            },
        )
        (output_dir / "report.md").write_text(
            _render_report(summary),
            encoding="utf-8",
        )
        return summary, output_dir
