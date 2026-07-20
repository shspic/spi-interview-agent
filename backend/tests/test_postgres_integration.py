from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import AuthSession, BackgroundJob, User
from app.db.schema_version import alembic_config, get_schema_status
from app.services.auth_session_service import create_session, rotate_refresh_token
from app.services.background_job_service import claim_next_job, create_background_job, utc_text
from app.services.rate_limit_service import enforce_rate_limit
from app.services.upload_security import UploadSecurityError, reserve_user_storage
from app.services.usage_service import UsageServiceError, reserve_usage

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def postgres_factory():
    configured = os.getenv("TEST_POSTGRES_DATABASE_URL", "").strip()
    if not configured:
        pytest.skip("未配置 TEST_POSTGRES_DATABASE_URL")
    url = make_url(configured)
    if url.get_backend_name() != "postgresql" or "test" not in (url.database or "").lower():
        pytest.fail("TEST_POSTGRES_DATABASE_URL 必须指向名称包含 test 的 PostgreSQL 数据库")
    schema = f"spi_test_{uuid4().hex}"
    admin_engine = create_engine(url, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(test_url, pool_pre_ping=True)
    try:
        command.upgrade(alembic_config(test_url.render_as_string(hide_password=False)), "head")
        assert get_schema_status(engine).ready is True
        yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def _user(factory, username: str) -> User:
    db = factory()
    try:
        user = User(
            username=username,
            password_hash=hash_password("StrongPass123"),
            is_active=True,
            is_admin=False,
            created_at=utc_text(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user
    finally:
        db.close()


def test_postgres_alembic_schema_and_partial_active_index(postgres_factory):
    db = postgres_factory()
    try:
        tables = set(inspect(db.get_bind()).get_table_names())
        assert {"auth_sessions", "background_jobs", "worker_heartbeats"} <= tables
        indexes = inspect(db.get_bind()).get_indexes("target_jobs")
        active = next(item for item in indexes if item["name"] == "ux_target_jobs_active_user")
        assert active["unique"] is True
        assert active.get("dialect_options", {}).get("postgresql_where") is not None
    finally:
        db.close()


def test_postgres_refresh_rotation_allows_only_one_winner(postgres_factory):
    user = _user(postgres_factory, f"refresh_{uuid4().hex[:8]}")
    db = postgres_factory()
    try:
        session, token, _ = create_session(db, user)
        session_id = session.id
        db.commit()
    finally:
        db.close()
    barrier = Barrier(2)

    def rotate() -> bool:
        local = postgres_factory()
        try:
            auth_session = local.get(AuthSession, session_id)
            barrier.wait()
            result = rotate_refresh_token(local, auth_session, token)
            if result is not None:
                local.commit()
            return result is not None
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: rotate(), range(2)))
    assert results.count(True) == 1
    assert results.count(False) == 1


def test_postgres_usage_rate_upload_and_job_claiming_are_atomic(
    postgres_factory,
    monkeypatch,
):
    user = _user(postgres_factory, f"atomic_{uuid4().hex[:8]}")
    monkeypatch.setattr(settings, "daily_job_analysis_limit", 1)
    monkeypatch.setattr(settings, "login_rate_limit_attempts", 1)
    monkeypatch.setattr(settings, "max_user_storage_mb", 1)

    def reserve_usage_once(index: int) -> str:
        db = postgres_factory()
        try:
            reserve_usage(db, user.id, "job_analysis", f"pg-usage-{index}")
            return "ok"
        except UsageServiceError:
            return "rejected"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        usage_results = list(executor.map(reserve_usage_once, range(2)))
    assert usage_results.count("ok") == 1
    assert usage_results.count("rejected") == 1

    def rate_once(_: int) -> str:
        db = postgres_factory()
        try:
            enforce_rate_limit(
                db,
                scope="login",
                subject_type="anonymous_ip",
                identifier="192.0.2.10",
                now_timestamp=1000,
            )
            return "ok"
        except HTTPException:
            return "rejected"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        rate_results = list(executor.map(rate_once, range(2)))
    assert rate_results.count("ok") == 1
    assert rate_results.count("rejected") == 1

    def upload_once(_: int) -> str:
        db = postgres_factory()
        try:
            reserve_user_storage(db, user.id, 700_000)
            return "ok"
        except UploadSecurityError:
            return "rejected"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        upload_results = list(executor.map(upload_once, range(2)))
    assert upload_results.count("ok") == 1
    assert upload_results.count("rejected") == 1

    db = postgres_factory()
    try:
        for index in range(2):
            create_background_job(
                db,
                user_id=user.id,
                task_type="knowledge_rebuild",
                idempotency_key=f"pg-claim-{index}",
            )
    finally:
        db.close()

    def claim(worker: str) -> str | None:
        local = postgres_factory()
        try:
            job = claim_next_job(local, worker)
            return job.id if job else None
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(claim, ["worker-a", "worker-b"]))
    assert None not in claimed
    assert len(set(claimed)) == 2
    db = postgres_factory()
    try:
        assert db.query(BackgroundJob).filter(BackgroundJob.status == "running").count() >= 2
    finally:
        db.close()
