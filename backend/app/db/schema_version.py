"""Alembic Schema 版本就绪检查。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError
from sqlalchemy.engine import Engine


BACKEND_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SchemaStatus:
    ready: bool
    state: str
    current: str | None
    head: str


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        config.attributes["database_url"] = database_url
    return config


def get_schema_status(engine: Engine) -> SchemaStatus:
    script = ScriptDirectory.from_config(alembic_config())
    head = script.get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    if current == head:
        return SchemaStatus(True, "current", current, head)
    if current is None:
        return SchemaStatus(False, "unversioned", None, head)
    try:
        script.get_revision(current)
    except ResolutionError:
        return SchemaStatus(False, "unknown_revision", current, head)
    return SchemaStatus(False, "outdated", current, head)


def require_current_schema(engine: Engine) -> None:
    status = get_schema_status(engine)
    if status.ready:
        return
    if status.state == "unversioned":
        raise RuntimeError(
            "数据库尚未由 Alembic 管理。新数据库请运行 alembic upgrade head；"
            "现有数据库请先运行 python -m scripts.adopt_existing_database。"
        )
    if status.state == "outdated":
        raise RuntimeError("数据库 Schema 版本落后，请运行 alembic upgrade head。")
    raise RuntimeError("数据库 Schema revision 高于或不属于当前代码，已拒绝启动。")
