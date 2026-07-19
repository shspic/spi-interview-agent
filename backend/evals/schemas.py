from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvalCase(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]+$")
    group: str
    description: str = Field(min_length=1, max_length=500)
    input: dict[str, Any]
    expected: dict[str, Any]
    tags: list[str] = Field(default_factory=list)


class CaseResult(StrictModel):
    case_id: str
    group: str
    status: Literal["passed", "failed", "skipped"]
    duration_ms: float = Field(ge=0)
    reason: str
    metrics: dict[str, float | int | bool | str | None] = Field(
        default_factory=dict
    )
    error_type: str | None = None


class GroupResult(StrictModel):
    group: str
    total: int
    passed: int
    failed: int
    skipped: int
    success_rate: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    metrics: dict[str, float | int | bool | str | None]
    failed_case_ids: list[str]


class BaselineCheck(StrictModel):
    metric: str
    operator: Literal["min", "max"]
    threshold: float
    actual: float | None
    passed: bool
    reason: str


class RunSummary(StrictModel):
    run_id: str
    started_at: str
    finished_at: str
    git_commit: str
    mode: Literal["mock", "real-model"]
    selected_groups: list[str]
    total: int
    passed: int
    failed: int
    skipped: int
    uncaught_exception_count: int
    structured_retry_count: int
    overall_metrics: dict[str, float | int | bool | str | None]
    groups: list[GroupResult]
    baseline_checks: list[BaselineCheck]
    baseline_passed: bool
    limitations: list[str]
