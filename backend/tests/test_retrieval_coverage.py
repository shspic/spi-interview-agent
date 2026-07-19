import hashlib
import json
from pathlib import Path

import pytest

from evals import retrieval_coverage


@pytest.mark.parametrize(
    ("dataset_name", "query_count", "chunk_count"),
    [
        ("development", 30, 50),
        ("validation", 25, 45),
        ("holdout", 25, 45),
    ],
)
def test_coverage_datasets_load_with_frozen_hashes(
    dataset_name,
    query_count,
    chunk_count,
):
    payload, entry = retrieval_coverage.load_coverage_dataset(dataset_name)
    assert len(payload["queries"]) == query_count
    assert len(payload["chunks"]) == chunk_count
    assert entry["frozen_before_production_changes"] is True


def test_coverage_case_ids_are_unique_and_facet_sources_exist():
    for dataset_name in retrieval_coverage.COVERAGE_DATASET_PATHS:
        payload, _entry = retrieval_coverage.load_coverage_dataset(dataset_name)
        case_ids = [item["id"] for item in payload["queries"]]
        source_ids = {
            f"{item['file_id']}:{item['chunk_index']}"
            for item in payload["chunks"]
        }
        assert len(case_ids) == len(set(case_ids))
        assert all(
            set(sources) <= source_ids
            for case in payload["queries"]
            for sources in case["facet_source_ids"].values()
        )


def test_coverage_sets_do_not_repeat_each_other_or_old_sets():
    result = retrieval_coverage.verify_dataset_discipline()
    assert result["dataset_count"] == 3
    assert result["query_count"] == 80
    assert result["intentional_duplicate_pair_count"] == 3


def test_fixture_change_breaks_manifest_hash(tmp_path, monkeypatch):
    original = retrieval_coverage.COVERAGE_DATASET_PATHS["development"]
    modified = tmp_path / "coverage_development_cases.json"
    modified.write_bytes(original.read_bytes() + b"\n")
    monkeypatch.setitem(
        retrieval_coverage.COVERAGE_DATASET_PATHS,
        "development",
        modified,
    )
    with pytest.raises(ValueError, match="SHA-256"):
        retrieval_coverage.load_coverage_dataset("development")


def test_holdout_cannot_run_before_final_flag():
    with pytest.raises(ValueError, match="只能在生产冻结后"):
        retrieval_coverage.run_coverage_evaluation(
            dataset_name="holdout",
            final_holdout=False,
        )


def test_production_freeze_detects_file_change_and_completed_marker(
    tmp_path,
):
    backend_root = Path(retrieval_coverage.__file__).resolve().parents[1]
    production_file = backend_root / "app" / "services" / "retrieval_query_analysis.py"
    payload = {
        "final_holdout_frozen": True,
        "formal_run_completed": False,
        "network_disabled": True,
        "dataset_manifest_sha256": hashlib.sha256(
            retrieval_coverage.COVERAGE_MANIFEST_PATH.read_bytes()
        ).hexdigest(),
        "production_files": [
            {
                "path": "app/services/retrieval_query_analysis.py",
                "sha256": hashlib.sha256(production_file.read_bytes()).hexdigest(),
            }
        ],
    }
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps(payload), encoding="utf-8")
    result = retrieval_coverage.verify_coverage_production_freeze(
        freeze_path,
        require_not_completed=True,
    )
    assert result["final_holdout_frozen"] is True

    payload["formal_run_completed"] = True
    freeze_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="已完成正式运行"):
        retrieval_coverage.verify_coverage_production_freeze(
            freeze_path,
            require_not_completed=True,
        )

    payload["formal_run_completed"] = False
    payload["production_files"][0]["sha256"] = "0" * 64
    freeze_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="生产冻结文件已变化"):
        retrieval_coverage.verify_coverage_production_freeze(freeze_path)
