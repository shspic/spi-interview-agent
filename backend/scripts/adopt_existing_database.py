"""核验、备份并显式接管现有 SQLite 数据库。"""

from __future__ import annotations

import argparse
from pathlib import Path

from alembic import command
from sqlalchemy import create_engine

from app.db.database import BACKEND_DIR, SQLALCHEMY_DATABASE_URL
from app.db.models import Base
from app.db.schema_adoption import (
    KNOWN_LEGACY_ISSUES,
    backup_sqlite_database,
    compare_schema,
    repair_known_legacy_schema,
    sqlite_database_path,
)
from app.db.schema_version import alembic_config, get_schema_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="核验现有 SQLite Schema；默认只读。")
    parser.add_argument("--apply", action="store_true", help="兼容时备份并 stamp")
    parser.add_argument(
        "--repair-known-legacy",
        action="store_true",
        help="仅在差异严格等于已知旧外键/检查约束时修复",
    )
    parser.add_argument("--database-url", default=SQLALCHEMY_DATABASE_URL)
    parser.add_argument("--backup-dir", type=Path, default=BACKEND_DIR / "backups")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_path = sqlite_database_path(args.database_url)
    if not database_path.is_file():
        raise SystemExit("数据库文件不存在；新数据库请运行 alembic upgrade head。")
    engine = create_engine(args.database_url, connect_args={"check_same_thread": False})
    try:
        status = get_schema_status(engine)
        if status.ready:
            print("数据库已处于 Alembic head，无需接管。")
            return
        if status.current is not None:
            raise SystemExit("数据库已有不匹配的 Alembic revision，已拒绝 stamp。")
        issues = compare_schema(engine, Base.metadata)
        known_legacy = set(issues) == KNOWN_LEGACY_ISSUES
        if issues and not (known_legacy and args.apply and args.repair_known_legacy):
            print("Schema 与基线不兼容，已拒绝 stamp：")
            for issue in issues:
                print(f"- {issue}")
            if known_legacy:
                print(
                    "这组差异可在显式确认后修复："
                    "使用 --apply --repair-known-legacy（执行前会创建备份）。"
                )
            raise SystemExit(2)
        if issues:
            backup_path = backup_sqlite_database(database_path, args.backup_dir.resolve())
            print(f"已创建 SQLite 备份：{backup_path.name}")
            repair_known_legacy_schema(engine)
            remaining_issues = compare_schema(engine, Base.metadata)
            if remaining_issues:
                print("已知差异修复后仍不兼容，未执行 stamp：")
                for issue in remaining_issues:
                    print(f"- {issue}")
                raise SystemExit(3)
            print("已知旧 Schema 差异已修复，并通过完整复检。")
        else:
            print("Schema 与 Alembic 基线完全兼容。")
        if not args.apply:
            print("当前为 dry-run，数据库未修改。使用 --apply 才会备份并 stamp。")
            return
        if not issues:
            backup_path = backup_sqlite_database(database_path, args.backup_dir.resolve())
            print(f"已创建 SQLite 备份：{backup_path.name}")
        command.stamp(alembic_config(args.database_url), "head")
        if not get_schema_status(engine).ready:
            raise SystemExit("stamp 后版本核验失败。")
        print("数据库已安全接管，当前 revision 为 head。")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
