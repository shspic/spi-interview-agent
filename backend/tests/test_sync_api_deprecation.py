from datetime import datetime

from fastapi import Response

from app.api.deprecation import enforce_sync_long_task_policy
from app.core.config import settings
from app.core.security import hash_password
from app.db.models import User
from auth_test_utils import session_headers


def test_old_sync_long_task_returns_controlled_410_with_replacement(
    client,
    db_session,
    monkeypatch,
):
    user = User(username="deprecated_api", password_hash=hash_password("test-password-123"), is_active=True, is_admin=False, created_at=datetime.now().isoformat(timespec="seconds"), last_login_at=None)
    db_session.add(user)
    db_session.commit()
    monkeypatch.setattr(settings, "enable_sync_long_task_compat", False)

    response = client.post(
        "/api/agent/ask",
        headers=session_headers(db_session, user),
        json={"question": "只用于验证迁移响应", "mode": "local"},
    )

    assert response.status_code == 410
    assert response.json()["detail"]["replacement"] == "/api/tasks/agent-ask"
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Cache-Control"] == "no-store"


def test_test_compatibility_mode_adds_deprecation_headers(monkeypatch):
    monkeypatch.setattr(settings, "enable_sync_long_task_compat", True)
    response = Response()

    enforce_sync_long_task_policy(response, "/api/tasks/interview-start")

    assert response.headers["Deprecation"] == "true"
    assert "successor-version" in response.headers["Link"]
