import pytest

from app.core.security import verify_password
from app.db.models import User

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


def test_correct_invite_code_can_register(client):
    response = register(client)

    assert response.status_code == 201
    assert response.json()["user"]["username"] == "alice"


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
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]

    me_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["user"]["username"] == "alice"


def test_wrong_password_cannot_login(client):
    assert register(client).status_code == 201

    response = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "用户名或密码错误"


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
    assert response.json()["detail"] == "请先登录"
