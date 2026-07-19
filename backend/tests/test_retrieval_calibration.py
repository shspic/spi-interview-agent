import json
import socket
import sqlite3
from pathlib import Path

import numpy as np

from evals import retrieval_calibration
from evals.retrieval_calibration import (
    _distance_summary,
    _lexical_rank,
    _parameter_comparison,
    _precision_at_k,
    _strategy_metrics,
    _verify_owned_candidates,
    load_dataset,
)


def _metric_row(rankings, relevant):
    return {
        "relevant_source_ids": relevant,
        "rankings": rankings,
        "duplicate_ratios": {"vector": 0.0, "lexical": 0.0, "final": 0.0},
    }


def test_calibration_dataset_is_synthetic_and_has_required_scale():
    dataset = load_dataset()
    assert len(dataset["queries"]) == 35
    assert len(dataset["chunks"]) == 48
    assert {item["user_id"] for item in dataset["chunks"]} == {1001, 2002}
    assert {item["category"] for item in dataset["chunks"]} == {
        "project",
        "resume",
        "other",
    }
    tags = {tag for case in dataset["queries"] for tag in case["tags"]}
    assert {
        "exact",
        "synonym",
        "mixed",
        "chinese_no_space",
        "similar_project",
        "negation",
        "keyword_stuffing",
        "filename",
        "duplicate",
        "near_duplicate",
        "isolation",
        "category",
        "empty",
    } <= tags


def test_default_cli_does_not_run_real_calibration(monkeypatch, capsys):
    from evals import run_retrieval_calibration

    monkeypatch.setattr(
        retrieval_calibration,
        "run_real_calibration",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("默认模式不得运行真实校准")
        ),
    )
    assert run_retrieval_calibration.main([]) == 0
    assert "默认关闭" in capsys.readouterr().out


def test_cache_check_is_read_only_and_does_not_disclose_paths(monkeypatch, capsys):
    from evals import run_retrieval_calibration

    monkeypatch.setattr(
        retrieval_calibration,
        "model_cache_status",
        lambda: {
            "model_id": "BAAI/bge-small-zh-v1.5",
            "cache_found": True,
            "offline_loading_allowed": True,
            "network_disabled": True,
            "download_will_be_attempted": False,
            "calibration_runnable": True,
        },
    )
    assert run_retrieval_calibration.main(["--check-model-cache"]) == 0
    output = capsys.readouterr().out
    assert "BAAI/bge-small-zh-v1.5" in output
    assert "Users" not in output
    assert "cache\\" not in output
    assert "secret" not in output.casefold()
    assert "token" not in output.casefold()


def test_missing_cache_skips_without_network_or_model_load(monkeypatch, tmp_path):
    monkeypatch.setattr(retrieval_calibration, "_resolve_cached_snapshot", lambda *args: None)
    original_connect = socket.socket.connect
    summary, output_dir = retrieval_calibration.run_real_calibration(tmp_path)
    assert socket.socket.connect is original_connect
    assert summary["status"] == "skipped_model_cache_missing"
    assert summary["download_attempted"] is False
    assert (output_dir / "summary.json").exists()
    assert "未发起网络下载" in (output_dir / "report.md").read_text(encoding="utf-8")


def test_sqlite_ownership_validation_uses_one_batch_query(tmp_path):
    connection = sqlite3.connect(tmp_path / "calibration.sqlite3")
    connection.execute(
        "CREATE TABLE files (file_id TEXT PRIMARY KEY, user_id INTEGER, filename TEXT, category TEXT)"
    )
    connection.executemany(
        "INSERT INTO files VALUES (?, ?, ?, ?)",
        [("a", 1001, "甲.md", "project"), ("b", 2002, "乙.md", "project")],
    )
    statements = []
    connection.set_trace_callback(statements.append)
    candidates = [
        {"content": "甲", "distance": 0.1, "metadata": {"user_id": 1001, "file_id": "a", "chunk_index": 0}},
        {"content": "乙", "distance": 0.2, "metadata": {"user_id": 1001, "file_id": "b", "chunk_index": 0}},
    ]
    owned, names, metadata_filtered, ownership_filtered = _verify_owned_candidates(
        connection, candidates, 1001
    )
    assert [item["metadata"]["file_id"] for item in owned] == ["a"]
    assert names == {"a": "甲.md"}
    assert metadata_filtered == 0
    assert ownership_filtered == 1
    assert sum(statement.startswith("SELECT") for statement in statements) == 1
    connection.close()


def test_distance_and_ranking_metrics_are_calculated_correctly():
    rows = [
        _metric_row(
            {"vector": ["noise", "a"], "lexical": ["a"], "final": ["a"]},
            ["a"],
        ),
        _metric_row(
            {"vector": [], "lexical": [], "final": []},
            [],
        ),
    ]
    metrics = _strategy_metrics(rows, "vector")
    assert metrics["recall_at_1"] == 0
    assert metrics["recall_at_3"] == 1
    assert metrics["mrr"] == 0.5
    assert metrics["precision_at_3"] == 1 / 6
    assert metrics["empty_result_accuracy"] == 1
    assert _precision_at_k(["a", "noise"], {"a"}, 3) == 1 / 3


def test_distance_distribution_percentiles_false_rates_and_overlap():
    rows = [{"distance_overlap": True}, {"distance_overlap": False}]
    summary = _distance_summary(
        [0.1, 0.2, 0.9],
        [0.15, 0.8, 1.2],
        rows,
        false_reject_count=1,
        relevant_pair_count=3,
        false_accept_count=2,
        obvious_pair_count=4,
    )
    assert summary["relevant"] == {"min": 0.1, "p50": 0.2, "p95": 0.9, "count": 3}
    assert summary["irrelevant"] == {"min": 0.15, "p50": 0.8, "p95": 1.2, "count": 3}
    assert summary["overlap_case_count"] == 1
    assert summary["false_reject_rate"] == 1 / 3
    assert summary["false_accept_rate"] == 0.5


def test_squared_l2_smaller_distance_is_more_relevant():
    import chromadb

    collection = chromadb.EphemeralClient().create_collection("calibration_distance_test")
    collection.add(
        ids=["same", "orthogonal"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        documents=["相同", "正交"],
    )
    result = collection.query(
        query_embeddings=[[1.0, 0.0]],
        n_results=2,
        include=["distances"],
    )
    assert result["ids"][0] == ["same", "orthogonal"]
    assert result["distances"][0] == [0.0, 2.0]


def test_distance_threshold_precedes_lexical_score():
    chunks = [
        {"source_id": "far:0", "content": "Kubernetes Kubernetes", "distance": 0.81, "metadata": {"file_id": "far", "category": "project", "chunk_index": 0}},
        {"source_id": "near:0", "content": "项目部署说明", "distance": 0.2, "metadata": {"file_id": "near", "category": "project", "chunk_index": 0}},
    ]
    ranked = _lexical_rank(
        "Kubernetes",
        chunks,
        top_k=3,
        distance_threshold=0.8,
        trusted_file_names={},
        allowed_categories={"project", "resume"},
    )
    assert [item["source_id"] for item in ranked] == ["near:0"]


def test_parameter_comparison_does_not_mutate_production_constants():
    chunks = [
        {"source_id": "a:0", "content": "FastAPI", "distance": 0.1, "metadata": {"file_id": "a", "category": "project", "chunk_index": 0}},
        {"source_id": "b:0", "content": "无关", "distance": 0.2, "metadata": {"file_id": "b", "category": "project", "chunk_index": 0}},
    ]
    row = {
        "query": "FastAPI",
        "relevant_source_ids": ["a:0"],
        "obvious_irrelevant_source_ids": ["b:0"],
        "all_owned_chunks": chunks,
        "trusted_file_names": {},
    }
    before = (
        retrieval_calibration.DISTANCE_THRESHOLD,
        retrieval_calibration.CANDIDATE_MULTIPLIER,
        retrieval_calibration.MAX_CANDIDATES,
    )
    comparison = _parameter_comparison([row])
    assert len(comparison) == 7
    assert all("false_accept_count" in item for item in comparison)
    assert before == (
        retrieval_calibration.DISTANCE_THRESHOLD,
        retrieval_calibration.CANDIDATE_MULTIPLIER,
        retrieval_calibration.MAX_CANDIDATES,
    )


def test_full_calibration_uses_temporary_chroma_and_sqlite(monkeypatch, tmp_path):
    import chromadb
    import sentence_transformers

    class FakeSentenceTransformer:
        def __init__(self, model_path, local_files_only=False):
            assert local_files_only is True
            assert str(tmp_path) in model_path

        def encode(self, texts, **kwargs):
            vectors = []
            for text in texts:
                values = np.array(
                    [
                        (sum(text.encode("utf-8")) + index * 17) % 97 + 1
                        for index in range(8)
                    ],
                    dtype=float,
                )
                vectors.append(values / np.linalg.norm(values))
            return np.array(vectors)

    original_client = chromadb.PersistentClient
    observed = {}

    def temporary_client(path, settings):
        observed["chroma_path"] = Path(path)
        return original_client(path=path, settings=settings)

    snapshot = tmp_path / "cached-model"
    snapshot.mkdir()
    monkeypatch.setattr(retrieval_calibration, "_resolve_cached_snapshot", lambda *args: snapshot)
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", FakeSentenceTransformer)
    monkeypatch.setattr(chromadb, "PersistentClient", temporary_client)
    summary, output_dir = retrieval_calibration.run_real_calibration(tmp_path / "results")
    assert summary["status"] == "completed"
    assert summary["isolation"]["production_paths_accessed"] is False
    assert summary["isolation"]["real_user_data_used"] is False
    assert summary["isolation"]["deepseek_called"] is False
    assert summary["isolation"]["tavily_called"] is False
    assert not observed["chroma_path"].exists()
    assert (output_dir / "summary.json").exists()
    report_payload = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert "cached-model" not in json.dumps(report_payload)
