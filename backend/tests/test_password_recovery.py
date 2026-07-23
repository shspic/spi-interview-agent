from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.models import (
    AdminAuditLog,
    AuthSecurityEvent,
    AuthSession,
    PasswordResetRequest,
    RateLimitBucket,
    User,
)
from app.services.auth_session_service import utc_now, utc_text
from auth_test_utils import prepare_preauth, session_headers

PASSWORD = "Synthetic-old-password-123!"
NEW_PASSWORD = "Synthetic-new-password-456!"
GENERIC_MESSAGE = "如果账号存在且申请信息有效，管理员会处理你的申请。"


def add_user(db, username, *, admin=False, quota_exempt=False):
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        is_active=True,
        is_admin=admin,
        is_quota_exempt=quota_exempt,
        must_change_password=False,
        temporary_password_expires_at=None,
        created_at=utc_text(),
        last_login_at=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def request_reset(client, username="recovery_user", note="请协助重置"):
    prepare_preauth(client)
    return client.post(
        "/api/auth/password-reset-requests",
        json={"username": username, "request_note": note},
    )


def test_anonymous_response_does_not_enumerate_and_pending_is_deduplicated(
    client,
    db_session,
):
    user = add_user(db_session, "recovery_user")
    existing = request_reset(client)
    missing = request_reset(client, "missing_user")
    repeated = request_reset(client)

    assert existing.status_code == missing.status_code == repeated.status_code == 202
    assert existing.json() == missing.json() == repeated.json()
    assert existing.json()["message"] == GENERIC_MESSAGE
    assert existing.headers["cache-control"] == "no-store"
    assert (
        db_session.query(PasswordResetRequest).filter_by(user_id=user.id).count()
        == 1
    )


def test_request_validation_rate_limit_and_csrf(client, db_session, monkeypatch):
    add_user(db_session, "recovery_user")
    html = request_reset(client, note="<script>bad</script>")
    long_note = request_reset(client, note="x" * 501)
    assert html.status_code == 422
    assert long_note.status_code == 422

    db_session.query(RateLimitBucket).delete()
    db_session.commit()
    monkeypatch.setattr(settings, "password_reset_request_rate_limit_attempts", 1)
    first = request_reset(client)
    second = request_reset(client)
    assert first.status_code == 202
    assert second.status_code == 429

    prepare_preauth(client)
    saved_hooks = list(client.event_hooks["request"])
    client.event_hooks["request"].clear()
    try:
        csrf = client.post(
            "/api/auth/password-reset-requests",
            json={"username": "recovery_user"},
        )
    finally:
        client.event_hooks["request"].extend(saved_hooks)
    assert csrf.status_code == 403


def test_database_prevents_multiple_pending_requests(db_session):
    user = add_user(db_session, "unique_pending")
    now = utc_text()
    db_session.add_all(
        [
            PasswordResetRequest(
                user_id=user.id,
                status="pending",
                request_note="a",
                admin_note="",
                requested_at=now,
                created_at=now,
                updated_at=now,
            ),
            PasswordResetRequest(
                user_id=user.id,
                status="pending",
                request_note="b",
                admin_note="",
                requested_at=now,
                created_at=now,
                updated_at=now,
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_admin_permissions_approval_one_time_secret_and_forced_change(
    client,
    db_session,
):
    admin = add_user(db_session, "recovery_admin", admin=True)
    target = add_user(db_session, "recovery_user", quota_exempt=True)
    ordinary = add_user(db_session, "ordinary_user")
    old_target_headers = session_headers(db_session, target)
    ordinary_headers = session_headers(db_session, ordinary)
    assert request_reset(client).status_code == 202
    reset_request = db_session.query(PasswordResetRequest).one()

    assert client.get("/api/admin/password-reset-requests").status_code == 401
    assert client.get(
        "/api/admin/password-reset-requests",
        headers=ordinary_headers,
    ).status_code == 403
    assert client.post(
        f"/api/admin/password-reset-requests/{reset_request.id}/approve",
        headers=ordinary_headers,
        json={"admin_note": "不允许"},
    ).status_code == 403

    admin_headers = session_headers(db_session, admin)
    listing = client.get(
        "/api/admin/password-reset-requests?status=pending",
        headers=admin_headers,
    )
    assert listing.status_code == 200
    assert listing.json()["items"][0]["username"] == target.username

    approved = client.post(
        f"/api/admin/password-reset-requests/{reset_request.id}/approve",
        headers=admin_headers,
        json={"admin_note": "已核验合成申请"},
    )
    assert approved.status_code == 200
    assert approved.headers["cache-control"] == "no-store"
    temporary_password = approved.json()["temporary_password"]
    assert temporary_password
    db_session.refresh(target)
    assert target.password_hash != temporary_password
    assert verify_password(temporary_password, target.password_hash)
    assert target.must_change_password is True
    assert target.temporary_password_expires_at
    assert target.is_admin is False
    assert target.is_quota_exempt is True
    assert all(
        item.revoked_at is not None
        for item in db_session.query(AuthSession).filter_by(user_id=target.id).all()
    )
    assert client.get("/api/auth/me", headers=old_target_headers).status_code == 401
    logs = db_session.query(AdminAuditLog).filter_by(
        action="approve_password_reset"
    ).all()
    assert len(logs) == 1
    assert temporary_password not in str(
        [(item.detail_summary, item.resource_id) for item in logs]
    )
    repeated = client.post(
        f"/api/admin/password-reset-requests/{reset_request.id}/approve",
        headers=admin_headers,
        json={"admin_note": "再次批准"},
    )
    assert repeated.status_code == 409
    assert "temporary_password" not in repeated.text
    assert db_session.query(AdminAuditLog).filter_by(
        action="approve_password_reset"
    ).count() == 1

    prepare_preauth(client)
    login = client.post(
        "/api/auth/login",
        json={"username": target.username, "password": temporary_password},
    )
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True
    assert client.get("/api/auth/me").status_code == 200
    blocked = client.get("/api/profile")
    assert blocked.status_code == 403
    assert blocked.json()["error_code"] == "password_change_required"
    assert client.get("/api/admin/users").status_code == 403

    changed = client.post(
        "/api/auth/change-temporary-password",
        json={"new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
    )
    assert changed.status_code == 200
    db_session.refresh(target)
    assert target.must_change_password is False
    assert target.temporary_password_expires_at is None
    assert verify_password(NEW_PASSWORD, target.password_hash)
    assert db_session.query(AuthSecurityEvent).filter_by(
        user_id=target.id,
        event_type="temporary_password_changed",
    ).count() == 1
    assert client.get("/api/auth/me").status_code == 401

    prepare_preauth(client)
    old_login = client.post(
        "/api/auth/login",
        json={"username": target.username, "password": temporary_password},
    )
    assert old_login.status_code == 401
    new_login = client.post(
        "/api/auth/login",
        json={"username": target.username, "password": NEW_PASSWORD},
    )
    assert new_login.status_code == 200
    assert new_login.json()["user"]["must_change_password"] is False


def test_rejection_does_not_change_password_or_revoke_session(client, db_session):
    admin = add_user(db_session, "reject_admin", admin=True)
    target = add_user(db_session, "reject_target")
    target_headers = session_headers(db_session, target)
    session = db_session.query(AuthSession).filter_by(user_id=target.id).one()
    password_hash = target.password_hash
    assert request_reset(client, target.username).status_code == 202
    item = db_session.query(PasswordResetRequest).one()

    rejected = client.post(
        f"/api/admin/password-reset-requests/{item.id}/reject",
        headers=session_headers(db_session, admin),
        json={"admin_note": "信息不足"},
    )
    assert rejected.status_code == 200
    db_session.refresh(target)
    db_session.refresh(session)
    assert target.password_hash == password_hash
    assert target.must_change_password is False
    assert session.revoked_at is None
    assert client.get("/api/auth/me", headers=target_headers).status_code == 200
    assert db_session.query(AdminAuditLog).filter_by(
        action="reject_password_reset",
        status="success",
    ).count() == 1


def test_expired_temporary_password_cannot_login(client, db_session):
    target = add_user(db_session, "expired_target")
    target.must_change_password = True
    target.temporary_password_expires_at = utc_text(utc_now() - timedelta(minutes=1))
    db_session.commit()
    prepare_preauth(client)
    response = client.post(
        "/api/auth/login",
        json={"username": target.username, "password": PASSWORD},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "temporary_password_expired"
    assert db_session.query(AuthSession).filter_by(user_id=target.id).count() == 0


def test_active_temporary_session_cannot_change_after_expiry(client, db_session):
    target = add_user(db_session, "session_expired_target")
    target.must_change_password = True
    target.temporary_password_expires_at = utc_text(
        utc_now() + timedelta(minutes=5)
    )
    db_session.commit()
    prepare_preauth(client)
    logged_in = client.post(
        "/api/auth/login",
        json={"username": target.username, "password": PASSWORD},
    )
    assert logged_in.status_code == 200

    target.temporary_password_expires_at = utc_text(
        utc_now() - timedelta(minutes=1)
    )
    db_session.commit()
    response = client.post(
        "/api/auth/change-temporary-password",
        json={"new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "temporary_password_expired"
    db_session.refresh(target)
    assert target.must_change_password is True
    assert verify_password(PASSWORD, target.password_hash)
