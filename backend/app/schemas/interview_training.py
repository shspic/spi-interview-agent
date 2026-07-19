from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.schemas import InterviewPlanOutput, SupervisorDecisionOutput
from app.core.config import settings
from app.core.input_validation import validate_identifier_text, validate_safe_text

InterviewMode = Literal["quick", "standard", "deep_dive"]
InterviewStatus = Literal["draft", "in_progress", "completed", "cancelled"]
ImprovementCategory = Literal[
    "technical",
    "project_evidence",
    "answer_depth",
    "expression",
    "job_match",
    "resume",
]
ImprovementPriority = Literal["low", "medium", "high"]
ImprovementStatus = Literal["pending", "completed"]
ImprovementGenerationStatus = Literal[
    "pending",
    "generating",
    "completed",
    "failed",
]


class InterviewSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    mode: InterviewMode
    target_job_id: int | None = Field(default=None, gt=0)
    selected_project_file_ids: list[str] = Field(default_factory=list, max_length=20)
    previous_session_id: int | None = Field(default=None, gt=0)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = validate_identifier_text(
            value,
            field_name="面试标题",
            max_chars=200,
        )
        if not normalized:
            raise ValueError("面试标题不能为空")
        return normalized

    @field_validator("selected_project_file_ids")
    @classmethod
    def normalize_file_ids(cls, values: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for value in values:
            file_id = value.strip()
            validate_identifier_text(
                file_id,
                field_name="项目文件 ID",
                max_chars=64,
            )
            if not file_id:
                raise ValueError("项目文件 ID 不能为空")
            if file_id not in seen:
                normalized.append(file_id)
                seen.add(file_id)
        return normalized


class InterviewSessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    target_job_id: int | None = Field(default=None, gt=0)
    selected_project_file_ids: list[str] | None = Field(
        default=None,
        max_length=20,
    )
    previous_session_id: int | None = Field(default=None, gt=0)

    @field_validator("title")
    @classmethod
    def normalize_optional_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = validate_identifier_text(
            value,
            field_name="面试标题",
            max_chars=200,
        )
        if not normalized:
            raise ValueError("面试标题不能为空")
        return normalized

    @field_validator("selected_project_file_ids")
    @classmethod
    def normalize_optional_file_ids(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return InterviewSessionCreate.normalize_file_ids(values)


class ImprovementTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ImprovementStatus


class InterviewAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: int = Field(gt=0)
    answer: str = Field(min_length=1, max_length=50000)

    @field_validator("answer")
    @classmethod
    def normalize_answer(cls, value: str) -> str:
        normalized = validate_safe_text(
            value,
            field_name="面试回答",
            max_chars=settings.max_interview_answer_chars,
            strip=True,
        )
        if not normalized:
            raise ValueError("回答不能为空")
        return normalized


class TargetJobSummary(BaseModel):
    id: int
    job_title: str
    company_name: str
    is_active: bool


class ProjectFileSummary(BaseModel):
    file_id: str
    filename: str
    file_type: str
    category: str


class PreviousSessionSummary(BaseModel):
    id: int
    title: str
    mode: InterviewMode
    overall_score: float | None
    completed_at: str | None


class InterviewTurnResponse(BaseModel):
    id: int
    session_id: int
    sequence_number: int
    main_question_number: int
    follow_up_number: int
    parent_turn_id: int | None
    question: str
    question_type: Literal["main", "follow_up"]
    user_answer: str | None
    technical_accuracy_score: int | None
    evidence_consistency_score: int | None
    answer_depth_score: int | None
    expression_structure_score: int | None
    job_match_score: int | None
    total_score: int | None
    evaluation_summary: str | None
    problems: list[dict[str, Any] | str] | None
    optimized_answer: str | None
    modification_reason: str | None
    has_evidence_conflict: bool
    evidence_conflicts: list[dict[str, Any]] | None
    evidence_sources: list[dict[str, Any]] | None
    evaluation_source_ids: list[str] | None
    unsupported_claims: list[str] | None
    strengths: list[str] | None
    answered_at: str | None
    created_at: str
    updated_at: str


class ImprovementTaskSourceTurnSummary(BaseModel):
    id: int
    sequence_number: int
    main_question_number: int
    follow_up_number: int
    question: str


class ImprovementTaskResponse(BaseModel):
    id: int
    session_id: int
    turn_id: int | None
    title: str
    description: str
    completion_criteria: str
    category: ImprovementCategory
    priority: ImprovementPriority
    status: ImprovementStatus
    created_at: str
    completed_at: str | None
    updated_at: str
    source_turn: ImprovementTaskSourceTurnSummary | None


class InterviewSessionResponse(BaseModel):
    id: int
    title: str
    mode: InterviewMode
    status: InterviewStatus
    planned_main_questions: int
    current_main_question: int
    selected_project_file_ids: list[str]
    overall_score: float | None
    dimension_scores: dict[str, float] | None
    summary: str | None
    improvement_status: ImprovementGenerationStatus
    improvement_summary: str | None
    next_round_strategy: str | None
    improvement_generated_at: str | None
    started_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str
    target_job: TargetJobSummary | None
    project_files: list[ProjectFileSummary]
    previous_session: PreviousSessionSummary | None


class InterviewSessionDetail(InterviewSessionResponse):
    turns: list[InterviewTurnResponse]
    improvement_tasks: list[ImprovementTaskResponse]
    interview_plan: InterviewPlanOutput | None
    current_question: InterviewTurnResponse | None
    completed_main_questions: int
    current_follow_up_count: int
    is_completed: bool
    comparison_available: bool
    agent_execution_summary: dict[str, Any] | None


class InterviewStartResponse(InterviewSessionResponse):
    interview_plan: InterviewPlanOutput
    current_question: InterviewTurnResponse
    completed_main_questions: int
    current_follow_up_count: int
    is_completed: bool
    evidence_limited: bool
    agent_execution_summary: dict[str, Any]


class InterviewAnswerResponse(InterviewSessionResponse):
    decision: SupervisorDecisionOutput
    answered_turn: InterviewTurnResponse
    current_question: InterviewTurnResponse | None
    completed_main_questions: int
    current_follow_up_count: int
    is_completed: bool
    evidence_limited: bool
    agent_execution_summary: dict[str, Any]


class InterviewSessionListResponse(BaseModel):
    sessions: list[InterviewSessionResponse]


class ImprovementTaskListResponse(BaseModel):
    tasks: list[ImprovementTaskResponse]


class ImprovementGenerationResponse(BaseModel):
    session_id: int
    improvement_status: ImprovementGenerationStatus
    improvement_summary: str | None
    next_round_strategy: str | None
    improvement_generated_at: str | None
    generated: bool
    tasks: list[ImprovementTaskResponse]


class InterviewRetryResponse(InterviewSessionResponse):
    source_session_id: int
    previous_task_count: int
    completed_task_count: int
    pending_task_count: int
    task_completion_rate: float


class InterviewComparisonResponse(BaseModel):
    comparable: bool
    reason: str | None
    note: str
    previous_session_id: int | None
    current_session_id: int
    previous_overall_score: float | None
    current_overall_score: float | None
    overall_delta: float | None
    previous_dimension_scores: dict[str, float] | None
    current_dimension_scores: dict[str, float] | None
    dimension_deltas: dict[str, float] | None
    improved_dimensions: list[str]
    regressed_dimensions: list[str]
    unchanged_dimensions: list[str]
    previous_task_count: int
    completed_task_count: int
    task_completion_rate: float
