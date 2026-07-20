"""安全准备本地数据库：新库升级，旧库先要求核验接管。"""

from alembic import command
from sqlalchemy import inspect

from app.db.database import SQLALCHEMY_DATABASE_URL, engine
from app.db.schema_version import alembic_config, get_schema_status


def main() -> None:
    status = get_schema_status(engine)
    existing_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    if status.state == "unversioned" and existing_tables:
        raise SystemExit(
            "检测到未接管的现有数据库。请先运行："
            "python -m scripts.adopt_existing_database"
        )
    if status.state == "unknown_revision":
        raise SystemExit("数据库 revision 不属于当前代码，已拒绝自动迁移。")
    command.upgrade(alembic_config(SQLALCHEMY_DATABASE_URL), "head")
    if not get_schema_status(engine).ready:
        raise SystemExit("数据库升级后仍未达到 head。")
    print("数据库 Schema 已就绪。")


if __name__ == "__main__":
    main()
