from datetime import datetime, timedelta, timezone

import pytest

from app.api import chat as chat_api
from app.api import jobs as jobs_api
from app.core.config import settings
from app.core.security import hash_password, verify_password
from auth_test_utils import session_headers
from app.db.models import (
    AdminAuditLog,
    BackgroundJob,
    DailyUsageCounter,
    FileRecord,
    HistoryRecord,
    RegistrationSetting,
    UsageEvent,
    User,
    WorkerHeartbeat,
)
from app.services import admin_service
from app.services.usage_service import (
    UsageLimitExceeded,
    UsageReservationConflict,
    commit_usage,
    get_user_usage,
    release_usage,
    reserve_usage,
)


def add_user(
    db_session,
    username: str,
    *,
    is_admin: bool = False,
    is_quota_exempt: bool = False,
    is_active: bool = True,
    password_hash: str = "unused-test-password-hash",
) -> User:
    user = User(
        username=username,
        password_hash=password_hash,
        is_active=is_active,
        is_admin=is_admin,
        is_quota_exempt=is_quota_exempt,
        created_at=datetime.now().isoformat(timespec="seconds"),
        last_login_at=None,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def auth_headers(db_session, user: User) -> dict:
    return session_headers(db_session, user)


def test_usage_reservation_commit_idempotency_and_user_isolation(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "daily_chat_limit", 2)
    first_user = add_user(db_session, "usage_a")
    second_user = add_user(db_session, "usage_b")

    reservation = reserve_usage(
        db_session,
        first_user.id,
        "chat",
        "chat-request-1",
    )
    assert get_user_usage(db_session, first_user.id)["items"][0]["reserved"] == 1
    commit_usage(db_session, reservation)

    duplicate = reserve_usage(
        db_session,
        first_user.id,
        "chat",
        "chat-request-1",
    )
    assert duplicate.already_succeeded is True
    first_usage = get_user_usage(db_session, first_user.id)["items"][0]
    second_usage = get_user_usage(db_session, second_user.id)["items"][0]
    assert first_usage["used"] == 1
    assert first_usage["reserved"] == 0
    assert second_usage["used"] == 0


def test_reserved_blocks_limit_and_release_restores_capacity(db_session, monkeypatch):
    monkeypatch.setattr(settings, "daily_chat_limit", 1)
    user = add_user(db_session, "usage_limit")
    reservation = reserve_usage(db_session, user.id, "chat", "first")

    with pytest.raises(UsageLimitExceeded) as exc_info:
        reserve_usage(db_session, user.id, "chat", "second")
    detail = exc_info.value.detail
    assert detail["limit"] == 1
    assert detail["used"] == 0
    assert detail["reserved"] == 1
    assert detail["remaining"] == 0
    assert detail["reset_at"]

    release_usage(db_session, reservation, "TestFailure")
    recovered = reserve_usage(db_session, user.id, "chat", "second")
    commit_usage(db_session, recovered)
    assert get_user_usage(db_session, user.id)["items"][0]["used"] == 1


def test_admin_without_quota_exemption_is_still_limited(
    client,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "daily_chat_limit", 0)
    admin = add_user(db_session, "limited_admin", is_admin=True)

    assert client.get(
        "/api/admin/users",
        headers=auth_headers(db_session, admin),
    ).status_code == 200
    with pytest.raises(UsageLimitExceeded):
        reserve_usage(db_session, admin.id, "chat", "limited-admin-chat")


def test_quota_exempt_user_keeps_accounting_release_and_conflict_semantics(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "daily_chat_limit", 1)
    monkeypatch.setattr(settings, "daily_job_analysis_limit", 1)
    monkeypatch.setattr(settings, "daily_interview_evaluation_limit", 1)
    monkeypatch.setattr(settings, "daily_multi_agent_task_limit", 1)
    user = add_user(db_session, "unlimited_user", is_quota_exempt=True)
    usage_types = (
        "chat",
        "job_analysis",
        "interview_evaluation",
        "multi_agent_task",
    )

    for usage_type in usage_types:
        first = reserve_usage(db_session, user.id, usage_type, f"{usage_type}-1")
        commit_usage(db_session, first)
        failed = reserve_usage(db_session, user.id, usage_type, f"{usage_type}-failed")
        with pytest.raises(UsageReservationConflict):
            reserve_usage(db_session, user.id, usage_type, f"{usage_type}-failed")
        release_usage(db_session, failed, "TestFailure")
        second = reserve_usage(db_session, user.id, usage_type, f"{usage_type}-2")
        commit_usage(db_session, second)

    usage = {item["usage_type"]: item for item in get_user_usage(db_session, user.id)["items"]}
    assert set(usage) == set(usage_types)
    assert all(item["unlimited"] is True for item in usage.values())
    assert all(item["limit"] is None for item in usage.values())
    assert all(item["remaining"] is None for item in usage.values())
    assert all(item["used"] == 2 for item in usage.values())
    assert all(item["reserved"] == 0 for item in usage.values())
    assert db_session.query(UsageEvent).filter_by(user_id=user.id).count() == 12
    assert db_session.query(UsageEvent).filter_by(
        user_id=user.id,
        status="failed",
    ).count() == 4


def test_usage_is_recalculated_for_new_natural_day(db_session, monkeypatch):
    monkeypatch.setattr(settings, "daily_chat_limit", 1)
    user = add_user(db_session, "usage_day")
    first_day = datetime(2026, 7, 18, 23, 50)
    second_day = datetime(2026, 7, 19, 0, 10)
    first = reserve_usage(db_session, user.id, "chat", "day-one", now=first_day)
    commit_usage(db_session, first)
    second = reserve_usage(db_session, user.id, "chat", "day-two", now=second_day)
    assert second.already_succeeded is False


def test_stale_reserved_usage_is_released_before_new_reservation(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "daily_chat_limit", 1)
    user = add_user(db_session, "usage_stale")
    local_now = datetime(2026, 7, 19, 12, 0)
    stale = reserve_usage(
        db_session,
        user.id,
        "chat",
        "stale",
        now=local_now,
    )
    event = db_session.get(UsageEvent, stale.event_id)
    event.reserved_at = "2000-01-01T00:00:00+08:00"
    db_session.commit()

    fresh = reserve_usage(
        db_session,
        user.id,
        "chat",
        "fresh",
        now=local_now,
    )

    db_session.refresh(event)
    assert event.status == "released"
    assert event.error_type == "reservation_timeout"
    assert fresh.already_succeeded is False


def test_chat_success_counts_and_failure_releases(
    client,
    db_session,
    monkeypatch,
):
    user = add_user(db_session, "chat_user")
    headers = auth_headers(db_session, user)
    monkeypatch.setattr(
        chat_api,
        "ask_with_rag",
        lambda **kwargs: {"answer": "ok"},
    )
    response = client.post(
        "/api/chat/ask",
        headers=headers,
        json={"question": "test"},
    )
    assert response.status_code == 200
    assert db_session.query(UsageEvent).filter_by(
        user_id=user.id,
        usage_type="chat",
        status="succeeded",
    ).count() == 1

    monkeypatch.setattr(
        chat_api,
        "ask_with_rag",
        lambda **kwargs: (_ for _ in ()).throw(chat_api.ChatServiceError("failed")),
    )
    response = client.post(
        "/api/chat/ask",
        headers=headers,
        json={"question": "fail"},
    )
    assert response.status_code == 400
    counter = db_session.query(DailyUsageCounter).filter_by(
        user_id=user.id,
        usage_type="chat",
    ).one()
    assert counter.used == 1
    assert counter.reserved == 0
    assert client.post(
        "/api/chat/ask",
        headers=headers,
        json={"question": "x", "user_id": 999},
    ).status_code == 422


def test_usage_me_only_returns_current_user(client, db_session):
    first = add_user(db_session, "usage_me_a")
    second = add_user(db_session, "usage_me_b")
    reservation = reserve_usage(db_session, second.id, "chat", "other")
    commit_usage(db_session, reservation)

    response = client.get("/api/usage/me", headers=auth_headers(db_session, first))
    assert response.status_code == 200
    payload = response.json()
    assert payload["timezone"] == "Asia/Shanghai"
    assert len(payload["items"]) == 4
    assert all(item["used"] == 0 for item in payload["items"])


def test_job_analysis_counts_and_api_limit_returns_structured_429(
    client,
    db_session,
    monkeypatch,
):
    user = add_user(db_session, "job_usage")
    headers = auth_headers(db_session, user)
    monkeypatch.setattr(
        jobs_api,
        "analyze_job",
        lambda **kwargs: {"analysis": "ok"},
    )
    assert client.post(
        "/api/jobs/analyze",
        headers=headers,
        json={"job_description": "backend"},
    ).status_code == 200
    assert db_session.query(UsageEvent).filter_by(
        user_id=user.id,
        usage_type="job_analysis",
        status="succeeded",
    ).count() == 1

    monkeypatch.setattr(settings, "daily_chat_limit", 0)
    response = client.post(
        "/api/chat/ask",
        headers=headers,
        json={"question": "limited"},
    )
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["usage_type"] == "chat"
    assert set(("limit", "used", "remaining", "reset_at")) <= detail.keys()


def test_admin_access_user_list_and_disable_invalidates_existing_jwt(
    client,
    db_session,
):
    admin = add_user(db_session, "admin_one", is_admin=True)
    user = add_user(db_session, "normal_one")
    admin_headers = auth_headers(db_session, admin)
    user_headers = auth_headers(db_session, user)

    assert client.get("/api/admin/users").status_code == 401
    assert client.get("/api/admin/users", headers=user_headers).status_code == 403
    response = client.get("/api/admin/users", headers=admin_headers)
    assert response.status_code == 200
    assert "password_hash" not in str(response.json())

    response = client.patch(
        f"/api/admin/users/{user.id}/status",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert client.get("/api/auth/me", headers=user_headers).status_code == 401
    assert client.patch(
        f"/api/admin/users/{user.id}/status",
        headers=admin_headers,
        json={"is_active": True, "is_admin": True, "is_quota_exempt": True},
    ).status_code == 422
    assert db_session.query(AdminAuditLog).filter_by(
        action="disable_user",
        status="success",
    ).count() == 1


def test_last_admin_protection_and_self_delete_are_rejected(client, db_session):
    admin = add_user(db_session, "only_admin", is_admin=True)
    headers = auth_headers(db_session, admin)
    assert client.patch(
        f"/api/admin/users/{admin.id}/status",
        headers=headers,
        json={"is_active": False},
    ).status_code == 409
    assert client.request(
        "DELETE",
        f"/api/admin/users/{admin.id}",
        headers=headers,
        json={"confirm_username": admin.username},
    ).status_code == 409


def test_admin_password_reset_uses_hash_and_does_not_leak_password(
    client,
    db_session,
):
    old_password = "old-password-123"
    new_password = "new-password-456"
    admin = add_user(db_session, "password_admin", is_admin=True)
    user = add_user(
        db_session,
        "password_user",
        password_hash=hash_password(old_password),
    )
    response = client.post(
        f"/api/admin/users/{user.id}/reset-password",
        headers=auth_headers(db_session, admin),
        json={"new_password": new_password},
    )
    assert response.status_code == 200
    assert new_password not in response.text
    db_session.refresh(user)
    assert not verify_password(old_password, user.password_hash)
    assert verify_password(new_password, user.password_hash)
    assert user.must_change_password is True
    assert user.temporary_password_expires_at is not None
    assert response.headers["cache-control"] == "no-store"
    logs = db_session.query(AdminAuditLog).filter_by(action="reset_password").all()
    assert logs and all(new_password not in log.detail_summary for log in logs)


def test_invite_code_is_hashed_and_admin_update_invalidates_old_code(
    client,
    db_session,
):
    admin = add_user(db_session, "invite_admin", is_admin=True)
    user = add_user(db_session, "invite_normal")
    headers = auth_headers(db_session, admin)
    new_code = "new-test-invite"
    response = client.put(
        "/api/admin/settings/registration/invite-code",
        headers=headers,
        json={"invite_code": new_code},
    )
    assert response.status_code == 200
    assert new_code not in response.text
    registration_setting = db_session.get(RegistrationSetting, 1)
    assert registration_setting.invite_code_hash != new_code
    assert verify_password(new_code, registration_setting.invite_code_hash)
    status_response = client.get(
        "/api/admin/settings/registration",
        headers=headers,
    )
    assert "invite_code_hash" not in status_response.text
    assert new_code not in status_response.text
    assert client.put(
        "/api/admin/settings/registration/invite-code",
        headers=auth_headers(db_session, user),
        json={"invite_code": "another-code"},
    ).status_code == 403

    old_response = client.post(
        "/api/auth/register",
        json={
            "username": "old_invite_user",
            "password": "strong-password-123",
            "invite_code": "test-invite-code",
        },
    )
    assert old_response.status_code == 403
    new_response = client.post(
        "/api/auth/register",
        json={
            "username": "new_invite_user",
            "password": "strong-password-123",
            "invite_code": new_code,
        },
    )
    assert new_response.status_code == 201


def test_delete_user_cleans_files_vectors_and_database_without_cross_user_damage(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    admin = add_user(db_session, "delete_admin", is_admin=True)
    target = add_user(db_session, "delete_target")
    other = add_user(db_session, "delete_other")
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_root))
    target_path = upload_root / str(target.id) / "target.txt"
    target_path.parent.mkdir(parents=True)
    target_path.write_text("target", encoding="utf-8")
    other_path = upload_root / str(other.id) / "other.txt"
    other_path.parent.mkdir(parents=True)
    other_path.write_text("other", encoding="utf-8")
    now = datetime.now().isoformat(timespec="seconds")
    db_session.add_all(
        [
            FileRecord(
                user_id=target.id,
                file_id="target-file",
                filename="target.txt",
                file_type="txt",
                file_path=str(target_path),
                category="project",
                status="indexed",
                created_at=now,
                updated_at=now,
            ),
            FileRecord(
                user_id=other.id,
                file_id="other-file",
                filename="other.txt",
                file_type="txt",
                file_path=str(other_path),
                category="project",
                status="indexed",
                created_at=now,
                updated_at=now,
            ),
            HistoryRecord(
                user_id=target.id,
                record_id="target-history",
                mode="chat",
                user_input="hidden",
                ai_output="hidden",
                created_at=now,
            ),
        ]
    )
    db_session.commit()
    deleted_vectors = []
    monkeypatch.setattr(
        admin_service,
        "delete_user_vectors",
        lambda user_id: deleted_vectors.append(user_id),
    )

    mismatch = client.request(
        "DELETE",
        f"/api/admin/users/{target.id}",
        headers=auth_headers(db_session, admin),
        json={"confirm_username": "wrong_username"},
    )
    assert mismatch.status_code == 422

    response = client.request(
        "DELETE",
        f"/api/admin/users/{target.id}",
        headers=auth_headers(db_session, admin),
        json={"confirm_username": target.username},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert deleted_vectors == [target.id]
    assert not target_path.exists()
    assert other_path.exists()
    assert db_session.get(User, target.id) is None
    assert db_session.get(User, other.id) is not None
    assert db_session.query(FileRecord).filter_by(file_id="other-file").count() == 1


def test_delete_user_reports_vector_failure_without_claiming_success(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    admin = add_user(db_session, "delete_fail_admin", is_admin=True)
    target = add_user(db_session, "delete_fail_target")
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_root))
    file_path = upload_root / str(target.id) / "target.txt"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("target", encoding="utf-8")
    now = datetime.now().isoformat(timespec="seconds")
    db_session.add(
        FileRecord(
            user_id=target.id,
            file_id="delete-fail-file",
            filename="target.txt",
            file_type="txt",
            file_path=str(file_path),
            category="project",
            status="indexed",
            created_at=now,
            updated_at=now,
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        admin_service,
        "delete_user_vectors",
        lambda user_id: (_ for _ in ()).throw(RuntimeError("failed")),
    )

    response = client.request(
        "DELETE",
        f"/api/admin/users/{target.id}",
        headers=auth_headers(db_session, admin),
        json={"confirm_username": target.username},
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["failed_items"][0]["resource_type"] == "vector"
    assert db_session.get(User, target.id) is not None
    assert file_path.exists()


def test_admin_can_read_sanitized_background_jobs_and_worker_status(
    client,
    db_session,
):
    admin = add_user(db_session, "jobs_admin", is_admin=True)
    user = add_user(db_session, "jobs_user")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    db_session.add_all(
        [
            BackgroundJob(
                id="job-admin-report",
                user_id=user.id,
                task_type="agent_ask",
                status="running",
                progress_percent=45,
                phase="executing",
                message_code="job_running",
                idempotency_key_hash="hidden-hash",
                created_at=now,
                available_at=now,
                heartbeat_at=now,
                lease_expires_at=now,
                attempt_count=1,
                max_attempts=3,
                timeout_seconds=900,
                worker_id="secret-worker-id",
            ),
            WorkerHeartbeat(
                worker_id="secret-worker-id",
                database_dialect="sqlite",
                started_at=now,
                heartbeat_at=now,
                stopped_at=None,
            ),
        ]
    )
    db_session.commit()

    jobs = client.get(
        "/api/admin/background-jobs",
        headers=auth_headers(db_session, admin),
    )
    workers = client.get(
        "/api/admin/workers",
        headers=auth_headers(db_session, admin),
    )

    assert jobs.status_code == 200
    item = jobs.json()["items"][0]
    assert item["id"] == "job-admin-report"
    assert "worker_id" not in item
    assert "lease_expires_at" not in item
    assert "idempotency_key_hash" not in item
    assert workers.status_code == 200
    assert workers.json()["online_count"] == 1
    assert workers.json()["workers"][0]["label"] == "Worker 1"
    assert "worker_id" not in workers.json()["workers"][0]
    assert "secret-worker-id" not in workers.text
