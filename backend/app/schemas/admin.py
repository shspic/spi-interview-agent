from pydantic import BaseModel, ConfigDict, Field


class UserStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool


class AdminPasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str


class UserDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_username: str


class InviteCodeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invite_code: str


class CleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str = Field(min_length=1, max_length=64)
