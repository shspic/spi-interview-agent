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
