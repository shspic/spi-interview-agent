import argparse
import json
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.adapters import isolated_db
from evals.config import FIXTURE_DIR, configure_isolated_environment
from evals.loaders import load_cases
from evals.metrics import accuracy, percentile, recall_at_k, reciprocal_rank
from evals.reporters import create_result_dir, write_json
from evals.run_evals import validate_real_model_args
from evals.schemas import EvalCase


def test_fixtures_and_cases_load_with_expected_coverage():
    cases = load_cases()
    assert len(cases) == 69
    assert {case.group for case in cases} == {
        "retrieval",
        "evidence",
        "evaluation",
        "supervisor",
        "improvement",
        "resume",
        "security",
        "reliability",
    }
    fixture_names = {
        path.name for path in FIXTURE_DIR.rglob("*") if path.is_file()
    }
    assert {
        "project_a_rag.md",
        "project_b_data_agent.md",
        "project_c_backend.md",
        "prompt_injection.md",
    } <= fixture_names


def test_invalid_fixture_is_rejected(tmp_path):
    (tmp_path / "bad_cases.json").write_text(
        json.dumps(
            [
                {
                    "id": "bad_case",
                    "group": "retrieval",
                    "description": "非法字段",
                    "input": {},
                    "expected": {},
                    "unexpected": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_cases({"retrieval"}, tmp_path)


def test_retrieval_metrics_are_deterministic():
    ranked = ["noise", "source-a", "source-b"]
    relevant = {"source-a", "source-b"}
    assert recall_at_k(ranked, relevant, 1) == 0
    assert recall_at_k(ranked, relevant, 3) == 1
    assert reciprocal_rank(ranked, relevant) == 0.5
    assert accuracy([True, False, True, True]) == 0.75


def test_latency_percentiles_use_nearest_rank():
    values = [1, 2, 3, 4, 100]
    assert percentile(values, 50) == 3
    assert percentile(values, 95) == 100
    assert percentile([], 95) == 0


def test_result_directory_never_overwrites(tmp_path):
    first = create_result_dir(tmp_path, "fixed-run")
    second = create_result_dir(tmp_path, "fixed-run")
    assert first != second
    assert first.name == "fixed-run"
    assert second.name == "fixed-run-1"


def test_json_report_redacts_sensitive_keys(tmp_path):
    path = tmp_path / "summary.json"
    write_json(
        path,
        {
            "password": "fixture-password-value",
            "jwt_token": "fixture-token-value",
            "system_prompt": "fixture-system-prompt",
            "prompt_injection_case_count": 6,
            "prompt_version": "fixture-version",
            "safe": "可公开摘要",
        },
    )
    text = path.read_text(encoding="utf-8")
    assert "fixture-password-value" not in text
    assert "fixture-token-value" not in text
    assert "fixture-system-prompt" not in text
    assert '"prompt_injection_case_count": 6' in text
    assert '"prompt_version": "fixture-version"' in text
    assert "可公开摘要" in text


def test_single_case_exception_does_not_stop_group(monkeypatch, tmp_path):
    from evals import adapters, runner

    cases = [
        EvalCase(
            id="case_failure",
            group="retrieval",
            description="抛出异常",
            input={},
            expected={},
        ),
        EvalCase(
            id="case_success",
            group="retrieval",
            description="继续运行",
            input={},
            expected={},
        ),
    ]
    monkeypatch.setattr(runner, "load_cases", lambda groups: cases)

    def fake_run(case):
        if case.id == "case_failure":
            raise RuntimeError("fixture failure")
        return True, "通过", {"recall_at_3": 1.0}

    monkeypatch.setattr(adapters, "run_case", fake_run)
    summary, results, _ = runner.run_evaluations(None, tmp_path)
    assert summary.total == 2
    assert summary.uncaught_exception_count == 1
    assert [item.status for item in results] == ["failed", "passed"]


def test_group_filter_only_loads_selected_group():
    cases = load_cases({"supervisor"})
    assert len(cases) == 8
    assert all(case.group == "supervisor" for case in cases)


def test_mock_retrieval_group_does_not_access_network(monkeypatch, tmp_path):
    from evals.runner import run_evaluations

    def block_network(*args, **kwargs):
        raise AssertionError("评估 Mock 模式禁止网络访问")

    monkeypatch.setattr(socket.socket, "connect", block_network)
    summary, _, output_dir = run_evaluations({"retrieval"}, tmp_path)
    assert summary.total == 8
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "cases.json").exists()
    assert (output_dir / "report.md").exists()


def test_real_model_requires_explicit_switch_and_limits(monkeypatch):
    args = argparse.Namespace(
        real_model=True,
        max_cases=5,
        max_model_calls=10,
    )
    monkeypatch.delenv("EVAL_REAL_MODEL_ENABLED", raising=False)
    with pytest.raises(SystemExit, match="显式设置"):
        validate_real_model_args(args)
    monkeypatch.setenv("EVAL_REAL_MODEL_ENABLED", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-key-not-used")
    args.max_cases = 6
    with pytest.raises(SystemExit, match="最多运行 5"):
        validate_real_model_args(args)


def test_evaluation_database_is_temporary_and_isolated():
    with isolated_db() as (_, database_path):
        assert database_path.exists()
        assert "spi-eval-db-" in str(database_path)
    assert not database_path.exists()


def test_configure_environment_uses_only_temporary_paths(monkeypatch, tmp_path):
    for key in ["SQLITE_DB_PATH", "UPLOAD_DIR", "CHROMA_PERSIST_DIR"]:
        monkeypatch.delenv(key, raising=False)
    configure_isolated_environment(tmp_path)
    assert Path(str(tmp_path / "eval.sqlite3")) == Path(
        __import__("os").environ["SQLITE_DB_PATH"]
    )
    assert __import__("os").environ["SKIP_DOTENV"] == "1"
