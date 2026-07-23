from pathlib import Path

from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.db.models import Base
from app.db.schema_adoption import backup_sqlite_database, compare_schema
from app.db.schema_version import alembic_config, get_schema_status


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_baseline_upgrade_downgrade_and_reupgrade(tmp_path):
    database_path = tmp_path / "fresh.db"
    url = sqlite_url(database_path)
    config = alembic_config(url)

    command.upgrade(config, "20260720_0002")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(username, password_hash, is_active, is_admin, created_at) "
                "VALUES ('existing-user', 'unused', 1, 0, '2026-07-22T00:00:00')"
            )
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert len(tables - {"alembic_version"}) == 26
        assert {
            "auth_sessions",
            "auth_security_events",
            "rate_limit_buckets",
            "upload_reservations",
            "background_jobs",
            "background_job_events",
            "background_job_artifacts",
            "worker_heartbeats",
            "maintenance_states",
        } <= tables
        with engine.connect() as connection:
            existing_user = connection.execute(
                text(
                    "SELECT is_quota_exempt, must_change_password, "
                    "temporary_password_expires_at FROM users "
                    "WHERE username = 'existing-user'"
                )
            ).one()
            assert existing_user.is_quota_exempt in (False, 0)
            assert existing_user.must_change_password in (False, 0)
            assert existing_user.temporary_password_expires_at is None
            indexes = {
                item["name"]
                for item in inspect(engine).get_indexes("password_reset_requests")
            }
            assert "ux_password_reset_requests_pending_user" in indexes
        assert compare_schema(engine, Base.metadata) == []
        assert get_schema_status(engine).ready is True
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        assert get_schema_status(engine).ready is True
    finally:
        engine.dispose()


def test_schema_comparison_rejects_missing_column_and_index(tmp_path):
    database_path = tmp_path / "mismatch.db"
    url = sqlite_url(database_path)
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_auth_sessions_expires_at"))
        issues = compare_schema(engine, Base.metadata)
        assert "auth_sessions 索引不匹配：ix_auth_sessions_expires_at" in issues
    finally:
        engine.dispose()


def test_sqlite_backup_is_readable_and_preserves_fixture_data(tmp_path):
    database_path = tmp_path / "source.db"
    connection = create_engine(sqlite_url(database_path))
    try:
        with connection.begin() as transaction:
            transaction.execute(text("CREATE TABLE fixture (id INTEGER PRIMARY KEY, value TEXT)"))
            transaction.execute(text("INSERT INTO fixture (value) VALUES ('fictional')"))
    finally:
        connection.dispose()

    backup = backup_sqlite_database(database_path, tmp_path / "backups")
    backup_engine = create_engine(sqlite_url(backup))
    try:
        with backup_engine.connect() as transaction:
            assert transaction.execute(text("SELECT COUNT(*) FROM fixture")).scalar_one() == 1
    finally:
        backup_engine.dispose()
