from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

db_path = Path(settings.sqlite_db_path)

if not db_path.is_absolute():
    backend_dir = Path(__file__).resolve().parents[2]
    db_path = backend_dir / db_path

db_path.parent.mkdir(parents=True, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{db_path.as_posix()}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def init_db():
    from app.db import models

    Base.metadata.create_all(bind=engine)
    ensure_history_records_columns()
    ensure_user_scope_columns()
    ensure_file_category_column()
    ensure_target_job_active_index()
    ensure_interview_session_agent_columns()
    ensure_interview_turn_evaluation_columns()
    ensure_interview_improvement_columns()
    ensure_agent_run_supports_improvement()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_history_records_columns():
    inspector = inspect(engine)
    columns = inspector.get_columns("history_records")
    column_names = {column["name"] for column in columns}

    with engine.begin() as connection:
        if "route_reason" not in column_names:
            connection.execute(
                text("ALTER TABLE history_records ADD COLUMN route_reason TEXT DEFAULT ''")
            )

        if "execution_steps" not in column_names:
            connection.execute(
                text("ALTER TABLE history_records ADD COLUMN execution_steps TEXT DEFAULT ''")
            )


def ensure_user_scope_columns():
    inspector = inspect(engine)
    table_indexes = {
        "files": "ix_files_user_id",
        "history_records": "ix_history_records_user_id",
        "interview_records": "ix_interview_records_user_id",
    }

    with engine.begin() as connection:
        for table_name, index_name in table_indexes.items():
            columns = inspector.get_columns(table_name)
            column_names = {column["name"] for column in columns}

            if "user_id" not in column_names:
                connection.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        "ADD COLUMN user_id INTEGER REFERENCES users(id)"
                    )
                )

            connection.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON {table_name} (user_id)"
                )
            )


def ensure_file_category_column():
    inspector = inspect(engine)
    columns = inspector.get_columns("files")
    column_names = {column["name"] for column in columns}

    if "category" in column_names:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE files ADD COLUMN category TEXT "
                "NOT NULL DEFAULT 'other'"
            )
        )


def ensure_target_job_active_index():
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_target_jobs_active_user "
                "ON target_jobs (user_id) WHERE is_active = 1"
            )
        )


def ensure_interview_session_agent_columns():
    inspector = inspect(engine)
    columns = inspector.get_columns("interview_sessions")
    column_names = {column["name"] for column in columns}

    with engine.begin() as connection:
        if "interview_plan" not in column_names:
            connection.execute(
                text("ALTER TABLE interview_sessions ADD COLUMN interview_plan JSON")
            )
        if "agent_execution_summary" not in column_names:
            connection.execute(
                text(
                    "ALTER TABLE interview_sessions "
                    "ADD COLUMN agent_execution_summary JSON"
                )
            )


def ensure_interview_turn_evaluation_columns():
    inspector = inspect(engine)
    columns = inspector.get_columns("interview_turns")
    column_names = {column["name"] for column in columns}
    new_columns = {
        "evaluation_source_ids": "JSON",
        "unsupported_claims": "JSON",
        "strengths": "JSON",
    }

    with engine.begin() as connection:
        for column_name, column_type in new_columns.items():
            if column_name not in column_names:
                connection.execute(
                    text(
                        f"ALTER TABLE interview_turns "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )


def ensure_interview_improvement_columns():
    inspector = inspect(engine)
    session_columns = {
        column["name"] for column in inspector.get_columns("interview_sessions")
    }
    task_columns = {
        column["name"] for column in inspector.get_columns("improvement_tasks")
    }

    session_new_columns = {
        "improvement_status": "TEXT NOT NULL DEFAULT 'pending'",
        "improvement_summary": "TEXT",
        "next_round_strategy": "TEXT",
        "improvement_generated_at": "TEXT",
        "improvement_error": "TEXT",
    }
    task_new_columns = {
        "completion_criteria": "TEXT NOT NULL DEFAULT ''",
        "dedupe_key": "TEXT",
    }

    with engine.begin() as connection:
        for column_name, column_type in session_new_columns.items():
            if column_name not in session_columns:
                connection.execute(
                    text(
                        "ALTER TABLE interview_sessions "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )
        for column_name, column_type in task_new_columns.items():
            if column_name not in task_columns:
                connection.execute(
                    text(
                        "ALTER TABLE improvement_tasks "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_interview_sessions_improvement_status "
                "ON interview_sessions (improvement_status)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ux_improvement_tasks_session_dedupe "
                "ON improvement_tasks (session_id, dedupe_key) "
                "WHERE dedupe_key IS NOT NULL"
            )
        )


def ensure_agent_run_supports_improvement():
    with engine.connect() as connection:
        table_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'agent_runs'"
            )
        ).scalar_one_or_none()

    if table_sql is None or "'improvement'" in table_sql:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE agent_runs_new ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "run_id TEXT NOT NULL, "
                "session_id INTEGER NOT NULL REFERENCES interview_sessions(id) "
                "ON DELETE CASCADE, "
                "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "agent_name TEXT NOT NULL CHECK (agent_name IN "
                "('supervisor', 'evidence', 'evaluation', 'interviewer', "
                "'improvement')), "
                "prompt_version TEXT NOT NULL, "
                "status TEXT NOT NULL CHECK (status IN ('success', 'error')), "
                "latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0), "
                "error TEXT, created_at TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO agent_runs_new "
                "(id, run_id, session_id, user_id, agent_name, prompt_version, "
                "status, latency_ms, error, created_at) "
                "SELECT id, run_id, session_id, user_id, agent_name, "
                "prompt_version, status, latency_ms, error, created_at "
                "FROM agent_runs"
            )
        )
        connection.execute(text("DROP TABLE agent_runs"))
        connection.execute(text("ALTER TABLE agent_runs_new RENAME TO agent_runs"))
        for index_sql in (
            "CREATE INDEX ix_agent_runs_id ON agent_runs (id)",
            "CREATE INDEX ix_agent_runs_session_id ON agent_runs (session_id)",
            "CREATE INDEX ix_agent_runs_user_id ON agent_runs (user_id)",
            "CREATE INDEX ix_agent_runs_agent_name ON agent_runs (agent_name)",
            "CREATE INDEX ix_agent_runs_status ON agent_runs (status)",
            "CREATE INDEX ix_agent_runs_created_at ON agent_runs (created_at)",
            "CREATE INDEX ix_agent_runs_session_created "
            "ON agent_runs (session_id, created_at)",
            "CREATE INDEX ix_agent_runs_user_created "
            "ON agent_runs (user_id, created_at)",
            "CREATE INDEX ix_agent_runs_run_id ON agent_runs (run_id)",
        ):
            connection.execute(text(index_sql))
