import json
import hashlib
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
    _target_assessment,
    _verify_owned_candidates,
    load_dataset,
    load_frozen_dataset,
    verify_production_freeze,
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


def test_validation_and_holdout_datasets_match_frozen_manifest():
    development, development_entry = load_frozen_dataset("development")
    validation, validation_entry = load_frozen_dataset("validation")
    holdout, holdout_entry = load_frozen_dataset("holdout")
    assert (len(validation["queries"]), len(validation["chunks"])) == (25, 42)
    assert (len(holdout["queries"]), len(holdout["chunks"])) == (25, 42)
    case_id_sets = [
        {item["id"] for item in dataset["queries"]}
        for dataset in (development, validation, holdout)
    ]
    assert not (case_id_sets[0] & case_id_sets[1])
    assert not (case_id_sets[0] & case_id_sets[2])
    assert not (case_id_sets[1] & case_id_sets[2])
    assert development_entry["sha256"] == hashlib.sha256(
        retrieval_calibration.DATASET_PATH.read_bytes()
    ).hexdigest()
    assert validation_entry["role"] == "validation_selection"
    assert holdout_entry["may_influence_tuning"] is False


def test_frozen_dataset_hash_mismatch_fails_closed(monkeypatch, tmp_path):
    tampered = tmp_path / "validation.json"
    tampered.write_bytes(retrieval_calibration.VALIDATION_DATASET_PATH.read_bytes() + b" ")
    monkeypatch.setitem(retrieval_calibration.DATASET_PATHS, "validation", tampered)
    try:
        with np.testing.assert_raises_regex(ValueError, "SHA-256"):
            load_frozen_dataset("validation")
    finally:
        monkeypatch.setitem(
            retrieval_calibration.DATASET_PATHS,
            "validation",
            retrieval_calibration.VALIDATION_DATASET_PATH,
        )


def test_invalid_expected_structure_is_rejected(tmp_path):
    payload = json.loads(retrieval_calibration.VALIDATION_DATASET_PATH.read_text(encoding="utf-8"))
    payload["queries"][0]["relevant_source_ids"] = "not-a-list"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with np.testing.assert_raises_regex(ValueError, "relevant_source_ids"):
        load_dataset(path)


def test_production_freeze_detects_file_changes(monkeypatch, tmp_path):
    backend_root = Path(retrieval_calibration.__file__).resolve().parents[1]
    target = backend_root / "tests" / "test_retrieval_calibration.py"
    payload = {
        "final_holdout_frozen": True,
        "dataset_manifest_sha256": hashlib.sha256(
            retrieval_calibration.DATASET_MANIFEST_PATH.read_bytes()
        ).hexdigest(),
        "production_files": [
            {"path": "tests/test_retrieval_calibration.py", "sha256": "0" * 64}
        ],
    }
    marker = tmp_path / "freeze.json"
    marker.write_text(json.dumps(payload), encoding="utf-8")
    with np.testing.assert_raises_regex(ValueError, "已变化"):
        verify_production_freeze(marker)
    payload["production_files"][0]["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    marker.write_text(json.dumps(payload), encoding="utf-8")
    assert verify_production_freeze(marker)["final_holdout_frozen"] is True


def test_holdout_requires_baseline_or_frozen_final(monkeypatch):
    from evals import run_retrieval_calibration

    with np.testing.assert_raises(SystemExit):
        run_retrieval_calibration.main(["--real-embedding", "--dataset", "holdout"])
    monkeypatch.setattr(
        retrieval_calibration,
        "verify_production_freeze",
        lambda: {"freeze_sha256": "freeze-hash"},
    )
    observed = {}

    def fake_run(*args, **kwargs):
        observed.update(kwargs)
        return ({"status": "completed", "query_count": 25, "chunk_count": 42}, Path("result"))

    monkeypatch.setattr(retrieval_calibration, "run_real_calibration", fake_run)
    assert run_retrieval_calibration.main(
        ["--real-embedding", "--dataset", "holdout", "--final-holdout"]
    ) == 0
    assert observed["evaluation_stage"] == "final_frozen_holdout"
    assert observed["suppress_case_details"] is False
    assert observed["final_holdout_frozen"] is True


def test_failed_holdout_targets_are_not_reported_as_passed():
    assessment = _target_assessment(
        {
            "no_answer_accuracy": 1.0,
            "false_reject_rate": 0.25,
            "false_accept_rate": 0.05,
            "recall_at_3": 0.70,
            "precision_at_3": 0.20,
            "mrr": 0.79,
        },
        final_holdout_frozen=True,
    )
    assert assessment["passed"] is False
    assert assessment["checks"]["recall_at_3_gte_0_80"] is False


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
