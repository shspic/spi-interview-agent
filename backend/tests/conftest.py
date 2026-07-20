import os

os.environ["SKIP_DOTENV"] = "1"
os.environ["APP_ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-with-sufficient-length"
os.environ["AUTH_CSRF_SECRET"] = "test-csrf-secret-with-sufficient-length"
os.environ["REGISTRATION_INVITE_CODE"] = "test-invite-code"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import Base, get_db
from app.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    testing_session = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def client(db_session, monkeypatch):
    monkeypatch.setattr(settings, "registration_invite_code", "test-invite-code")
    monkeypatch.setattr(
        settings,
        "jwt_secret_key",
        "test-jwt-secret-key-with-sufficient-length",
    )
    monkeypatch.setattr(settings, "jwt_expire_minutes", 120)
    monkeypatch.setattr(settings, "auth_csrf_secret", "test-csrf-secret-with-sufficient-length")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "enable_sync_long_task_compat", True)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    test_client.get("/api/auth/csrf")

    def add_csrf_header(request):
        csrf_token = test_client.cookies.get(settings.auth_csrf_cookie_name)
        if (
            csrf_token
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and "X-CSRF-Token" not in request.headers
        ):
            request.headers["X-CSRF-Token"] = csrf_token

    test_client.event_hooks["request"].append(add_csrf_header)

    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()
