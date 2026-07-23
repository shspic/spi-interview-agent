from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import jwt
from fastapi.testclient import TestClient
from starlette.responses import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, settings
from app.core.security import hash_password
from app.db.database import Base
from app.db.models import AuthSecurityEvent, AuthSession, DailyUsageCounter, User
from app.main import app
from app.services.auth_session_service import (
    create_session,
    hash_secret,
    rotate_refresh_token,
    set_auth_cookies,
)
from auth_test_utils import cookie_headers, prepare_preauth

PASSWORD = "strong-password-123"


def register_and_login(client, username="alice"):
    prepare_preauth(client)
    register = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "invite_code": "test-invite-code",
        },
    )
    assert register.status_code == 201
    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login.status_code == 200
    return login, cookie_headers(client)


def login_existing(client, username="alice"):
    prepare_preauth(client)
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response, cookie_headers(client)


def test_login_sets_secure_cookie_shape_and_safe_payload(client, db_session):
    response, headers = register_and_login(client)
    payload = response.json()
    assert payload["user"]["username"] == "alice"
    assert not {"access_token", "refresh_token", "token", "token_type"} & payload.keys()
    cookies = response.headers.get_list("set-cookie")
    access = next(item for item in cookies if item.startswith("spi_access="))
    refresh = next(item for item in cookies if item.startswith("spi_refresh="))
    csrf = next(item for item in cookies if item.startswith("spi_csrf="))
    assert "HttpOnly" in access and "Path=/api" in access and "SameSite=lax" in access
    assert "HttpOnly" in refresh and "Path=/api/auth" in refresh
    assert "HttpOnly" not in csrf and "Path=/" in csrf
    assert "Secure" not in access

    auth_session = db_session.query(AuthSession).one()
    raw_refresh = client.cookies.get(settings.auth_refresh_cookie_name)
    assert auth_session.refresh_token_hash == hash_secret(raw_refresh)
    assert raw_refresh not in auth_session.refresh_token_hash
    assert db_session.query(AuthSecurityEvent).filter_by(event_type="login_success").count() == 1
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.headers["cache-control"] == "no-store"


def test_access_payload_is_short_lived_and_session_bound(client):
    register_and_login(client)
    access_token = client.cookies.get(settings.auth_access_cookie_name)
    payload = jwt.decode(
        access_token,
        settings.jwt_secret_key,
        algorithms=["HS256"],
    )
    assert payload["token_type"] == "access"
    assert payload["session_id"]
    assert payload["jti"]
    assert payload["sub"]
    assert payload["exp"] - payload["iat"] == settings.jwt_expire_minutes * 60
    assert "password" not in payload and "invite_code" not in payload


def test_refresh_rotates_once_without_new_session_or_usage(client, db_session):
    register_and_login(client)
    old_headers = cookie_headers(client)
    old_refresh = client.cookies.get(settings.auth_refresh_cookie_name)
    before_session_count = db_session.query(AuthSession).count()
    before_usage = db_session.query(DailyUsageCounter).count()
    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert client.cookies.get(settings.auth_refresh_cookie_name) != old_refresh
    assert db_session.query(AuthSession).count() == before_session_count
    assert db_session.query(DailyUsageCounter).count() == before_usage
    repeated = client.post("/api/auth/refresh", headers=old_headers)
    assert repeated.status_code == 401
    assert repeated.json()["error_code"] == "refresh_failed"


def test_permission_fields_are_current_across_login_refresh_and_me(
    client,
    db_session,
):
    register_and_login(client)
    user = db_session.query(User).filter_by(username="alice").one()
    user.is_admin = True
    user.is_quota_exempt = True
    db_session.commit()

    login, _ = login_existing(client)
    assert login.json()["user"]["is_admin"] is True
    assert login.json()["user"]["is_quota_exempt"] is True
    me = client.get("/api/auth/me")
    assert me.json()["user"]["is_admin"] is True
    assert me.json()["user"]["is_quota_exempt"] is True
    refreshed = client.post("/api/auth/refresh")
    assert refreshed.json()["user"]["is_admin"] is True
    assert refreshed.json()["user"]["is_quota_exempt"] is True


def test_refresh_ignores_body_token_and_clears_invalid_cookies(client):
    client.cookies.clear()
    response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": "forged-body-token"},
        headers={"X-CSRF-Token": "forged"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "refresh_failed"
    assert any("spi_refresh=\"\"" in item for item in response.headers.get_list("set-cookie"))


def test_revocation_disable_and_reenable_never_restore_session(client, db_session):
    _, headers = register_and_login(client)
    user = db_session.query(User).filter_by(username="alice").one()
    auth_session = db_session.query(AuthSession).filter_by(user_id=user.id).one()
    auth_session.revoked_at = "2026-07-20T00:00:00+00:00"
    auth_session.revoke_reason = "test"
    db_session.commit()
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    user.is_active = False
    db_session.commit()
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    user.is_active = True
    db_session.commit()
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_max_sessions_revokes_oldest(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "auth_max_active_sessions", 2)
    _, first = register_and_login(client)
    _, second = login_existing(client)
    _, third = login_existing(client)
    sessions = db_session.query(AuthSession).order_by(AuthSession.created_at, AuthSession.id).all()
    assert len(sessions) == 3
    assert sum(item.revoked_at is None for item in sessions) == 2
    assert client.get("/api/auth/me", headers=first).status_code == 401
    assert client.get("/api/auth/me", headers=second).status_code == 200
    assert client.get("/api/auth/me", headers=third).status_code == 200


def test_csrf_missing_mismatch_signature_and_cross_session_are_rejected(client):
    _, alice = register_and_login(client, "alice")
    saved_hooks = list(client.event_hooks["request"])
    client.event_hooks["request"].clear()
    try:
        missing = client.post("/api/auth/logout-all", headers={"Cookie": alice["Cookie"]})
        assert missing.status_code == 403
        mismatch = client.post(
            "/api/auth/logout-all",
            headers={"Cookie": alice["Cookie"], "X-CSRF-Token": "mismatch"},
        )
        assert mismatch.status_code == 403
        forged_cookie = alice["Cookie"].replace("spi_csrf=", "spi_csrf=forged-")
        forged = client.post(
            "/api/auth/logout-all",
            headers={"Cookie": forged_cookie, "X-CSRF-Token": "forged"},
        )
        assert forged.status_code == 403
    finally:
        client.event_hooks["request"].extend(saved_hooks)

    _, bob = register_and_login(client, "bob")
    alice_access = next(item for item in alice["Cookie"].split("; ") if item.startswith("spi_access="))
    bob_csrf = next(item for item in bob["Cookie"].split("; ") if item.startswith("spi_csrf="))
    cross = client.post(
        "/api/auth/logout-all",
        headers={"Cookie": f"{alice_access}; {bob_csrf}", "X-CSRF-Token": bob["X-CSRF-Token"]},
    )
    assert cross.status_code == 403


def test_origin_check_rejects_malicious_and_allows_configured(client):
    _, headers = register_and_login(client)
    rejected = client.post(
        "/api/auth/logout-all",
        headers={**headers, "Origin": "https://evil.example"},
    )
    assert rejected.status_code == 403
    accepted = client.post(
        "/api/auth/logout-all",
        headers={**headers, "Origin": "http://testserver"},
    )
    assert accepted.status_code == 200


def test_logout_current_and_logout_all_are_scoped(client, db_session):
    _, first = register_and_login(client)
    _, second = login_existing(client)
    first_logout = client.post("/api/auth/logout", headers=first)
    assert first_logout.status_code == 200
    sessions = db_session.query(AuthSession).all()
    assert sum(item.revoked_at is None for item in sessions) == 1
    assert client.get("/api/auth/me", headers=second).status_code == 200
    all_logout = client.post("/api/auth/logout-all", headers=second)
    assert all_logout.status_code == 200
    assert all(item.revoked_at is not None for item in sessions)
    client.cookies.clear()
    assert client.post("/api/auth/logout").status_code == 200


def test_password_change_revokes_every_session(client, db_session):
    _, first = register_and_login(client)
    _, second = login_existing(client)
    changed = client.post(
        "/api/auth/change-password",
        headers=second,
        json={
            "current_password": PASSWORD,
            "new_password": "new-strong-password-456",
            "confirm_password": "new-strong-password-456",
        },
    )
    assert changed.status_code == 200
    assert all(item.revoked_at is not None for item in db_session.query(AuthSession).all())
    assert client.get("/api/auth/me", headers=first).status_code == 401


def test_bearer_is_rejected_and_cookie_bearer_conflict_is_rejected(client):
    _, headers = register_and_login(client)
    client.cookies.clear()
    bearer = client.get("/api/auth/me", headers={"Authorization": "Bearer legacy-token"})
    assert bearer.status_code == 401
    conflict = client.get(
        "/api/auth/me",
        headers={**headers, "Authorization": "Bearer conflicting-token"},
    )
    assert conflict.status_code == 401
    assert conflict.json()["error_code"] == "auth_conflict"


def test_invalid_cookie_configuration_fails_validation():
    try:
        Settings(auth_cookie_samesite="none", auth_cookie_secure=False)
        raise AssertionError("配置校验未生效")
    except ValueError:
        pass
    try:
        Settings(auth_cookie_samesite="invalid")
        raise AssertionError("配置校验未生效")
    except ValueError:
        pass


def test_refresh_token_atomic_rotation_allows_only_one_success(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auth_csrf_secret", "test-csrf-secret-with-sufficient-length")
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'refresh-race.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    setup = factory()
    user = User(
        username="race-user",
        password_hash=hash_password(PASSWORD),
        is_active=True,
        is_admin=False,
        created_at="2026-07-20T00:00:00",
    )
    setup.add(user)
    setup.commit()
    auth_session, refresh_token, _ = create_session(setup, user)
    session_id = auth_session.id
    setup.commit()
    setup.close()
    barrier = Barrier(2)

    def rotate():
        db = factory()
        try:
            current = db.get(AuthSession, session_id)
            barrier.wait()
            result = rotate_refresh_token(db, current, refresh_token)
            if result is not None:
                db.commit()
            return result is not None
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: rotate(), range(2)))
    engine.dispose()
    assert results.count(True) == 1
    assert results.count(False) == 1


def test_preauth_csrf_is_required_for_login_and_register(client):
    prepare_preauth(client)
    saved_hooks = list(client.event_hooks["request"])
    client.event_hooks["request"].clear()
    try:
        register = client.post(
            "/api/auth/register",
            json={
                "username": "missing-csrf",
                "password": PASSWORD,
                "invite_code": "test-invite-code",
            },
        )
        login = client.post(
            "/api/auth/login",
            json={"username": "missing-csrf", "password": PASSWORD},
        )
    finally:
        client.event_hooks["request"].extend(saved_hooks)
    assert register.status_code == 403
    assert login.status_code == 403


def test_cookie_secure_flag_can_be_enabled(monkeypatch):
    monkeypatch.setattr(settings, "auth_cookie_secure", True)
    response = Response()
    set_auth_cookies(
        response,
        access_token="access-placeholder",
        refresh_token="refresh-placeholder",
        csrf_token="csrf-placeholder",
    )
    auth_cookies = response.headers.getlist("set-cookie")
    assert auth_cookies and all("Secure" in item for item in auth_cookies)


def test_auth_routes_do_not_accept_query_refresh_token(client):
    response = client.post("/api/auth/refresh?refresh_token=forged")
    assert response.status_code == 401
    assert "forged" not in response.text


def test_test_client_is_cookie_authenticated_not_bearer(client: TestClient):
    _, headers = register_and_login(client)
    assert "Authorization" not in headers
    assert "spi_access=" in headers["Cookie"]
    assert client.get("/api/auth/me", headers=headers).status_code == 200


def test_minimal_cookie_auth_smoke(client):
    register_and_login(client, "smoke_user")
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/refresh").status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_frontend_auth_source_uses_cookie_csrf_and_safe_replay_only():
    frontend_src = Path(__file__).resolve().parents[2] / "frontend" / "src"
    client_source = (frontend_src / "api" / "client.js").read_text(encoding="utf-8")
    provider_source = (frontend_src / "auth" / "AuthProvider.jsx").read_text(
        encoding="utf-8"
    )
    combined = client_source + provider_source
    assert "localStorage" not in combined
    assert "sessionStorage" not in combined
    assert "Authorization" not in combined
    assert "Bearer" not in combined
    assert "access_token" not in combined
    assert "refresh_token" not in combined
    assert "withCredentials: true" in client_source
    assert 'config.headers["X-CSRF-Token"]' in client_source
    assert "refreshPromise" in client_source
    assert "SAFE_METHODS.has(method)" in client_source
    assert 'apiClient.get("/api/auth/me")' in provider_source
