from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DailyUsageCounter, UsageEvent

LIMITED_USAGE_TYPES = (
    "chat",
    "job_analysis",
    "interview_evaluation",
    "multi_agent_task",
)
USAGE_DISPLAY_NAMES = {
    "chat": "普通问答",
    "job_analysis": "岗位分析",
    "interview_evaluation": "面试评价",
    "multi_agent_task": "完整多 Agent 面试任务",
    "resume_generation": "简历项目描述生成",
}
RESERVATION_TIMEOUT_MINUTES = 30


class UsageServiceError(Exception):
    def __init__(self, status_code: int, detail):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class UsageLimitExceeded(UsageServiceError):
    pass


class UsageReservationConflict(UsageServiceError):
    pass


@dataclass
class UsageReservation:
    event_id: int
    usage_type: str
    already_succeeded: bool = False


def get_app_timezone() -> tzinfo:
    try:
        return ZoneInfo(settings.app_timezone)
    except ZoneInfoNotFoundError as exc:
        if settings.app_timezone == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        raise RuntimeError("APP_TIMEZONE 配置无效") from exc


def get_local_now(now: datetime | None = None) -> datetime:
    timezone = get_app_timezone()
    if now is None:
        return datetime.now(timezone)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone)
    return now.astimezone(timezone)


def get_usage_limit(usage_type: str) -> int | None:
    limits = {
        "chat": settings.daily_chat_limit,
        "job_analysis": settings.daily_job_analysis_limit,
        "interview_evaluation": settings.daily_interview_evaluation_limit,
        "multi_agent_task": settings.daily_multi_agent_task_limit,
    }
    return limits.get(usage_type)


def get_reset_at(local_now: datetime) -> str:
    next_day = (local_now + timedelta(days=1)).date()
    return datetime.combine(
        next_day,
        datetime.min.time(),
        tzinfo=get_app_timezone(),
    ).isoformat(timespec="seconds")


def _ensure_counter(
    db: Session,
    user_id: int,
    usage_type: str,
    usage_date: str,
    now_text: str,
) -> None:
    statement = (
        sqlite_insert(DailyUsageCounter)
        .values(
            user_id=user_id,
            usage_type=usage_type,
            usage_date=usage_date,
            used=0,
            reserved=0,
            updated_at=now_text,
        )
        .on_conflict_do_nothing(
            index_elements=["user_id", "usage_type", "usage_date"]
        )
    )
    db.execute(statement)


def _release_stale_reservations(
    db: Session,
    user_id: int,
    usage_type: str,
    usage_date: str,
    local_now: datetime,
) -> bool:
    stale_before = (
        local_now - timedelta(minutes=RESERVATION_TIMEOUT_MINUTES)
    ).isoformat(timespec="seconds")
    stale_events = (
        db.query(UsageEvent)
        .filter(
            UsageEvent.user_id == user_id,
            UsageEvent.usage_type == usage_type,
            UsageEvent.usage_date == usage_date,
            UsageEvent.status == "reserved",
            UsageEvent.reserved_at < stale_before,
        )
        .all()
    )
    if not stale_events:
        return False

    released_amount = sum(event.amount for event in stale_events)
    now_text = local_now.isoformat(timespec="seconds")
    counter = (
        db.query(DailyUsageCounter)
        .filter(
            DailyUsageCounter.user_id == user_id,
            DailyUsageCounter.usage_type == usage_type,
            DailyUsageCounter.usage_date == usage_date,
        )
        .first()
    )
    if counter is not None:
        counter.reserved = max(0, counter.reserved - released_amount)
        counter.updated_at = now_text
    for event in stale_events:
        event.status = "released"
        event.error_type = "reservation_timeout"
        event.completed_at = now_text
        event.updated_at = now_text
    db.flush()
    return True


def _counter_values(
    db: Session,
    user_id: int,
    usage_type: str,
    usage_date: str,
) -> tuple[int, int]:
    counter = (
        db.query(DailyUsageCounter)
        .filter(
            DailyUsageCounter.user_id == user_id,
            DailyUsageCounter.usage_type == usage_type,
            DailyUsageCounter.usage_date == usage_date,
        )
        .first()
    )
    if counter is None:
        return 0, 0
    return counter.used, counter.reserved


def _limit_detail(
    db: Session,
    user_id: int,
    usage_type: str,
    usage_date: str,
    local_now: datetime,
    limit: int,
) -> dict:
    used, reserved = _counter_values(db, user_id, usage_type, usage_date)
    return {
        "code": "usage_limit_exceeded",
        "message": f"今日{USAGE_DISPLAY_NAMES[usage_type]}额度已用尽",
        "usage_type": usage_type,
        "limit": limit,
        "used": used,
        "reserved": reserved,
        "remaining": max(0, limit - used - reserved),
        "reset_at": get_reset_at(local_now),
    }


def reserve_usage(
    db: Session,
    user_id: int,
    usage_type: str,
    idempotency_key: str,
    *,
    related_resource_type: str | None = None,
    related_resource_id: str | int | None = None,
    amount: int = 1,
    now: datetime | None = None,
) -> UsageReservation:
    if amount <= 0:
        raise ValueError("用量数量必须大于 0")
    local_now = get_local_now(now)
    usage_date = local_now.date().isoformat()
    now_text = local_now.isoformat(timespec="seconds")
    released_stale = _release_stale_reservations(
        db,
        user_id,
        usage_type,
        usage_date,
        local_now,
    )
    if released_stale:
        db.commit()

    existing = (
        db.query(UsageEvent)
        .filter(
            UsageEvent.user_id == user_id,
            UsageEvent.usage_type == usage_type,
            UsageEvent.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing is not None and existing.status == "succeeded":
        db.commit()
        return UsageReservation(existing.id, usage_type, already_succeeded=True)
    if existing is not None and existing.status == "reserved":
        db.commit()
        raise UsageReservationConflict(409, "相同业务请求正在处理中")

    _ensure_counter(db, user_id, usage_type, usage_date, now_text)
    limit = get_usage_limit(usage_type)
    conditions = [
        DailyUsageCounter.user_id == user_id,
        DailyUsageCounter.usage_type == usage_type,
        DailyUsageCounter.usage_date == usage_date,
    ]
    if limit is not None:
        conditions.append(
            DailyUsageCounter.used
            + DailyUsageCounter.reserved
            + amount
            <= limit
        )
    result = db.execute(
        update(DailyUsageCounter)
        .where(*conditions)
        .values(
            reserved=DailyUsageCounter.reserved + amount,
            updated_at=now_text,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        duplicate = (
            db.query(UsageEvent)
            .filter(
                UsageEvent.user_id == user_id,
                UsageEvent.usage_type == usage_type,
                UsageEvent.idempotency_key == idempotency_key,
            )
            .first()
        )
        if duplicate is not None and duplicate.status == "succeeded":
            return UsageReservation(
                duplicate.id,
                usage_type,
                already_succeeded=True,
            )
        if duplicate is not None and duplicate.status == "reserved":
            raise UsageReservationConflict(409, "相同业务请求正在处理中")
        if limit is None:
            raise UsageServiceError(500, "用量预留失败")
        raise UsageLimitExceeded(
            429,
            _limit_detail(
                db,
                user_id,
                usage_type,
                usage_date,
                local_now,
                limit,
            ),
        )

    if existing is None:
        event = UsageEvent(
            user_id=user_id,
            usage_type=usage_type,
            usage_date=usage_date,
            idempotency_key=idempotency_key,
            status="reserved",
            amount=amount,
            related_resource_type=related_resource_type,
            related_resource_id=(
                str(related_resource_id) if related_resource_id is not None else None
            ),
            error_type=None,
            reserved_at=now_text,
            completed_at=None,
            created_at=now_text,
            updated_at=now_text,
        )
        db.add(event)
    else:
        event = existing
        event.usage_date = usage_date
        event.status = "reserved"
        event.amount = amount
        event.error_type = None
        event.reserved_at = now_text
        event.completed_at = None
        event.updated_at = now_text
    try:
        db.commit()
        db.refresh(event)
    except IntegrityError:
        db.rollback()
        duplicate = (
            db.query(UsageEvent)
            .filter(
                UsageEvent.user_id == user_id,
                UsageEvent.usage_type == usage_type,
                UsageEvent.idempotency_key == idempotency_key,
            )
            .first()
        )
        if duplicate is not None and duplicate.status == "succeeded":
            return UsageReservation(duplicate.id, usage_type, already_succeeded=True)
        raise UsageReservationConflict(409, "相同业务请求正在处理中")
    return UsageReservation(event.id, usage_type)


def commit_usage(db: Session, reservation: UsageReservation) -> UsageEvent:
    event = db.get(UsageEvent, reservation.event_id)
    if event is None:
        raise UsageServiceError(500, "用量记录不存在")
    if event.status == "succeeded":
        return event
    if event.status != "reserved":
        raise UsageServiceError(409, "用量记录当前不可提交")

    now_text = get_local_now().isoformat(timespec="seconds")
    counter = (
        db.query(DailyUsageCounter)
        .filter(
            DailyUsageCounter.user_id == event.user_id,
            DailyUsageCounter.usage_type == event.usage_type,
            DailyUsageCounter.usage_date == event.usage_date,
        )
        .first()
    )
    if counter is None or counter.reserved < event.amount:
        raise UsageServiceError(500, "用量计数状态不一致")
    counter.reserved -= event.amount
    counter.used += event.amount
    counter.updated_at = now_text
    event.status = "succeeded"
    event.completed_at = now_text
    event.updated_at = now_text
    db.commit()
    db.refresh(event)
    return event


def release_usage(
    db: Session,
    reservation: UsageReservation,
    error_type: str | None = None,
) -> UsageEvent:
    event = db.get(UsageEvent, reservation.event_id)
    if event is None:
        raise UsageServiceError(500, "用量记录不存在")
    if event.status != "reserved":
        return event

    now_text = get_local_now().isoformat(timespec="seconds")
    counter = (
        db.query(DailyUsageCounter)
        .filter(
            DailyUsageCounter.user_id == event.user_id,
            DailyUsageCounter.usage_type == event.usage_type,
            DailyUsageCounter.usage_date == event.usage_date,
        )
        .first()
    )
    if counter is not None:
        counter.reserved = max(0, counter.reserved - event.amount)
        counter.updated_at = now_text
    event.status = "failed" if error_type else "released"
    event.error_type = error_type[:100] if error_type else None
    event.completed_at = now_text
    event.updated_at = now_text
    db.commit()
    db.refresh(event)
    return event


def get_user_usage(
    db: Session,
    user_id: int,
    now: datetime | None = None,
) -> dict:
    local_now = get_local_now(now)
    usage_date = local_now.date().isoformat()
    items = []
    for usage_type in LIMITED_USAGE_TYPES:
        used, reserved = _counter_values(db, user_id, usage_type, usage_date)
        limit = get_usage_limit(usage_type)
        items.append(
            {
                "usage_type": usage_type,
                "display_name": USAGE_DISPLAY_NAMES[usage_type],
                "limit": limit,
                "used": used,
                "reserved": reserved,
                "remaining": max(0, limit - used - reserved),
                "reset_at": get_reset_at(local_now),
            }
        )
    return {
        "current_date": usage_date,
        "timezone": settings.app_timezone,
        "items": items,
    }
