import json
import re
from pathlib import Path
from typing import Any

from evals.schemas import CaseResult, RunSummary


SENSITIVE_KEY_PATTERN = re.compile(
    r"password|token|secret|invite|api[_-]?key|prompt|authorization",
    re.IGNORECASE,
)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE_KEY_PATTERN.search(key) else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def create_result_dir(base_dir: Path, run_id: str) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = base_dir / run_id
    suffix = 1
    while candidate.exists():
        candidate = base_dir / f"{run_id}-{suffix}"
        suffix += 1
    candidate.mkdir()
    return candidate


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_sanitize(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def render_markdown(summary: RunSummary, cases: list[CaseResult]) -> str:
    failed = [item for item in cases if item.status == "failed"]
    lines = [
        "# SPI 面试 Agent 自动化评估报告",
        "",
        f"- 运行 ID：`{summary.run_id}`",
        f"- Git Commit：`{summary.git_commit}`",
        f"- 模式：`{summary.mode}`",
        f"- Case：{summary.total}（通过 {summary.passed} / 失败 {summary.failed} / 跳过 {summary.skipped}）",
        f"- 基线门槛：{'通过' if summary.baseline_passed else '未通过'}",
        "",
        "> Mock 延迟仅反映本地确定性代码和固定 Mock 的开销，不代表真实模型性能。",
        "",
        "## 分组结果",
        "",
        "| 分组 | 通过/总数 | 成功率 | P50(ms) | P95(ms) | 最大(ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group in summary.groups:
        lines.append(
            f"| {group.group} | {group.passed}/{group.total} | "
            f"{group.success_rate:.1%} | {group.p50_ms:.3f} | "
            f"{group.p95_ms:.3f} | {group.max_ms:.3f} |"
        )
    lines.extend(["", "## 全局指标", ""])
    for name, value in summary.overall_metrics.items():
        lines.append(f"- `{name}`：{value}")
    lines.extend(["", "## 基线门槛", ""])
    for check in summary.baseline_checks:
        actual = "未测量" if check.actual is None else f"{check.actual:.4g}"
        lines.append(
            f"- [{'x' if check.passed else ' '}] `{check.metric}`："
            f"{actual}，要求 {check.operator} {check.threshold:g}。{check.reason}"
        )
    lines.extend(["", "## 失败 Case", ""])
    if failed:
        for item in failed:
            lines.append(f"- `{item.case_id}`：{item.reason}")
    else:
        lines.append("- 无。")
    lines.extend(["", "## 已知局限", ""])
    lines.extend(f"- {item}" for item in summary.limitations)
    lines.append("")
    return "\n".join(lines)


def write_reports(
    output_dir: Path,
    summary: RunSummary,
    cases: list[CaseResult],
) -> None:
    write_json(output_dir / "summary.json", summary.model_dump(mode="json"))
    write_json(
        output_dir / "cases.json",
        [item.model_dump(mode="json") for item in cases],
    )
    (output_dir / "report.md").write_text(
        render_markdown(summary, cases),
        encoding="utf-8",
    )
