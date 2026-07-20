from pydantic import BaseModel, ConfigDict, Field


class DataCleanupPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(max_length=72)
    confirm: str = Field(max_length=64)


class AccountDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(max_length=72)
    confirm_username: str = Field(min_length=1, max_length=32)
    confirm: str = Field(max_length=64)
