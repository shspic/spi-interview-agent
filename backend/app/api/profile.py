import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import User, UserProfile

router = APIRouter()


class UserProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(default="", max_length=100)
    target_direction: str = Field(default="", max_length=200)
    self_introduction: str = Field(default="", max_length=5000)
    technical_skills: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("technical_skills")
    @classmethod
    def normalize_technical_skills(cls, skills: list[str]) -> list[str]:
        normalized = []
        seen = set()

        for skill in skills:
            value = skill.strip()

            if not value:
                continue

            if len(value) > 50:
                raise ValueError("单个技术栈标签不能超过 50 个字符")

            key = value.lower()

            if key not in seen:
                normalized.append(value)
                seen.add(key)

        return normalized


class UserProfileResponse(BaseModel):
    user_id: int
    display_name: str
    target_direction: str
    self_introduction: str
    technical_skills: list[str]
    created_at: str
    updated_at: str


class UserProfileEnvelope(BaseModel):
    profile: UserProfileResponse | None


def profile_to_response(profile: UserProfile) -> UserProfileResponse:
    try:
        technical_skills = json.loads(profile.technical_skills or "[]")
    except json.JSONDecodeError:
        technical_skills = []

    if not isinstance(technical_skills, list):
        technical_skills = []

    return UserProfileResponse(
        user_id=profile.user_id,
        display_name=profile.display_name,
        target_direction=profile.target_direction,
        self_introduction=profile.self_introduction,
        technical_skills=[str(skill) for skill in technical_skills],
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.get("/profile", response_model=UserProfileEnvelope)
def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = (
        db.query(UserProfile)
        .filter(UserProfile.user_id == current_user.id)
        .first()
    )

    return {
        "profile": profile_to_response(profile) if profile is not None else None
    }


@router.put("/profile", response_model=UserProfileResponse)
def save_profile(
    request: UserProfileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = (
        db.query(UserProfile)
        .filter(UserProfile.user_id == current_user.id)
        .first()
    )
    now = datetime.now().isoformat(timespec="seconds")

    if profile is None:
        profile = UserProfile(
            user_id=current_user.id,
            created_at=now,
            updated_at=now,
        )
        db.add(profile)

    profile.display_name = request.display_name.strip()
    profile.target_direction = request.target_direction.strip()
    profile.self_introduction = request.self_introduction.strip()
    profile.technical_skills = json.dumps(
        request.technical_skills,
        ensure_ascii=False,
    )
    profile.updated_at = now

    db.commit()
    db.refresh(profile)

    return profile_to_response(profile)
