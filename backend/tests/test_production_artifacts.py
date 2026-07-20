from pathlib import Path

from scripts.restore_postgres import SAFE_DATABASE

ROOT = Path(__file__).resolve().parents[2]


def test_docker_context_excludes_runtime_and_secret_data():
    content = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for expected in (
        "**/.env",
        "**/.env.*",
        "backend/data",
        "backend/backups",
        "backend/evals/results",
        "frontend/dist",
        "**/*.db",
        "**/*.dump",
    ):
        assert expected in content


def test_compose_has_migration_dependencies_and_persistent_volumes():
    content = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "condition: service_completed_successfully" in content
    assert "postgres_data:" in content
    assert "uploads:" in content
    assert "chroma:" in content
    assert "backups:" in content
    assert "python\", \"-m\", \"app.worker" in content
    assert "redis" not in content.lower()
    assert "celery" not in content.lower()


def test_images_do_not_copy_runtime_data_or_secrets():
    backend = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "USER app" in backend
    assert "--no-server-header" in backend
    assert "backend/ /app/" in backend
    assert "COPY frontend/ ./" in frontend
    assert "VITE_API_BASE_URL" not in frontend
    assert ".env" not in backend


def test_production_proxy_and_override_enforce_same_site_security():
    proxy = (ROOT / "deploy" / "nginx-https.conf.template").read_text(
        encoding="utf-8"
    )
    frontend_proxy = (ROOT / "frontend" / "nginx.conf").read_text(
        encoding="utf-8"
    )
    override = (
        ROOT / "deploy" / "docker-compose.production.yml"
    ).read_text(encoding="utf-8")
    assert "return 308 https://" in proxy
    assert "server_tokens off" in proxy
    assert "client_max_body_size 25m" in proxy
    assert "X-Forwarded-Proto https" in proxy
    assert "websocket" not in proxy.lower()
    assert 'Cache-Control "no-store"' in frontend_proxy
    assert "try_files $uri $uri/ /index.html" in frontend_proxy
    assert "APP_ENVIRONMENT: production" in override
    assert 'AUTH_COOKIE_SECURE: "true"' in override
    assert "ENABLE_SYNC_LONG_TASK_COMPAT" in override


def test_restore_target_database_name_requires_test_or_restore_marker():
    assert SAFE_DATABASE.fullmatch("spi_restore_test")
    assert not any(marker in "production" for marker in ("test", "restore"))
