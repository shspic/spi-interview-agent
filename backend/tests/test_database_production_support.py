from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.db.database import BACKEND_DIR, build_database_url, sanitized_database_url


def test_database_url_prefers_explicit_value_and_hides_password():
    config = SimpleNamespace(
        database_url="postgresql+psycopg://test_user:secret@db/test_database",
        sqlite_db_path="ignored.db",
        app_environment="development",
    )
    assert build_database_url(config) == config.database_url
    sanitized = sanitized_database_url(config.database_url)
    assert "secret" not in sanitized
    assert "***" in sanitized


def test_database_url_falls_back_to_existing_sqlite_path():
    config = SimpleNamespace(
        database_url="",
        sqlite_db_path="data/test-fallback.db",
        app_environment="development",
    )
    assert build_database_url(config) == (
        f"sqlite:///{(BACKEND_DIR / 'data/test-fallback.db').resolve().as_posix()}"
    )


def test_production_requires_explicit_psycopg_database_url():
    base = {
        "app_environment": "production",
        "jwt_secret_key": "valid-jwt",
        "auth_csrf_secret": "valid-csrf",
        "auth_cookie_secure": True,
    }
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(**base, database_url="")
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings(**base, database_url="sqlite:///production.db")
    configured = Settings(
        **base,
        database_url="postgresql+psycopg://app:secret@db/app_production",
    )
    assert configured.database_url.startswith("postgresql+psycopg://")


def test_invalid_database_driver_is_rejected():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(database_url="mysql+pymysql://user:pass@db/test")
