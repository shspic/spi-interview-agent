from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import AdminAuditLog, AgentRun, UsageEvent, User
from app.services.admin_service import AdminServiceError, get_admin_user
from app.services.usage_service import LIMITED_USAGE_TYPES, get_user_usage


def _date_bounds(date_from: date, date_to: date) -> tuple[str, str]:
    return date_from.isoformat(), (date_to + timedelta(days=1)).isoformat()


def get_usage_summary(db: Session, date_from: date, date_to: date) -> dict:
    start, end = _date_bounds(date_from, date_to)
    usage_rows = (
        db.query(
            UsageEvent.usage_date,
            UsageEvent.usage_type,
            UsageEvent.status,
            func.sum(UsageEvent.amount),
        )
        .filter(UsageEvent.usage_date >= start, UsageEvent.usage_date < end)
        .group_by(UsageEvent.usage_date, UsageEvent.usage_type, UsageEvent.status)
        .all()
    )
    usage_totals = {usage_type: 0 for usage_type in LIMITED_USAGE_TYPES}
    status_totals = {
        "reserved": 0,
        "succeeded": 0,
        "released": 0,
        "failed": 0,
    }
    trend_map = defaultdict(lambda: {item: 0 for item in LIMITED_USAGE_TYPES})
    for usage_date, usage_type, event_status, amount in usage_rows:
        amount = int(amount or 0)
        status_totals[event_status] = status_totals.get(event_status, 0) + amount
        if event_status == "succeeded" and usage_type in usage_totals:
            usage_totals[usage_type] += amount
            trend_map[usage_date][usage_type] += amount

    run_rows = (
        db.query(
            AgentRun.agent_name,
            AgentRun.status,
            func.count(AgentRun.id),
            func.avg(AgentRun.latency_ms),
        )
        .filter(AgentRun.created_at >= start, AgentRun.created_at < end)
        .group_by(AgentRun.agent_name, AgentRun.status)
        .all()
    )
    agent_totals = defaultdict(lambda: {"success": 0, "error": 0})
    latency_weighted_sum = 0.0
    run_count = 0
    for agent_name, run_status, count, average_latency in run_rows:
        count = int(count or 0)
        agent_totals[agent_name][run_status] = count
        run_count += count
        latency_weighted_sum += float(average_latency or 0) * count

    recent_failures = (
        db.query(AgentRun.agent_name, AgentRun.error, AgentRun.created_at)
        .filter(
            AgentRun.status == "error",
            AgentRun.created_at >= start,
            AgentRun.created_at < end,
        )
        .order_by(AgentRun.created_at.desc())
        .limit(20)
        .all()
    )
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "registered_user_count": db.query(func.count(User.id)).scalar() or 0,
        "active_user_count": (
            db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar()
            or 0
        ),
        "business_usage": usage_totals,
        "daily_trend": [
            {"date": trend_date, **trend_map[trend_date]}
            for trend_date in sorted(trend_map)
        ],
        "event_status_counts": status_totals,
        "agent_run_count": run_count,
        "agent_runs_by_name": dict(agent_totals),
        "average_latency_ms": (
            round(latency_weighted_sum / run_count, 2) if run_count else None
        ),
        "recent_failure_types": [
            {
                "agent_name": agent_name,
                "error_type": (error or "unknown")[:100],
                "created_at": created_at,
            }
            for agent_name, error, created_at in recent_failures
        ],
    }


def get_user_usage_report(
    db: Session,
    user_id: int,
    date_from: date,
    date_to: date,
) -> dict:
    user = get_admin_user(db, user_id)
    start, end = _date_bounds(date_from, date_to)
    rows = (
        db.query(
            UsageEvent.usage_date,
            UsageEvent.usage_type,
            UsageEvent.status,
            func.sum(UsageEvent.amount),
        )
        .filter(
            UsageEvent.user_id == user_id,
            UsageEvent.usage_date >= start,
            UsageEvent.usage_date < end,
        )
        .group_by(UsageEvent.usage_date, UsageEvent.usage_type, UsageEvent.status)
        .all()
    )
    return {
        "user": {"id": user.id, "username": user.username},
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "today": get_user_usage(db, user_id),
        "events": [
            {
                "date": usage_date,
                "usage_type": usage_type,
                "status": status,
                "amount": int(amount or 0),
            }
            for usage_date, usage_type, status, amount in rows
        ],
    }


def list_agent_runs(
    db: Session,
    *,
    user_id: int | None,
    session_id: int | None,
    agent_name: str | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    page_size: int,
) -> dict:
    query = db.query(AgentRun)
    if user_id is not None:
        query = query.filter(AgentRun.user_id == user_id)
    if session_id is not None:
        query = query.filter(AgentRun.session_id == session_id)
    if agent_name:
        query = query.filter(AgentRun.agent_name == agent_name)
    if status:
        query = query.filter(AgentRun.status == status)
    if date_from:
        query = query.filter(AgentRun.created_at >= date_from.isoformat())
    if date_to:
        query = query.filter(
            AgentRun.created_at < (date_to + timedelta(days=1)).isoformat()
        )
    total = query.count()
    runs = (
        query.order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [
            {
                "id": run.id,
                "run_id": run.run_id,
                "session_id": run.session_id,
                "user_id": run.user_id,
                "agent_name": run.agent_name,
                "prompt_version": run.prompt_version,
                "status": run.status,
                "latency_ms": run.latency_ms,
                "error_type": (run.error or "")[:100] or None,
                "created_at": run.created_at,
            }
            for run in runs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_audit_logs(
    db: Session,
    *,
    action: str | None,
    admin_user_id: int | None,
    target_user_id: int | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    page_size: int,
) -> dict:
    query = db.query(AdminAuditLog)
    if action:
        query = query.filter(AdminAuditLog.action == action)
    if admin_user_id is not None:
        query = query.filter(AdminAuditLog.admin_user_id == admin_user_id)
    if target_user_id is not None:
        query = query.filter(AdminAuditLog.target_user_id == target_user_id)
    if status:
        query = query.filter(AdminAuditLog.status == status)
    if date_from:
        query = query.filter(AdminAuditLog.created_at >= date_from.isoformat())
    if date_to:
        query = query.filter(
            AdminAuditLog.created_at < (date_to + timedelta(days=1)).isoformat()
        )
    total = query.count()
    logs = (
        query.order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [
            {
                "id": log.id,
                "admin_user_id": log.admin_user_id,
                "action": log.action,
                "target_user_id": log.target_user_id,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "status": log.status,
                "detail_summary": log.detail_summary,
                "created_at": log.created_at,
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
