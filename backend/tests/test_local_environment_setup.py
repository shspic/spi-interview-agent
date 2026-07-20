import os
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.readiness import (
    auth_configuration_issues,
    auth_unavailable_message,
    validate_auth_startup,
)
from scripts import bootstrap_local_env


EXAMPLE = """APP_ENVIRONMENT=development
REGISTRATION_INVITE_CODE=change-me
JWT_SECRET_KEY=change-me
AUTH_CSRF_SECRET=change-me
RATE_LIMIT_HASH_SALT=change-me
AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=lax
CORS_ALLOWED_ORIGINS=http://localhost:5173
"""


def read_values(path: Path) -> dict[str, str]:
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }


def test_bootstrap_creates_from_example_with_distinct_secrets(tmp_path):
    example_path = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    example_path.write_text(EXAMPLE, encoding="utf-8")

    existed, names = bootstrap_local_env.bootstrap_local_env(example_path, env_path)
    values = read_values(env_path)

    assert existed is False
    assert set(names) == set(read_values(example_path))
    assert values["JWT_SECRET_KEY"] not in {"", "change-me"}
    assert values["AUTH_CSRF_SECRET"] not in {"", "change-me"}
    assert values["JWT_SECRET_KEY"] != values["AUTH_CSRF_SECRET"]
    assert values["REGISTRATION_INVITE_CODE"] != "change-me"


def test_bootstrap_only_adds_missing_values_and_is_idempotent(tmp_path):
    example_path = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    example_path.write_text(EXAMPLE, encoding="utf-8")
    env_path.write_text("JWT_SECRET_KEY=keep-jwt\nCUSTOM=value\n", encoding="utf-8")

    existed, names = bootstrap_local_env.bootstrap_local_env(example_path, env_path)
    first_content = env_path.read_text(encoding="utf-8")
    _, second_names = bootstrap_local_env.bootstrap_local_env(example_path, env_path)

    assert existed is True
    assert "JWT_SECRET_KEY" not in names
    assert read_values(env_path)["JWT_SECRET_KEY"] == "keep-jwt"
    assert read_values(env_path)["CUSTOM"] == "value"
    assert second_names == []
    assert env_path.read_text(encoding="utf-8") == first_content


def test_bootstrap_does_not_print_secret_values(tmp_path, monkeypatch, capsys):
    example_path = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    example_path.write_text(EXAMPLE, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["bootstrap", "--example-file", str(example_path), "--env-file", str(env_path)],
    )

    bootstrap_local_env.main()
    output = capsys.readouterr().out
    values = read_values(env_path)

    assert values["JWT_SECRET_KEY"] not in output
    assert values["AUTH_CSRF_SECRET"] not in output
    assert "JWT_SECRET_KEY" in output


def test_atomic_write_failure_preserves_existing_file(tmp_path, monkeypatch):
    example_path = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    example_path.write_text(EXAMPLE, encoding="utf-8")
    original = "JWT_SECRET_KEY=keep-jwt\n"
    env_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(os, "replace", lambda source, target: (_ for _ in ()).throw(OSError()))

    with pytest.raises(OSError):
        bootstrap_local_env.bootstrap_local_env(example_path, env_path)

    assert env_path.read_text(encoding="utf-8") == original


def test_bootstrap_refuses_production_configuration(tmp_path):
    example_path = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    example_path.write_text(EXAMPLE, encoding="utf-8")
    env_path.write_text("APP_ENVIRONMENT=production\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="拒绝修改生产环境"):
        bootstrap_local_env.bootstrap_local_env(example_path, env_path)


def test_bootstrap_refuses_existing_equal_auth_secrets(tmp_path):
    example_path = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    example_path.write_text(EXAMPLE, encoding="utf-8")
    env_path.write_text(
        "JWT_SECRET_KEY=same-value\nAUTH_CSRF_SECRET=same-value\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="必须不同"):
        bootstrap_local_env.bootstrap_local_env(example_path, env_path)


def test_auth_readiness_and_production_fail_fast():
    development = Settings(
        app_environment="development",
        jwt_secret_key="",
        auth_csrf_secret="",
    )
    production = Settings(
        app_environment="production",
        jwt_secret_key="valid-jwt",
        auth_csrf_secret="valid-csrf",
        auth_cookie_secure=True,
    )

    assert auth_configuration_issues(development)
    assert "python -m scripts.bootstrap_local_env" in auth_unavailable_message(development)
    validate_auth_startup(production)


def test_production_rejects_missing_jwt_secret():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            app_environment="production",
            jwt_secret_key="",
            auth_csrf_secret="valid-csrf",
            auth_cookie_secure=True,
        )
