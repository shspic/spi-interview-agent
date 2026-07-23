import pytest

from app.core.config import settings
from app.core.security import verify_password
from app.db.models import RegistrationSetting, User

VALID_PASSWORD = "strong-password-123"


def register(client, username="alice", invite_code="test-invite-code"):
    return client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": VALID_PASSWORD,
            "invite_code": invite_code,
        },
    )


def test_correct_invite_code_can_register(client, db_session):
    response = register(client)

    assert response.status_code == 201
    assert response.json()["user"]["username"] == "alice"
    assert response.json()["user"]["is_admin"] is False
    assert response.json()["user"]["is_quota_exempt"] is False
    user = db_session.query(User).filter_by(username="alice").one()
    assert user.is_admin is False
    assert user.is_quota_exempt is False
    registration_setting = db_session.get(RegistrationSetting, 1)
    assert registration_setting.invite_code_hash != "test-invite-code"
    assert verify_password(
        "test-invite-code",
        registration_setting.invite_code_hash,
    )


def test_missing_invite_configuration_returns_controlled_503(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "registration_invite_code", "")

    response = register(client)

    assert response.status_code == 503
    assert response.json()["detail"] == "注册邀请码尚未配置"


def test_wrong_invite_code_cannot_register(client):
    response = register(client, invite_code="wrong-code")

    assert response.status_code == 403
    assert response.json()["detail"] == "邀请码无效"


def test_duplicate_username_cannot_register(client):
    assert register(client).status_code == 201

    response = register(client, username="ALICE")

    assert response.status_code == 409
    assert response.json()["detail"] == "用户名已存在"


def test_password_is_saved_as_hash(client, db_session):
    assert register(client).status_code == 201

    user = db_session.query(User).filter(User.username == "alice").one()

    assert user.password_hash != VALID_PASSWORD
    assert verify_password(VALID_PASSWORD, user.password_hash)


def test_correct_password_can_login(client):
    assert register(client).status_code == 201

    response = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": VALID_PASSWORD},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "token_type" not in payload
    assert "access_token" not in payload

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["user"]["username"] == "alice"


def test_wrong_password_cannot_login(client):
    assert register(client).status_code == 201

    response = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "invalid_credentials"


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/files", None),
        ("get", "/api/knowledge/status", None),
        ("post", "/api/chat/ask", {"question": "test"}),
        ("post", "/api/jobs/analyze", {"job_description": "test"}),
        ("post", "/api/interview/question", {"job_description": "test"}),
        ("get", "/api/interview-records", None),
        ("post", "/api/agent/ask", {"question": "test"}),
        ("get", "/api/history", None),
        ("get", "/api/system/status", None),
        ("get", "/api/profile", None),
        ("get", "/api/target-jobs", None),
    ],
)
def test_unauthenticated_request_cannot_access_protected_api(
    client,
    method,
    path,
    payload,
):
    response = client.request(method, path, json=payload)

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth_required"
