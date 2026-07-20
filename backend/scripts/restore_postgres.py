from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

from scripts.backup_postgres import require_pg_environment, sha256_file

SAFE_DATABASE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将备份恢复到全新的测试数据库")
    parser.add_argument("backup", type=Path)
    parser.add_argument("--target-database", required=True)
    parser.add_argument("--confirm", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_pg_environment()
    target = args.target_database.strip().lower()
    if not SAFE_DATABASE.fullmatch(target) or not any(
        marker in target for marker in ("test", "restore")
    ):
        raise SystemExit("目标数据库名必须安全且包含 test 或 restore")
    if args.confirm != "RESTORE_TO_NEW_DATABASE":
        raise SystemExit("恢复需要 --confirm RESTORE_TO_NEW_DATABASE")
    backup = args.backup.resolve()
    if not backup.is_file():
        raise SystemExit("备份文件不存在")
    checksum_path = backup.with_suffix(backup.suffix + ".sha256")
    if checksum_path.is_file():
        expected = checksum_path.read_text(encoding="ascii").split()[0]
        if sha256_file(backup) != expected:
            raise SystemExit("备份校验和不匹配")
    environment = os.environ.copy()
    subprocess.run(["createdb", target], check=True, env=environment)
    subprocess.run(
        ["pg_restore", "--no-owner", "--exit-on-error", "--dbname", target, str(backup)],
        check=True,
        env=environment,
    )
    subprocess.run(
        ["psql", "--dbname", target, "--command", "SELECT version_num FROM alembic_version;"],
        check=True,
        env=environment,
    )
    print(f"restored_database={target}")


if __name__ == "__main__":
    main()
