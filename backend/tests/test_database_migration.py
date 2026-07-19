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
        connection.execute(
            text(
                "CREATE TABLE interview_sessions ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
                "title TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL, "
                "planned_main_questions INTEGER NOT NULL, "
                "current_main_question INTEGER NOT NULL, "
                "selected_project_file_ids JSON NOT NULL, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO interview_sessions VALUES "
                "(1, 1, 'existing session', 'quick', 'draft', 3, 0, "
                "'[]', '2026-07-18T00:00:00', '2026-07-18T00:00:00')"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX ix_interview_sessions_user_status "
                "ON interview_sessions (user_id, status)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE interview_turns ("
                "id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, "
                "user_id INTEGER NOT NULL, sequence_number INTEGER NOT NULL, "
                "main_question_number INTEGER NOT NULL, "
                "follow_up_number INTEGER NOT NULL, parent_turn_id INTEGER, "
                "question TEXT NOT NULL, question_type TEXT NOT NULL, "
                "user_answer TEXT, technical_accuracy_score INTEGER, "
                "evidence_consistency_score INTEGER, answer_depth_score INTEGER, "
                "expression_structure_score INTEGER, job_match_score INTEGER, "
                "total_score INTEGER, evaluation_summary TEXT, problems JSON, "
                "optimized_answer TEXT, modification_reason TEXT, "
                "has_evidence_conflict BOOLEAN NOT NULL, "
                "evidence_conflicts JSON, evidence_sources JSON, answered_at TEXT, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE agent_runs ("
                "id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, "
                "session_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
                "agent_name TEXT NOT NULL CHECK (agent_name IN "
                "('supervisor', 'evidence', 'interviewer')), "
                "prompt_version TEXT NOT NULL, status TEXT NOT NULL, "
                "latency_ms INTEGER NOT NULL, error TEXT, created_at TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO agent_runs VALUES "
                "(1, 'existing-run', 1, 1, 'supervisor', 'v1', "
                "'success', 10, NULL, '2026-07-18T00:00:00')"
            )
        )

    monkeypatch.setattr(database, "engine", legacy_engine)
    database.init_db()

    inspector = inspect(legacy_engine)
    assert {
        "interview_sessions",
        "interview_turns",
        "improvement_tasks",
        "agent_runs",
        "resume_project_descriptions",
        "usage_events",
        "daily_usage_counters",
        "registration_settings",
        "admin_audit_logs",
        "user_data_deletion_logs",
        "rate_limit_buckets",
        "upload_reservations",
    }.issubset(set(inspector.get_table_names()))
    session_columns = {
        column["name"] for column in inspector.get_columns("interview_sessions")
    }
    assert "interview_plan" in session_columns
    assert "agent_execution_summary" in session_columns
    assert {
        "improvement_status",
        "improvement_summary",
        "next_round_strategy",
        "improvement_generated_at",
        "improvement_error",
    }.issubset(session_columns)
    turn_columns = {
        column["name"] for column in inspector.get_columns("interview_turns")
    }
    assert {
        "evaluation_source_ids",
        "unsupported_claims",
        "strengths",
    }.issubset(turn_columns)
    session_indexes = {
        index["name"] for index in inspector.get_indexes("interview_sessions")
    }
    task_indexes = {
        index["name"] for index in inspector.get_indexes("improvement_tasks")
    }
    task_columns = {
        column["name"] for column in inspector.get_columns("improvement_tasks")
    }
    assert "ix_interview_sessions_user_status" in session_indexes
    assert "ix_improvement_tasks_user_status" in task_indexes
    assert "ux_improvement_tasks_session_dedupe" in task_indexes
    assert {"completion_criteria", "dedupe_key"}.issubset(task_columns)
    file_columns = {
        column["name"] for column in inspector.get_columns("files")
    }
    assert {
        "size_bytes",
        "content_sha256",
        "upload_idempotency_key_hash",
    }.issubset(file_columns)
    agent_run_columns = {
        column["name"] for column in inspector.get_columns("agent_runs")
    }
    assert "request_id" in agent_run_columns
    description_foreign_keys = inspector.get_foreign_keys(
        "resume_project_descriptions"
    )
    session_foreign_key = next(
        item
        for item in description_foreign_keys
        if item["referred_table"] == "interview_sessions"
    )
    assert session_foreign_key["options"]["ondelete"] == "SET NULL"

    with legacy_engine.connect() as connection:
        existing_user = connection.execute(
            text(
                "SELECT username, password_hash FROM users "
                "WHERE id = 1"
            )
        ).one()
        existing_session = connection.execute(
            text("SELECT title, status FROM interview_sessions WHERE id = 1")
        ).one()
        existing_run = connection.execute(
            text("SELECT run_id, agent_name FROM agent_runs WHERE id = 1")
        ).one()
        connection.execute(
            text(
                "INSERT INTO agent_runs "
                "(id, run_id, session_id, user_id, agent_name, prompt_version, "
                "status, latency_ms, error, created_at) VALUES "
                "(2, 'evaluation-run', 1, 1, 'evaluation', 'v2', "
                "'success', 12, NULL, '2026-07-18T00:00:01')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO agent_runs "
                "(id, run_id, session_id, user_id, agent_name, prompt_version, "
                "status, latency_ms, error, created_at) VALUES "
                "(3, 'improvement-run', 1, 1, 'improvement', 'v3', "
                "'success', 13, NULL, '2026-07-18T00:00:02')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO agent_runs "
                "(id, run_id, session_id, user_id, agent_name, prompt_version, "
                "status, latency_ms, error, created_at) VALUES "
                "(4, 'resume-run', 1, 1, 'resume', 'v4', "
                "'success', 14, NULL, '2026-07-18T00:00:03')"
            )
        )

    assert existing_user.username == "existing-user"
    assert existing_user.password_hash == "existing-hash"
    assert existing_session.title == "existing session"
    assert existing_session.status == "draft"
    assert existing_run.run_id == "existing-run"
    assert existing_run.agent_name == "supervisor"
