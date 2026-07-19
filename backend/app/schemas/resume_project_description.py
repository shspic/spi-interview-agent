from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResumeProjectDescriptionGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: int = Field(gt=0)
    target_job_id: int | None = Field(default=None, gt=0)
    project_file_ids: list[str] | None = Field(default=None, max_length=20)

    @field_validator("project_file_ids")
    @classmethod
    def normalize_file_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
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


class ResumeProjectDescriptionResponse(BaseModel):
    id: int
    session_id: int | None
    target_job_id: int | None
    project_file_ids: list[str]
    project_name: str
    one_line_summary: str
    concise_bullets: list[str]
    detailed_description: str
    technical_stack: list[str]
    responsibilities: list[str]
    challenges: list[str]
    solutions: list[str]
    outcomes: list[str]
    interview_talking_points: list[str]
    warnings: list[str]
    evidence_source_ids: list[str]
    prompt_version: str
    created_at: str
    updated_at: str


class ResumeProjectDescriptionListResponse(BaseModel):
    descriptions: list[ResumeProjectDescriptionResponse]
