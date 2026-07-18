from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.schemas import InterviewPlanOutput, SupervisorDecisionOutput

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
        normalized = value.strip()
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
        normalized = value.strip()
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
    answer: str = Field(min_length=1, max_length=20000)

    @field_validator("answer")
    @classmethod
    def normalize_answer(cls, value: str) -> str:
        normalized = value.strip()
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
    overall_score: int | None
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
    problems: list[str] | None
    optimized_answer: str | None
    modification_reason: str | None
    has_evidence_conflict: bool
    evidence_conflicts: list[dict[str, Any]] | None
    evidence_sources: list[dict[str, Any]] | None
    answered_at: str | None
    created_at: str
    updated_at: str


class ImprovementTaskResponse(BaseModel):
    id: int
    session_id: int
    turn_id: int | None
    title: str
    description: str
    category: ImprovementCategory
    priority: ImprovementPriority
    status: ImprovementStatus
    created_at: str
    completed_at: str | None
    updated_at: str


class InterviewSessionResponse(BaseModel):
    id: int
    title: str
    mode: InterviewMode
    status: InterviewStatus
    planned_main_questions: int
    current_main_question: int
    selected_project_file_ids: list[str]
    overall_score: int | None
    dimension_scores: dict[str, float] | None
    summary: str | None
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
