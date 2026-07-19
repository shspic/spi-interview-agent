from pydantic import BaseModel, ConfigDict


class DataCleanupPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    confirm: str
