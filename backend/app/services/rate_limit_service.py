import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from time import time

from fastapi import HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import RateLimitBucket


@dataclass(frozen=True)
class RateLimitRule:
    attempts: int
    window_seconds: int


def get_rate_limit_rule(scope: str) -> RateLimitRule:
    rules = {
        "login": RateLimitRule(
            settings.login_rate_limit_attempts,
            settings.login_rate_limit_window_seconds,
        ),
        "register": RateLimitRule(
            settings.register_rate_limit_attempts,
            settings.register_rate_limit_window_seconds,
        ),
        "upload": RateLimitRule(
            settings.upload_rate_limit_attempts,
            settings.upload_rate_limit_window_seconds,
        ),
        "password_change": RateLimitRule(
            settings.password_change_rate_limit_attempts,
            settings.password_change_rate_limit_window_seconds,
        ),
        "chat_burst": RateLimitRule(
            settings.chat_burst_rate_limit_attempts,
            settings.chat_burst_rate_limit_window_seconds,
        ),
        "admin_write": RateLimitRule(
            settings.admin_write_rate_limit_attempts,
            settings.admin_write_rate_limit_window_seconds,
        ),
    }
    try:
        return rules[scope]
    except KeyError as exc:
        raise ValueError("未知的限流范围") from exc


def _identifier_secret() -> bytes:
    configured_salt = settings.rate_limit_hash_salt.strip()
    secret = (
        configured_salt
        if configured_salt and configured_salt != "change-me"
        else settings.jwt_secret_key.strip()
    )
    if len(secret) < 16 or secret == "change-me":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="安全限流服务尚未配置",
        )
    return secret.encode("utf-8")


def hash_identifier(subject_type: str, identifier: str) -> str:
    payload = f"{subject_type}:{identifier}".encode("utf-8")
    return hmac.new(_identifier_secret(), payload, hashlib.sha256).hexdigest()


def resolve_client_ip(request: Request) -> str:
    peer = request.client.host if request.client is not None else ""
    try:
        peer_ip = ip_address(peer)
    except ValueError:
        return "unknown"

    trusted_networks = [
        ip_network(value, strict=False) for value in settings.trusted_proxy_cidrs
    ]
    if not trusted_networks or not any(peer_ip in item for item in trusted_networks):
        return peer_ip.compressed

    forwarded_chain = request.headers.get("x-forwarded-for", "")
    if forwarded_chain:
        parsed_chain = []
        for value in forwarded_chain.split(","):
            try:
                parsed_chain.append(ip_address(value.strip()))
            except ValueError:
                return peer_ip.compressed

        for candidate in reversed([*parsed_chain, peer_ip]):
            if any(candidate in item for item in trusted_networks):
                continue
            return candidate.compressed

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        try:
            return ip_address(real_ip).compressed
        except ValueError:
            return peer_ip.compressed

    return peer_ip.compressed


def enforce_rate_limit(
    db: Session,
    *,
    scope: str,
    subject_type: str,
    identifier: str,
    now_timestamp: int | None = None,
) -> None:
    rule = get_rate_limit_rule(scope)
    now_value = int(time()) if now_timestamp is None else int(now_timestamp)
    window_started_at = now_value - (now_value % rule.window_seconds)
    expires_at = window_started_at + rule.window_seconds
    subject_hash = hash_identifier(subject_type, identifier)
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    db.execute(
        delete(RateLimitBucket).where(RateLimitBucket.expires_at <= now_value)
    )
    dialect_name = db.get_bind().dialect.name
    insert_factory = (
        postgresql_insert if dialect_name == "postgresql" else sqlite_insert
    )
    statement = insert_factory(RateLimitBucket).values(
        scope=scope,
        subject_type=subject_type,
        subject_hash=subject_hash,
        window_started_at=window_started_at,
        expires_at=expires_at,
        attempts=1,
        updated_at=updated_at,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[
            RateLimitBucket.scope,
            RateLimitBucket.subject_type,
            RateLimitBucket.subject_hash,
            RateLimitBucket.window_started_at,
        ],
        set_={
            "attempts": RateLimitBucket.attempts + 1,
            "updated_at": updated_at,
        },
        where=RateLimitBucket.attempts < rule.attempts,
    )
    result = db.execute(statement)
    db.commit()

    if result.rowcount != 0:
        return

    retry_after = max(1, expires_at - now_value)
    reset_at = datetime.fromtimestamp(expires_at, timezone.utc).isoformat(
        timespec="seconds"
    )
    detail = {
        "error_code": "rate_limit_exceeded",
        "scope": scope,
        "message": "请求过于频繁，请稍后再试",
        "retry_after_seconds": retry_after,
        "reset_at": reset_at,
    }
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )


def enforce_ip_rate_limit(db: Session, request: Request, scope: str) -> None:
    enforce_rate_limit(
        db,
        scope=scope,
        subject_type="anonymous_ip",
        identifier=resolve_client_ip(request),
    )


def enforce_user_rate_limit(db: Session, user_id: int, scope: str) -> None:
    enforce_rate_limit(
        db,
        scope=scope,
        subject_type="user",
        identifier=str(user_id),
    )
