"""为当前 SQLite 数据库创建一致性备份。"""

from app.db.database import BACKEND_DIR, SQLALCHEMY_DATABASE_URL
from app.db.schema_adoption import backup_sqlite_database, sqlite_database_path


def main() -> None:
    source = sqlite_database_path(SQLALCHEMY_DATABASE_URL)
    backup = backup_sqlite_database(source, BACKEND_DIR / "backups")
    print(f"备份完成：{backup.name}")


if __name__ == "__main__":
    main()
