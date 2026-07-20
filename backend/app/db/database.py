from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def build_database_url(config=settings) -> str:
    configured_url = config.database_url.strip()
    if configured_url:
        parsed_url = make_url(configured_url)
        if parsed_url.drivername not in {"sqlite", "postgresql+psycopg"}:
            raise ValueError("不支持的 DATABASE_URL 数据库驱动")
        if configured_url.startswith("sqlite:///./"):
            relative_path = unquote(configured_url.removeprefix("sqlite:///"))
            absolute_path = (BACKEND_DIR / relative_path).resolve()
            return f"sqlite:///{absolute_path.as_posix()}"
        return configured_url

    if config.app_environment == "production":
        raise ValueError("生产环境不得回退到 SQLite，请显式配置 DATABASE_URL")

    configured_path = Path(config.sqlite_db_path)
    if not configured_path.is_absolute():
        configured_path = BACKEND_DIR / configured_path
    return f"sqlite:///{configured_path.resolve().as_posix()}"


SQLALCHEMY_DATABASE_URL = build_database_url()
DATABASE_DIALECT = make_url(SQLALCHEMY_DATABASE_URL).get_backend_name()


def sanitized_database_url(database_url: str = SQLALCHEMY_DATABASE_URL) -> str:
    """仅供诊断使用，始终隐藏凭据。"""
    return make_url(database_url).render_as_string(hide_password=True)


def _prepare_sqlite_directory(database_url: str) -> None:
    parsed = urlsplit(database_url)
    if parsed.scheme != "sqlite" or database_url in {"sqlite://", "sqlite:///:memory:"}:
        return
    path = Path(unquote(parsed.path.lstrip("/")))
    if database_url.startswith("sqlite:////"):
        path = Path("/") / path
    if path.drive or path.is_absolute():
        path.parent.mkdir(parents=True, exist_ok=True)

_prepare_sqlite_directory(SQLALCHEMY_DATABASE_URL)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=(
        {"check_same_thread": False}
        if SQLALCHEMY_DATABASE_URL.startswith("sqlite")
        else {}
    ),
    pool_pre_ping=DATABASE_DIALECT == "postgresql",
)


if DATABASE_DIALECT == "sqlite":
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
    """仅供显式旧库兼容和隔离测试使用，不得作为正常启动路径。"""
    from app.db import models

    Base.metadata.create_all(bind=engine)
    ensure_history_records_columns()
    ensure_user_scope_columns()
    ensure_file_category_column()
    ensure_file_security_columns()
    ensure_target_job_active_index()
    ensure_interview_session_agent_columns()
    ensure_interview_turn_evaluation_columns()
    ensure_interview_improvement_columns()
    ensure_agent_run_supports_resume()
    ensure_agent_run_request_id()


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


def ensure_file_security_columns():
    inspector = inspect(engine)
    columns = inspector.get_columns("files")
    column_names = {column["name"] for column in columns}

    with engine.begin() as connection:
        if "size_bytes" not in column_names:
            connection.execute(
                text(
                    "ALTER TABLE files ADD COLUMN size_bytes INTEGER "
                    "NOT NULL DEFAULT 0"
                )
            )
        if "content_sha256" not in column_names:
            connection.execute(
                text("ALTER TABLE files ADD COLUMN content_sha256 TEXT")
            )
        if "upload_idempotency_key_hash" not in column_names:
            connection.execute(
                text(
                    "ALTER TABLE files ADD COLUMN "
                    "upload_idempotency_key_hash TEXT"
                )
            )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ux_files_user_upload_idempotency "
                "ON files (user_id, upload_idempotency_key_hash) "
                "WHERE upload_idempotency_key_hash IS NOT NULL"
            )
        )

    _backfill_legacy_file_sizes()


def _backfill_legacy_file_sizes():
    upload_root = Path(settings.upload_dir)
    if not upload_root.is_absolute():
        upload_root = Path(__file__).resolve().parents[2] / upload_root
    upload_root = upload_root.resolve()

    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT id, user_id, file_path FROM files "
                "WHERE size_bytes = 0 AND user_id IS NOT NULL"
            )
        ).mappings()
        for row in rows:
            candidate = Path(row["file_path"])
            try:
                resolved = candidate.resolve()
                expected_root = (upload_root / str(row["user_id"])).resolve()
                if not resolved.is_relative_to(expected_root) or not resolved.is_file():
                    continue
                size_bytes = resolved.stat().st_size
            except OSError:
                continue
            connection.execute(
                text("UPDATE files SET size_bytes = :size_bytes WHERE id = :id"),
                {"size_bytes": size_bytes, "id": row["id"]},
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


def ensure_agent_run_supports_resume():
    with engine.connect() as connection:
        table_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'agent_runs'"
            )
        ).scalar_one_or_none()

    if table_sql is None or "'resume'" in table_sql:
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
                "'improvement', 'resume')), "
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


def ensure_agent_run_request_id():
    inspector = inspect(engine)
    columns = inspector.get_columns("agent_runs")
    column_names = {column["name"] for column in columns}
    with engine.begin() as connection:
        if "request_id" not in column_names:
            connection.execute(
                text("ALTER TABLE agent_runs ADD COLUMN request_id TEXT")
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_agent_runs_request_id "
                "ON agent_runs (request_id)"
            )
        )
