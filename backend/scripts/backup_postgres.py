from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.db.database import BACKEND_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用 pg_dump 创建 PostgreSQL 自定义格式备份")
    parser.add_argument("--backup-dir", type=Path, default=BACKEND_DIR / "backups")
    return parser.parse_args()


def require_pg_environment() -> None:
    missing = [
        name
        for name in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE")
        if not os.getenv(name, "").strip()
    ]
    if missing:
        raise SystemExit("缺少 PostgreSQL 环境变量：" + ", ".join(missing))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    require_pg_environment()
    backup_dir = args.backup_dir.resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"postgres-{timestamp}.dump"
    if target.exists():
        raise SystemExit("备份文件已存在，拒绝覆盖")
    subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--file", str(target)],
        check=True,
        env=os.environ.copy(),
    )
    subprocess.run(["pg_restore", "--list", str(target)], check=True)
    checksum = sha256_file(target)
    checksum_path = target.with_suffix(target.suffix + ".sha256")
    checksum_path.write_text(f"{checksum}  {target.name}\n", encoding="ascii")
    print(f"backup={target.name}")
    print(f"sha256={checksum}")


if __name__ == "__main__":
    main()
