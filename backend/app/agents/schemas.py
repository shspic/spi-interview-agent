from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InterviewPlanInput(AgentSchema):
    title: str
    mode: Literal["quick", "standard", "deep_dive"]
    planned_main_questions: int = Field(gt=0, le=10)
    target_job_title: str | None = None


class InterviewPlanOutput(AgentSchema):
    planned_main_questions: int = Field(gt=0, le=10)
    focus_areas: list[str] = Field(min_length=1, max_length=8)
    strategy: str = Field(min_length=1, max_length=1000)
    opening_focus: str = Field(min_length=1, max_length=300)


class EvidenceQueryInput(AgentSchema):
    title: str
    mode: Literal["quick", "standard", "deep_dive"]
    plan: InterviewPlanOutput
    current_question: str | None = None
    latest_answer: str | None = None


class EvidenceQueryOutput(AgentSchema):
    query: str = Field(min_length=1, max_length=500)


class EvidenceItem(AgentSchema):
    evidence_type: Literal["profile", "project", "resume", "job_requirement"]
    source_id: str
    filename: str | None = None
    content: str
    distance: float | None = None


class EvidenceOutput(AgentSchema):
    is_sufficient: bool
    reason: str
    best_distance: float | None
    distance_metric: Literal["l2_squared"] = "l2_squared"
    sources: list[EvidenceItem]
    context: str
    profile_evidence: list[EvidenceItem]
    project_evidence: list[EvidenceItem]
    resume_evidence: list[EvidenceItem]
    job_requirements: list[EvidenceItem]


class SupervisorDecisionInput(AgentSchema):
    mode: Literal["quick", "standard", "deep_dive"]
    planned_main_questions: int
    current_main_question: int
    current_follow_up_count: int
    question: str
    answer: str
    evidence: EvidenceOutput


class SupervisorDecisionOutput(AgentSchema):
    action: Literal["follow_up", "next_main_question", "complete"]
    reason: str = Field(min_length=1, max_length=500)


class InterviewerInput(AgentSchema):
    action: Literal["main_question", "follow_up"]
    mode: Literal["quick", "standard", "deep_dive"]
    main_question_number: int = Field(gt=0)
    plan: InterviewPlanOutput
    evidence: EvidenceOutput
    previous_question: str | None = None
    previous_answer: str | None = None
    follow_up_reason: str | None = None


class InterviewerOutput(AgentSchema):
    question: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=500)
    evidence_limited: bool
