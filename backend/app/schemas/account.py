from pydantic import BaseModel, ConfigDict, Field


class DataCleanupPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(max_length=72)
    confirm: str = Field(max_length=64)
