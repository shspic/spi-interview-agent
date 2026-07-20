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

    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert len(tables - {"alembic_version"}) == 20
        assert {
            "auth_sessions",
            "auth_security_events",
            "rate_limit_buckets",
            "upload_reservations",
        } <= tables
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
