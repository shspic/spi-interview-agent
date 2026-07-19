from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrainingGuidanceTask(AgentSchema):
    title: str
    category: Literal[
        "technical",
        "project_evidence",
        "answer_depth",
        "expression",
        "job_match",
        "resume",
    ]
    completion_criteria: str


class TrainingGuidance(AgentSchema):
    next_round_strategy: str | None = None
    pending_tasks: list[TrainingGuidanceTask] = Field(
        default_factory=list,
        max_length=20,
    )


class InterviewPlanInput(AgentSchema):
    title: str
    mode: Literal["quick", "standard", "deep_dive"]
    planned_main_questions: int = Field(gt=0, le=10)
    target_job_title: str | None = None
    training_guidance: TrainingGuidance | None = None


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
    chunk_index: int | None = None
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
    evaluation: "SupervisorEvaluationSummary"


class SupervisorEvaluationSummary(AgentSchema):
    technical_accuracy_score: int = Field(ge=0, le=100)
    evidence_consistency_score: int = Field(ge=0, le=100)
    answer_depth_score: int = Field(ge=0, le=100)
    has_evidence_conflict: bool
    evaluation_summary: str


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


class EvaluationProblem(AgentSchema):
    category: Literal[
        "technical",
        "evidence",
        "depth",
        "expression",
        "job_match",
    ]
    description: str = Field(min_length=1, max_length=1000)
    suggestion: str = Field(min_length=1, max_length=1000)


class EvaluationConflict(AgentSchema):
    claim: str = Field(min_length=1, max_length=1000)
    conflict_type: Literal["unsupported", "contradiction", "exaggeration"]
    explanation: str = Field(min_length=1, max_length=1000)
    evidence_source_ids: list[str] = Field(default_factory=list, max_length=20)


class EvaluationInput(AgentSchema):
    question: str
    answer: str
    evidence: EvidenceOutput


class EvaluationOutput(AgentSchema):
    technical_accuracy_score: int = Field(ge=0, le=100)
    evidence_consistency_score: int = Field(ge=0, le=100)
    answer_depth_score: int = Field(ge=0, le=100)
    expression_structure_score: int = Field(ge=0, le=100)
    job_match_score: int = Field(ge=0, le=100)
    evaluation_summary: str = Field(min_length=1, max_length=2000)
    problems: list[EvaluationProblem] = Field(default_factory=list, max_length=20)
    optimized_answer: str = Field(min_length=1, max_length=20000)
    modification_reason: str = Field(min_length=1, max_length=5000)
    has_evidence_conflict: bool
    evidence_conflicts: list[EvaluationConflict] = Field(
        default_factory=list,
        max_length=20,
    )
    evidence_source_ids: list[str] = Field(default_factory=list, max_length=50)
    unsupported_claims: list[str] = Field(default_factory=list, max_length=20)
    strengths: list[str] = Field(default_factory=list, max_length=20)


ImprovementCategory = Literal[
    "technical",
    "project_evidence",
    "answer_depth",
    "expression",
    "job_match",
    "resume",
]
ImprovementPriority = Literal["low", "medium", "high"]


class ImprovementTurnInput(AgentSchema):
    turn_id: int = Field(gt=0)
    question: str
    technical_accuracy_score: int = Field(ge=0, le=100)
    evidence_consistency_score: int = Field(ge=0, le=100)
    answer_depth_score: int = Field(ge=0, le=100)
    expression_structure_score: int = Field(ge=0, le=100)
    job_match_score: int = Field(ge=0, le=100)
    total_score: int = Field(ge=0, le=100)
    problems: list[EvaluationProblem] = Field(default_factory=list, max_length=20)
    strengths: list[str] = Field(default_factory=list, max_length=20)
    unsupported_claims: list[str] = Field(default_factory=list, max_length=20)
    evidence_conflicts: list[EvaluationConflict] = Field(
        default_factory=list,
        max_length=20,
    )
    evaluation_summary: str


class ExistingImprovementTaskInput(AgentSchema):
    title: str
    category: ImprovementCategory
    source_turn_id: int | None = None
    status: Literal["pending", "completed"]


class ImprovementInput(AgentSchema):
    mode: Literal["quick", "standard", "deep_dive"]
    target_job_title: str | None = None
    target_company_name: str | None = None
    overall_score: float | None = Field(default=None, ge=0, le=100)
    dimension_scores: dict[str, float] | None = None
    turns: list[ImprovementTurnInput] = Field(min_length=1, max_length=50)
    existing_tasks: list[ExistingImprovementTaskInput] = Field(
        default_factory=list,
        max_length=50,
    )


class ImprovementTaskProposal(AgentSchema):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=3000)
    category: ImprovementCategory
    priority: ImprovementPriority
    source_turn_id: int | None = Field(default=None, gt=0)
    completion_criteria: str = Field(min_length=1, max_length=2000)


class ImprovementOutput(AgentSchema):
    overall_diagnosis: str = Field(min_length=1, max_length=5000)
    strongest_dimensions: list[str] = Field(default_factory=list, max_length=5)
    weakest_dimensions: list[str] = Field(default_factory=list, max_length=5)
    next_round_strategy: str = Field(min_length=1, max_length=5000)
    tasks: list[ImprovementTaskProposal] = Field(min_length=3, max_length=8)
