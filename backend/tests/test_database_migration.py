from sqlalchemy import create_engine, inspect, text

from app.db import database
from app.db.models import (
    FileRecord,
    HistoryRecord,
    InterviewRecord,
    TargetJob,
    User,
    UserProfile,
)


def test_legacy_rows_are_preserved_with_null_user_id(tmp_path, monkeypatch):
    legacy_engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")

    with legacy_engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE)")
        )
        connection.execute(
            text("CREATE TABLE files (id INTEGER PRIMARY KEY, file_id TEXT)")
        )
        connection.execute(
            text(
                "CREATE TABLE history_records "
                "(id INTEGER PRIMARY KEY, record_id TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE interview_records "
                "(id INTEGER PRIMARY KEY, session_id TEXT)"
            )
        )
        connection.execute(text("INSERT INTO files VALUES (1, 'legacy-file')"))
        connection.execute(
            text("INSERT INTO history_records VALUES (1, 'legacy-history')")
        )
        connection.execute(
            text("INSERT INTO interview_records VALUES (1, 'legacy-interview')")
        )

    monkeypatch.setattr(database, "engine", legacy_engine)
    database.ensure_user_scope_columns()
    database.ensure_file_category_column()

    inspector = inspect(legacy_engine)
    for table_name in ("files", "history_records", "interview_records"):
        column_names = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        assert "user_id" in column_names

        with legacy_engine.connect() as connection:
            row = connection.execute(
                text(f"SELECT COUNT(*) AS row_count, user_id FROM {table_name}")
            ).one()

        assert row.row_count == 1
        assert row.user_id is None

    with legacy_engine.connect() as connection:
        legacy_file = connection.execute(
            text("SELECT category FROM files WHERE id = 1")
        ).one()

    assert legacy_file.category == "other"


def test_training_tables_are_added_without_changing_existing_user(
    tmp_path,
    monkeypatch,
):
    legacy_engine = create_engine(f"sqlite:///{(tmp_path / 'current.db').as_posix()}")
    existing_tables = [
        User.__table__,
        UserProfile.__table__,
        TargetJob.__table__,
        FileRecord.__table__,
        HistoryRecord.__table__,
        InterviewRecord.__table__,
    ]
    database.Base.metadata.create_all(bind=legacy_engine, tables=existing_tables)
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, username, password_hash, is_active, is_admin, created_at) "
                "VALUES (1, 'existing-user', 'existing-hash', 1, 0, "
                "'2026-07-18T00:00:00')"
            )
        )

    monkeypatch.setattr(database, "engine", legacy_engine)
    database.init_db()

    inspector = inspect(legacy_engine)
    assert {
        "interview_sessions",
        "interview_turns",
        "improvement_tasks",
    }.issubset(set(inspector.get_table_names()))
    session_indexes = {
        index["name"] for index in inspector.get_indexes("interview_sessions")
    }
    task_indexes = {
        index["name"] for index in inspector.get_indexes("improvement_tasks")
    }
    assert "ix_interview_sessions_user_status" in session_indexes
    assert "ix_improvement_tasks_user_status" in task_indexes

    with legacy_engine.connect() as connection:
        existing_user = connection.execute(
            text(
                "SELECT username, password_hash FROM users "
                "WHERE id = 1"
            )
        ).one()

    assert existing_user.username == "existing-user"
    assert existing_user.password_hash == "existing-hash"
