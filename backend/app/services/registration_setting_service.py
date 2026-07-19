import re
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.models import RegistrationSetting

INVITE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
MIN_INVITE_CODE_LENGTH = 6
MAX_INVITE_CODE_LENGTH = 64


class RegistrationSettingError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def validate_invite_code(invite_code: str) -> str:
    normalized = invite_code.strip()
    if not MIN_INVITE_CODE_LENGTH <= len(normalized) <= MAX_INVITE_CODE_LENGTH:
        raise RegistrationSettingError(400, "邀请码长度必须在 6 到 64 个字符之间")
    if not INVITE_CODE_PATTERN.fullmatch(normalized):
        raise RegistrationSettingError(400, "邀请码只能包含字母、数字、下划线和连字符")
    return normalized


def ensure_registration_setting(db: Session) -> RegistrationSetting:
    registration_setting = db.get(RegistrationSetting, 1)
    if registration_setting is not None:
        return registration_setting

    configured_code = settings.registration_invite_code.strip()
    if not configured_code or configured_code == "change-me":
        raise RegistrationSettingError(503, "注册邀请码尚未配置")

    try:
        normalized_code = validate_invite_code(configured_code)
    except RegistrationSettingError as exc:
        raise RegistrationSettingError(503, "注册邀请码配置无效") from exc

    now = datetime.now().isoformat(timespec="seconds")
    registration_setting = RegistrationSetting(
        id=1,
        invite_code_hash=hash_password(normalized_code),
        updated_at=now,
        updated_by=None,
    )
    try:
        db.add(registration_setting)
        db.commit()
        db.refresh(registration_setting)
        return registration_setting
    except IntegrityError:
        db.rollback()
        existing = db.get(RegistrationSetting, 1)
        if existing is None:
            raise RegistrationSettingError(503, "注册邀请码初始化失败")
        return existing


def verify_registration_invite(db: Session, invite_code: str) -> bool:
    registration_setting = ensure_registration_setting(db)
    return verify_password(invite_code, registration_setting.invite_code_hash)


def update_registration_invite_code(
    db: Session,
    invite_code: str,
    admin_user_id: int,
) -> RegistrationSetting:
    normalized_code = validate_invite_code(invite_code)
    registration_setting = db.get(RegistrationSetting, 1)
    now = datetime.now().isoformat(timespec="seconds")
    if registration_setting is None:
        registration_setting = RegistrationSetting(id=1)
        db.add(registration_setting)
    registration_setting.invite_code_hash = hash_password(normalized_code)
    registration_setting.updated_at = now
    registration_setting.updated_by = admin_user_id
    db.commit()
    db.refresh(registration_setting)
    return registration_setting
