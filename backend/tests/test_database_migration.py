from sqlalchemy import create_engine, inspect, text

from app.db import database


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
