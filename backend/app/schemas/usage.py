from pydantic import BaseModel, ConfigDict


class UsageItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usage_type: str
    display_name: str
    unlimited: bool
    limit: int | None
    used: int
    reserved: int
    remaining: int | None
    reset_at: str


class CurrentUserUsageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_date: str
    timezone: str
    items: list[UsageItemResponse]
