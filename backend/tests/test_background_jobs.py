from datetime import timedelta
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import worker as worker_module
from app.core.config import settings
from app.core.security import hash_password
from app.db.database import Base
from app.db.models import (
    BackgroundJob,
    BackgroundJobArtifact,
    DailyUsageCounter,
    User,
    UsageEvent,
)
from app.services.background_job_service import (
    BackgroundJobError,
    cancel_background_job,
    claim_next_job,
    complete_job,
    create_background_job,
    get_owned_job,
    recover_expired_jobs,
    renew_job_lease,
    serialize_job,
    transition_job,
    update_job_progress,
    utc_now,
    utc_text,
)
from app.services.interview_flow_service import InterviewFlowError
from app.services.usage_service import UsageLimitExceeded, UsageReservationConflict
from auth_test_utils import session_headers


def create_user(db, username: str) -> User:
    user = User(
        username=username,
        password_hash=hash_password("StrongPass123"),
        is_active=True,
        is_admin=False,
        created_at=utc_text(),
        last_login_at=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_threaded_session_factory(tmp_path):
    database_path = (tmp_path / "worker-heartbeat.db").as_posix()
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_job_create_is_idempotent_and_does_not_serialize_input(db_session):
    user = create_user(db_session, "job_owner")
    first, created = create_background_job(
        db_session,
        user_id=user.id,
        task_type="agent_ask",
        idempotency_key="agent-job-0001",
        input_data={"question": "虚构问题", "mode": "local"},
    )
    second, created_again = create_background_job(
        db_session,
        user_id=user.id,
        task_type="agent_ask",
        idempotency_key="agent-job-0001",
        input_data={"question": "不会覆盖", "mode": "web"},
    )

    assert created is True
    assert created_again is False
    assert first.id == second.id
    payload = serialize_job(db_session, first)
    assert "question" not in str(payload)
    assert "worker_id" not in payload
    assert (
        db_session.query(BackgroundJobArtifact)
        .filter(BackgroundJobArtifact.user_id == user.id)
        .count()
        == 1
    )


def test_state_machine_claim_progress_and_terminal_immutability(db_session):
    user = create_user(db_session, "state_owner")
    job, _ = create_background_job(
        db_session,
        user_id=user.id,
        task_type="knowledge_rebuild",
        idempotency_key="knowledge-0001",
    )
    claimed = claim_next_job(db_session, "worker-test")
    assert claimed.id == job.id
    assert claimed.status == "running"
    assert claimed.attempt_count == 1

    progressed = update_job_progress(
        db_session,
        job.id,
        "worker-test",
        progress_percent=40,
        phase="indexing",
        message_code="knowledge_indexing",
    )
    assert progressed.progress_percent == 40
    completed = complete_job(db_session, progressed, "worker-test", {"total_chunks": 2})
    assert completed.status == "succeeded"
    assert completed.progress_percent == 100
    assert serialize_job(db_session, completed)["result"] == {"total_chunks": 2}

    with pytest.raises(BackgroundJobError, match="状态"):
        transition_job(
            db_session,
            completed,
            "failed",
            phase="failed",
            message_code="invalid",
        )


def test_cancel_releases_reserved_quota_once(db_session):
    user = create_user(db_session, "quota_owner")
    job, _ = create_background_job(
        db_session,
        user_id=user.id,
        task_type="job_analysis",
        idempotency_key="quota-job-0001",
        input_data={"job_description": "虚构岗位", "use_web_search": False},
        quota_usage_type="job_analysis",
    )
    event = db_session.get(UsageEvent, job.quota_event_id)
    counter = db_session.query(DailyUsageCounter).filter_by(user_id=user.id).one()
    assert event.status == "reserved"
    assert counter.reserved == 1

    cancelled = cancel_background_job(db_session, user.id, job.id)
    cancelled_again = cancel_background_job(db_session, user.id, job.id)
    db_session.refresh(event)
    db_session.refresh(counter)
    assert cancelled.status == cancelled_again.status == "cancelled"
    assert event.status == "failed"
    assert counter.reserved == 0
    assert counter.used == 0


def test_expired_lease_is_recovered_then_exhausted(db_session):
    user = create_user(db_session, "lease_owner")
    job, _ = create_background_job(
        db_session,
        user_id=user.id,
        task_type="knowledge_rebuild",
        idempotency_key="lease-job-0001",
        max_attempts=2,
    )
    claimed = claim_next_job(db_session, "worker-a")
    claimed.lease_expires_at = utc_text(utc_now() - timedelta(seconds=1))
    db_session.commit()
    summary = recover_expired_jobs(db_session)
    db_session.refresh(claimed)
    assert summary["retried"] == 1
    assert claimed.status == "retry_wait"

    claimed.available_at = utc_text(utc_now() - timedelta(seconds=1))
    db_session.commit()
    claimed_again = claim_next_job(db_session, "worker-b")
    claimed_again.lease_expires_at = utc_text(utc_now() - timedelta(seconds=1))
    db_session.commit()
    summary = recover_expired_jobs(db_session)
    db_session.refresh(claimed_again)
    assert summary["failed"] == 1
    assert claimed_again.status == "failed"


def test_renew_job_lease_requires_running_matching_owner(db_session):
    user = create_user(db_session, "renew_owner")
    job, _ = create_background_job(
        db_session,
        user_id=user.id,
        task_type="knowledge_rebuild",
        idempotency_key="renew-job-0001",
    )
    claimed = claim_next_job(db_session, "worker-renew")
    claimed.lease_expires_at = utc_text(utc_now() - timedelta(seconds=1))
    db_session.commit()

    assert renew_job_lease(db_session, job.id, "worker-renew") is True
    db_session.refresh(claimed)
    assert claimed.lease_expires_at > utc_text()
    assert recover_expired_jobs(db_session)["expired"] == 0

    claimed.worker_id = "worker-other"
    db_session.commit()
    assert renew_job_lease(db_session, job.id, "worker-renew") is False

    claimed.worker_id = "worker-renew"
    claimed.status = "cancel_requested"
    db_session.commit()
    assert renew_job_lease(db_session, job.id, "worker-renew") is False


def test_job_lease_heartbeat_prevents_recovery_and_stops(
    tmp_path,
    monkeypatch,
):
    engine, session_factory = create_threaded_session_factory(tmp_path)
    db = session_factory()
    try:
        user = create_user(db, "heartbeat_owner")
        job, _ = create_background_job(
            db,
            user_id=user.id,
            task_type="knowledge_rebuild",
            idempotency_key="heartbeat-job-0001",
        )
        claimed = claim_next_job(db, "worker-heartbeat")
        claimed.lease_expires_at = utc_text(utc_now() - timedelta(seconds=1))
        db.commit()
        job_id = job.id
    finally:
        db.close()

    renewed = threading.Event()
    renew_count = 0
    original_renew = worker_module.renew_job_lease

    def observed_renew(renew_db, renew_job_id, renew_worker_id):
        nonlocal renew_count
        result = original_renew(renew_db, renew_job_id, renew_worker_id)
        renew_count += 1
        renewed.set()
        return result

    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_module, "renew_job_lease", observed_renew)
    monkeypatch.setattr(settings, "job_heartbeat_seconds", 0.01)
    heartbeat = worker_module.JobLeaseHeartbeat(job_id, "worker-heartbeat")
    heartbeat.start()
    try:
        assert renewed.wait(2)
        recovery_db = session_factory()
        try:
            assert recover_expired_jobs(recovery_db)["expired"] == 0
        finally:
            recovery_db.close()
    finally:
        heartbeat.stop()

    count_after_stop = renew_count
    time.sleep(0.25)
    assert renew_count == count_after_stop
    engine.dispose()


def test_job_lease_heartbeat_stops_after_losing_ownership(
    tmp_path,
    monkeypatch,
):
    engine, session_factory = create_threaded_session_factory(tmp_path)
    db = session_factory()
    try:
        user = create_user(db, "lost_owner")
        job, _ = create_background_job(
            db,
            user_id=user.id,
            task_type="knowledge_rebuild",
            idempotency_key="lost-owner-job-0001",
        )
        claim_next_job(db, "worker-original")
        job_id = job.id
    finally:
        db.close()

    renewed = threading.Event()
    renew_count = 0
    original_renew = worker_module.renew_job_lease

    def observed_renew(renew_db, renew_job_id, renew_worker_id):
        nonlocal renew_count
        result = original_renew(renew_db, renew_job_id, renew_worker_id)
        renew_count += 1
        renewed.set()
        return result

    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_module, "renew_job_lease", observed_renew)
    monkeypatch.setattr(settings, "job_heartbeat_seconds", 0.01)
    heartbeat = worker_module.JobLeaseHeartbeat(job_id, "worker-original")
    heartbeat.start()
    try:
        assert renewed.wait(2)
        ownership_db = session_factory()
        try:
            owned_job = ownership_db.get(BackgroundJob, job_id)
            owned_job.worker_id = "worker-replacement"
            ownership_db.commit()
        finally:
            ownership_db.close()
        deadline = time.monotonic() + 2
        while not heartbeat.lost_ownership and time.monotonic() < deadline:
            time.sleep(0.01)
        assert heartbeat.lost_ownership is True
    finally:
        heartbeat.stop()

    count_after_loss = renew_count
    time.sleep(0.25)
    assert renew_count == count_after_loss
    engine.dispose()


def test_lease_heartbeat_error_does_not_replace_main_task_error(
    tmp_path,
    monkeypatch,
):
    engine, session_factory = create_threaded_session_factory(tmp_path)
    db = session_factory()
    try:
        user = create_user(db, "heartbeat_error_owner")
        job, _ = create_background_job(
            db,
            user_id=user.id,
            task_type="knowledge_rebuild",
            idempotency_key="heartbeat-error-job-0001",
            max_attempts=1,
        )
        claim_next_job(db, "worker-error")
        job_id = job.id
    finally:
        db.close()

    renewal_attempted = threading.Event()
    main_session_ids = []
    renewal_session_ids = []

    def failing_renew(renew_db, renew_job_id, renew_worker_id):
        renewal_session_ids.append(id(renew_db))
        renewal_attempted.set()
        raise RuntimeError("lease renewal failed")

    def failing_execution(main_db, claimed_job, worker_id):
        main_session_ids.append(id(main_db))
        assert renewal_attempted.wait(2)
        raise ValueError("main task failed")

    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_module, "renew_job_lease", failing_renew)
    monkeypatch.setattr(worker_module, "execute_background_job", failing_execution)
    monkeypatch.setattr(settings, "job_heartbeat_seconds", 0.01)

    worker_module.run_job(job_id, "worker-error")

    result_db = session_factory()
    try:
        failed_job = result_db.get(BackgroundJob, job_id)
        assert failed_job.status == "failed"
        assert failed_job.error_code == "ValueError"
    finally:
        result_db.close()
        engine.dispose()
    assert set(main_session_ids).isdisjoint(renewal_session_ids)


def test_job_error_retry_classification_is_explicit():
    assert worker_module._is_retryable_job_error(
        InterviewFlowError(409, "该题目已经回答")
    ) is False
    assert worker_module._is_retryable_job_error(
        UsageLimitExceeded(429, {"message": "今日面试评价额度已用尽"})
    ) is False
    assert worker_module._is_retryable_job_error(
        BackgroundJobError(409, "任务输入引用无效")
    ) is False
    assert worker_module._is_retryable_job_error(
        BackgroundJobError(409, {"error_code": "temporary_conflict"})
    ) is True
    assert worker_module._is_retryable_job_error(
        InterviewFlowError(408, "上游请求超时")
    ) is True
    assert worker_module._is_retryable_job_error(
        InterviewFlowError(429, "外部服务限流")
    ) is True
    assert worker_module._is_retryable_job_error(
        InterviewFlowError(502, "模型服务失败")
    ) is True
    assert worker_module._is_retryable_job_error(
        UsageReservationConflict(409, "相同业务请求正在处理中")
    ) is True


def test_task_api_returns_202_and_isolates_users(client, db_session):
    owner = create_user(db_session, "api_owner")
    other = create_user(db_session, "api_other")
    owner_headers = session_headers(db_session, owner)
    other_headers = session_headers(db_session, other)

    created = client.post(
        "/api/tasks/knowledge-rebuild",
        headers={**owner_headers, "Idempotency-Key": "api-job-0001"},
    )
    assert created.status_code == 202
    assert created.headers["cache-control"] == "no-store"
    task_id = created.json()["task_id"]

    own = client.get(f"/api/tasks/{task_id}", headers=owner_headers)
    hidden = client.get(f"/api/tasks/{task_id}", headers=other_headers)
    hidden_cancel = client.post(
        f"/api/tasks/{task_id}/cancel",
        headers=other_headers,
    )
    assert own.status_code == 200
    assert hidden.status_code == 404
    assert hidden_cancel.status_code == 404
    assert "worker_id" not in own.json()
    assert "input_reference" not in own.json()


def test_task_api_requires_csrf(client, db_session):
    user = create_user(db_session, "csrf_job_owner")
    headers = session_headers(db_session, user)
    headers["X-CSRF-Token"] = ""
    response = client.post(
        "/api/tasks/knowledge-rebuild",
        headers={**headers, "Idempotency-Key": "csrf-job-0001"},
    )
    assert response.status_code == 403


def test_get_owned_job_does_not_disclose_other_user(db_session):
    owner = create_user(db_session, "private_owner")
    other = create_user(db_session, "private_other")
    job, _ = create_background_job(
        db_session,
        user_id=owner.id,
        task_type="knowledge_rebuild",
        idempotency_key="private-job-0001",
    )
    with pytest.raises(BackgroundJobError) as exc:
        get_owned_job(db_session, other.id, job.id)
    assert exc.value.status_code == 404
