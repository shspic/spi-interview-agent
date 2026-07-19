import subprocess
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from evals.config import BASELINE_THRESHOLDS
from evals.loaders import load_cases
from evals.metrics import accuracy, mean, percentile
from evals.reporters import create_result_dir, write_reports
from evals.schemas import (
    BaselineCheck,
    CaseResult,
    GroupResult,
    RunSummary,
)


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _aggregate_metrics(results: list[CaseResult]) -> dict[str, float | int]:
    retrieval = [item for item in results if item.group == "retrieval"]
    rerank_latencies = [
        float(item.metrics.get("rerank_latency_ms", 0))
        for item in retrieval
    ]
    evidence = [item for item in results if item.group == "evidence"]
    supervisor = [item for item in results if item.group == "supervisor"]
    evaluation = [item for item in results if item.group == "evaluation"]
    security = [item for item in results if item.group == "security"]
    structured = [
        item
        for item in results
        if item.group in {"evaluation", "improvement", "resume", "reliability"}
        and "controlled_failure" in item.metrics
    ]
    prompt_injection = [
        item for item in results if "prompt_injection" in item.case_id
    ]
    return {
        "cross_user_leakage_count": sum(
            int(item.metrics.get("forbidden_hit_count", 0)) for item in results
        ),
        "invalid_evidence_source_count": sum(
            int(item.metrics.get("source_ids_valid") is False) for item in results
        ),
        "total_score_error_count": sum(
            int(item.metrics.get("total_score_correct") is False)
            + int(item.metrics.get("total_score_error") is True)
            for item in results
        ),
        "follow_up_limit_violation_count": sum(
            int(item.metrics.get("follow_up_limit_violation") is True)
            for item in results
        ),
        "duplicate_charge_count": sum(
            int(item.metrics.get("duplicate_charge_count", 0)) for item in results
        ),
        "orphan_record_count": sum(
            int(item.metrics.get("orphan_record_count", 0)) for item in results
        ),
        "uncaught_exception_count": sum(
            int(item.error_type is not None) for item in results
        ),
        "structured_output_success_rate": accuracy(
            item.status == "passed" for item in structured
        ),
        "retrieval_recall_at_3": mean(
            float(item.metrics.get("recall_at_3", 0)) for item in retrieval
        ),
        "retrieval_recall_at_1": mean(
            float(item.metrics.get("recall_at_1", 0)) for item in retrieval
        ),
        "retrieval_recall_at_5": mean(
            float(item.metrics.get("recall_at_5", 0)) for item in retrieval
        ),
        "retrieval_mrr": mean(
            float(item.metrics.get("mrr", 0)) for item in retrieval
        ),
        "retrieval_irrelevant_ratio": mean(
            float(item.metrics.get("irrelevant_ratio", 0))
            for item in retrieval
        ),
        "retrieval_duplicate_ratio": mean(
            float(item.metrics.get("duplicate_ratio", 0))
            for item in retrieval
        ),
        "retrieval_average_candidate_pool_size": mean(
            float(item.metrics.get("candidate_pool_size", 0))
            for item in retrieval
        ),
        "retrieval_max_candidate_pool_size": max(
            (
                int(item.metrics.get("candidate_pool_size", 0))
                for item in retrieval
            ),
            default=0,
        ),
        "retrieval_average_final_result_size": mean(
            float(item.metrics.get("final_result_size", 0))
            for item in retrieval
        ),
        "retrieval_distance_filtered_count": sum(
            int(item.metrics.get("distance_filtered_count", 0))
            for item in retrieval
        ),
        "retrieval_ownership_filtered_count": sum(
            int(item.metrics.get("ownership_filtered_count", 0))
            + int(item.metrics.get("metadata_filtered_count", 0))
            for item in retrieval
        ),
        "retrieval_deduplicated_count": sum(
            int(item.metrics.get("duplicate_filtered_count", 0))
            for item in retrieval
        ),
        "retrieval_sort_instability_count": sum(
            int(item.metrics.get("ordering_stable") is False)
            for item in retrieval
        ),
        "retrieval_rerank_p50_ms": percentile(rerank_latencies, 50),
        "retrieval_rerank_p95_ms": percentile(rerank_latencies, 95),
        "retrieval_rerank_max_ms": round(max(rerank_latencies, default=0), 6),
        "evidence_sufficiency_accuracy": accuracy(
            item.metrics.get("sufficiency_correct") is True for item in evidence
        ),
        "supervisor_decision_accuracy": accuracy(
            item.metrics.get("decision_correct") is True for item in supervisor
        ),
        "conflict_detection_accuracy": accuracy(
            item.metrics.get("conflict_detection_correct") is True
            for item in evaluation
            if "conflict_detection_correct" in item.metrics
        ),
        "unsupported_number_block_rate": accuracy(
            item.status == "passed"
            for item in security
            if "number" in item.case_id
        ),
        "unsupported_technology_block_rate": accuracy(
            item.status == "passed"
            for item in security
            if "technology" in item.case_id
        ),
        "prompt_injection_case_count": len(prompt_injection),
        "prompt_injection_blocked_count": sum(
            item.status == "passed" for item in prompt_injection
        ),
        "prompt_injection_unsafe_behavior_count": sum(
            item.status == "failed" for item in prompt_injection
        ),
        "structured_output_retry_rate": accuracy(
            item.metrics.get("retried") is True for item in structured
        ),
        "controlled_failure_rate": accuracy(
            item.metrics.get("controlled_failure") is True for item in structured
        ),
    }


def _baseline_checks(metrics: dict[str, float | int]) -> list[BaselineCheck]:
    checks = []
    for name, (operator, threshold) in BASELINE_THRESHOLDS.items():
        actual = metrics.get(name)
        if actual is None:
            checks.append(
                BaselineCheck(
                    metric=name,
                    operator=operator,
                    threshold=threshold,
                    actual=None,
                    passed=False,
                    reason="当前评估集尚未提供该指标，不能视为通过",
                )
            )
            continue
        passed = actual >= threshold if operator == "min" else actual <= threshold
        checks.append(
            BaselineCheck(
                metric=name,
                operator=operator,
                threshold=threshold,
                actual=float(actual),
                passed=passed,
                reason="达到门槛" if passed else "未达到门槛",
            )
        )
    return checks


def _group_results(results: list[CaseResult]) -> list[GroupResult]:
    grouped = defaultdict(list)
    for result in results:
        grouped[result.group].append(result)
    output = []
    for group, items in sorted(grouped.items()):
        durations = [item.duration_ms for item in items]
        passed = sum(item.status == "passed" for item in items)
        failed = sum(item.status == "failed" for item in items)
        skipped = sum(item.status == "skipped" for item in items)
        metric_values = defaultdict(list)
        for item in items:
            for name, value in item.metrics.items():
                if isinstance(value, bool):
                    metric_values[name].append(int(value))
                elif isinstance(value, (int, float)):
                    metric_values[name].append(float(value))
        group_metrics = {
            name: (
                round(sum(values), 6)
                if name.endswith("_count")
                else round(mean(values), 6)
            )
            for name, values in metric_values.items()
        }
        output.append(
            GroupResult(
                group=group,
                total=len(items),
                passed=passed,
                failed=failed,
                skipped=skipped,
                success_rate=passed / len(items),
                p50_ms=percentile(durations, 50),
                p95_ms=percentile(durations, 95),
                max_ms=round(max(durations, default=0), 3),
                metrics=group_metrics,
                failed_case_ids=[
                    item.case_id for item in items if item.status == "failed"
                ],
            )
        )
    return output


def run_evaluations(
    groups: set[str] | None,
    output_base: Path,
    mode: str = "mock",
) -> tuple[RunSummary, list[CaseResult], Path]:
    from evals.adapters import run_case

    cases = load_cases(groups)
    started = datetime.now().astimezone()
    results = []
    uncaught = 0
    for case in cases:
        started_case = time.perf_counter()
        try:
            passed, reason, metrics = run_case(case)
            status = "passed" if passed else "failed"
            error_type = None
        except Exception as exc:
            status = "failed"
            reason = f"未捕获异常：{type(exc).__name__}"
            metrics = {}
            error_type = type(exc).__name__
            uncaught += 1
        results.append(
            CaseResult(
                case_id=case.id,
                group=case.group,
                status=status,
                duration_ms=round(
                    (time.perf_counter() - started_case) * 1000,
                    3,
                ),
                reason=reason,
                metrics=metrics,
                error_type=error_type,
            )
        )
    finished = datetime.now().astimezone()
    aggregate = _aggregate_metrics(results)
    aggregate["uncaught_exception_count"] = uncaught
    checks = _baseline_checks(aggregate)
    run_id = started.strftime("%Y-%m-%dT%H%M%S-%f")
    summary = RunSummary(
        run_id=run_id,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        git_commit=_git_commit(),
        mode=mode,
        selected_groups=sorted(groups) if groups else sorted({c.group for c in cases}),
        total=len(results),
        passed=sum(item.status == "passed" for item in results),
        failed=sum(item.status == "failed" for item in results),
        skipped=sum(item.status == "skipped" for item in results),
        uncaught_exception_count=uncaught,
        structured_retry_count=sum(
            int(item.metrics.get("retried") is True) for item in results
        ),
        overall_metrics=aggregate,
        groups=_group_results(results),
        baseline_checks=checks,
        baseline_passed=all(item.passed for item in checks),
        limitations=[
            "默认使用固定 Mock LLM、固定检索排序和临时 SQLite，不衡量真实模型语义质量。",
            "Mock 模式延迟不能外推到 DeepSeek、BGE、Chroma 生产数据或 Tavily。",
            "Prompt Injection 只测结构化边界和后端语义校验，不能替代真实模型红队测试。",
        ],
    )
    output_dir = create_result_dir(output_base, run_id)
    write_reports(output_dir, summary, results)
    return summary, results, output_dir
