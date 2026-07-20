"""现有 SQLite 数据库与 Alembic 基线的结构核验和备份。"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import UniqueConstraint, inspect
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.schema import CheckConstraint, MetaData


KNOWN_LEGACY_ISSUES = {
    "files 外键定义不匹配",
    "files 检查约束不匹配：ck_files_size_bytes",
    "history_records 外键定义不匹配",
    "interview_records 外键定义不匹配",
}
CONSTRAINT_NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _normalized_sql(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().strip("() ")).lower()


def _type_affinity(value: object) -> str:
    affinity = getattr(value, "_type_affinity", type(value))
    return getattr(affinity, "__name__", str(affinity)).lower()


def compare_schema(engine: Engine, metadata: MetaData) -> list[str]:
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names()) - {"alembic_version"}
    expected_tables = set(metadata.tables)
    issues = [f"缺少表：{name}" for name in sorted(expected_tables - actual_tables)]
    issues.extend(f"存在非基线表：{name}" for name in sorted(actual_tables - expected_tables))

    for table_name in sorted(expected_tables & actual_tables):
        table = metadata.tables[table_name]
        actual_columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        expected_columns = {column.name: column for column in table.columns}
        for name in sorted(set(expected_columns) - set(actual_columns)):
            issues.append(f"{table_name} 缺少列：{name}")
        for name in sorted(set(actual_columns) - set(expected_columns)):
            issues.append(f"{table_name} 存在非基线列：{name}")
        for name in sorted(set(expected_columns) & set(actual_columns)):
            expected = expected_columns[name]
            actual = actual_columns[name]
            if _type_affinity(expected.type) != _type_affinity(actual["type"]):
                issues.append(f"{table_name}.{name} 字段类型不匹配")
            if not expected.primary_key and bool(expected.nullable) != bool(actual["nullable"]):
                issues.append(f"{table_name}.{name} nullable 不匹配")
            if expected.server_default is not None:
                expected_default = _normalized_sql(expected.server_default.arg)
                actual_default = _normalized_sql(actual.get("default")).strip("'\"")
                if expected_default != actual_default:
                    issues.append(f"{table_name}.{name} 默认值不匹配")

        expected_unique = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        expected_unique.update(
            tuple(column.name for column in index.columns)
            for index in table.indexes
            if index.unique
        )
        actual_unique = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(table_name)
        }
        actual_unique.update(
            tuple(item["column_names"])
            for item in inspector.get_indexes(table_name)
            if item.get("unique")
        )
        for columns in sorted(expected_unique - actual_unique):
            issues.append(f"{table_name} 缺少唯一约束：{','.join(columns)}")

        actual_indexes = {
            item["name"]: (tuple(item["column_names"]), bool(item.get("unique")))
            for item in inspector.get_indexes(table_name)
        }
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            expected_index = (
                tuple(column.name for column in index.columns),
                bool(index.unique),
            )
            if actual_indexes.get(index.name) != expected_index:
                issues.append(f"{table_name} 索引不匹配：{index.name}")

        expected_foreign_keys = {
            (
                tuple(element.parent.name for element in constraint.elements),
                constraint.referred_table.name,
                tuple(element.column.name for element in constraint.elements),
                (constraint.ondelete or "").upper(),
            )
            for constraint in table.foreign_key_constraints
        }
        actual_foreign_keys = {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
                str(item.get("options", {}).get("ondelete", "")).upper(),
            )
            for item in inspector.get_foreign_keys(table_name)
        }
        if expected_foreign_keys != actual_foreign_keys:
            issues.append(f"{table_name} 外键定义不匹配")

        expected_checks = {
            constraint.name: _normalized_sql(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint) and constraint.name
        }
        actual_checks = {
            item.get("name"): _normalized_sql(item.get("sqltext"))
            for item in inspector.get_check_constraints(table_name)
            if item.get("name")
        }
        for name, sqltext in expected_checks.items():
            if actual_checks.get(name) != sqltext:
                issues.append(f"{table_name} 检查约束不匹配：{name}")
    return issues


def sqlite_database_path(database_url: str) -> Path:
    parsed = make_url(database_url)
    if parsed.drivername != "sqlite" or not parsed.database or parsed.database == ":memory:":
        raise ValueError("当前辅助工具只支持文件型 SQLite 数据库")
    return Path(parsed.database).resolve()


def backup_sqlite_database(database_path: Path, backup_dir: Path) -> Path:
    if not database_path.is_file():
        raise FileNotFoundError("SQLite 数据库文件不存在")
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"{database_path.stem}-{timestamp}.sqlite3"
    source = sqlite3.connect(database_path)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError("SQLite 备份完整性检查失败")
    except Exception:
        destination.close()
        source.close()
        if backup_path.exists():
            backup_path.unlink()
        raise
    else:
        destination.close()
        source.close()
    return backup_path


def repair_known_legacy_schema(engine: Engine) -> None:
    """只修复已核验的三个旧外键和文件大小检查约束。"""
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        with operations.batch_alter_table(
            "files",
            recreate="always",
            naming_convention=CONSTRAINT_NAMING,
        ) as batch:
            batch.drop_constraint("fk_files_user_id_users", type_="foreignkey")
            batch.create_foreign_key(
                "fk_files_user_id_users",
                "users",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch.create_check_constraint("ck_files_size_bytes", "size_bytes >= 0")
        for table_name in ("history_records", "interview_records"):
            constraint_name = f"fk_{table_name}_user_id_users"
            with operations.batch_alter_table(
                table_name,
                recreate="always",
                naming_convention=CONSTRAINT_NAMING,
            ) as batch:
                batch.drop_constraint(constraint_name, type_="foreignkey")
                batch.create_foreign_key(
                    constraint_name,
                    "users",
                    ["user_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
