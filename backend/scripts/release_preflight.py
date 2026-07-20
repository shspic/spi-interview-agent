"""只读发布前检查；不创建用户、不迁移数据库、不调用模型。"""

from __future__ import annotations

import argparse
from datetime import timedelta
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import func

from app.core.config import settings
from app.db.database import BACKEND_DIR, DATABASE_DIALECT, SessionLocal, engine
from app.db.models import RegistrationSetting, User, WorkerHeartbeat
from app.db.schema_version import get_schema_status
from app.services.background_job_service import utc_now, utc_text


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    message: str


def _result(name: str, ok: bool, message: str, *, dry_run: bool = False) -> Check:
    return Check(name, "pass" if ok else ("warn" if dry_run else "fail"), message)


def _path(value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else BACKEND_DIR / candidate


def configuration_checks(*, dry_run: bool) -> list[Check]:
    production = settings.app_environment.lower() == "production"
    checks = [
        _result("production_mode", production, "APP_ENVIRONMENT 应为 production", dry_run=dry_run),
        _result("jwt_secret", bool(settings.jwt_secret_key), "JWT Secret 已配置（值不显示）", dry_run=dry_run),
        _result("csrf_secret", bool(settings.auth_csrf_secret), "CSRF Secret 已配置（值不显示）", dry_run=dry_run),
        _result("cookie_secure", settings.auth_cookie_secure, "生产 Cookie 必须启用 Secure", dry_run=dry_run),
        _result("cookie_samesite", settings.auth_cookie_samesite in {"lax", "strict"}, "SameSite 应为 lax 或 strict", dry_run=dry_run),
        _result("cors", bool(settings.cors_allowed_origins) and "*" not in settings.cors_allowed_origins and all(origin.startswith("https://") for origin in settings.cors_allowed_origins), "CORS 必须使用明确 HTTPS Origin", dry_run=dry_run),
        _result("trusted_proxy", bool(settings.trusted_proxy_cidrs), "仅信任实际反向代理网段", dry_run=dry_run),
        _result("postgresql", DATABASE_DIALECT == "postgresql", "生产数据库必须为 PostgreSQL", dry_run=dry_run),
        _result("deepseek", bool(settings.deepseek_api_key), "DeepSeek 配置存在（不会调用）", dry_run=True),
        _result("tavily", bool(settings.tavily_api_key), "Tavily 配置存在（不会调用）", dry_run=True),
        _result("invite", bool(settings.registration_invite_code), "环境邀请码已配置，或应在数据库中配置", dry_run=True),
        _result("legacy_patches", not settings.enable_legacy_schema_patches, "旧 Schema patch 必须关闭", dry_run=dry_run),
        _result("sync_compat", not settings.enable_sync_long_task_compat, "旧同步长任务兼容必须关闭", dry_run=dry_run),
        _result("origin_check", settings.auth_require_origin_check, "CSRF Origin 校验必须开启", dry_run=dry_run),
    ]
    return checks


def runtime_checks(*, dry_run: bool) -> list[Check]:
    checks: list[Check] = []
    try:
        schema = get_schema_status(engine)
        checks.append(_result("alembic_head", schema.ready, f"current={schema.current or 'none'} head={schema.head}", dry_run=dry_run))
    except Exception as exc:
        checks.append(Check("alembic_head", "warn" if dry_run else "fail", f"无法读取 Schema：{type(exc).__name__}"))

    for name, path in (
        ("uploads", _path(settings.upload_dir)),
        ("chroma", _path(settings.chroma_persist_dir)),
        ("backups", BACKEND_DIR / "backups"),
    ):
        ok = path.exists() and path.is_dir() and os.access(path, os.W_OK)
        checks.append(_result(f"{name}_writable", ok, f"{name} 持久目录存在且可写", dry_run=dry_run))

    try:
        db = SessionLocal()
        active_after = utc_text(utc_now() - timedelta(seconds=settings.job_lease_seconds * 2))
        worker_count = db.query(func.count(WorkerHeartbeat.worker_id)).filter(WorkerHeartbeat.stopped_at.is_(None), WorkerHeartbeat.heartbeat_at >= active_after).scalar() or 0
        invite_ready = db.get(RegistrationSetting, 1) is not None or bool(settings.registration_invite_code)
        default_admin = db.query(User).filter(User.username.in_(["admin", "administrator"]), User.is_admin.is_(True)).first()
        checks.append(_result("worker_heartbeat", worker_count > 0, f"活跃 Worker 数：{worker_count}", dry_run=dry_run))
        checks.append(_result("invite_ready", invite_ready, "邀请码配置可用", dry_run=dry_run))
        checks.append(_result("default_admin_absent", default_admin is None, "未发现通用默认管理员账号", dry_run=dry_run))
    except Exception as exc:
        checks.append(Check("database_runtime", "warn" if dry_run else "fail", f"数据库只读检查失败：{type(exc).__name__}"))
    finally:
        if "db" in locals():
            db.close()

    free_gb = shutil.disk_usage(BACKEND_DIR).free / 1024**3
    checks.append(_result("disk_space", free_gb >= 2, f"可用磁盘约 {free_gb:.1f} GiB", dry_run=dry_run))
    return checks


def tool_checks(*, dry_run: bool) -> list[Check]:
    checks = []
    for name, command in (("docker", ["docker", "--version"]), ("compose", ["docker", "compose", "version", "--short"]), ("docker_daemon", ["docker", "info", "--format", "{{.ServerVersion}}"]),):
        try:
            result = subprocess.run(command, cwd=BACKEND_DIR.parent, capture_output=True, text=True, timeout=10, check=False)
            checks.append(_result(name, result.returncode == 0, f"{name} CLI {'可用' if result.returncode == 0 else '不可用'}", dry_run=dry_run))
        except (OSError, subprocess.TimeoutExpired):
            checks.append(_result(name, False, f"{name} CLI 不可用", dry_run=dry_run))

    try:
        result = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=BACKEND_DIR.parent, capture_output=True, text=True, timeout=10, check=False)
        sensitive_suffixes = (".env", ".pem", ".key", ".dump", ".backup", ".sqlite", ".sqlite3")
        flagged = [line[3:] for line in result.stdout.splitlines() if line[3:].lower().endswith(sensitive_suffixes)]
        checks.append(_result("untracked_sensitive", result.returncode == 0 and not flagged, f"未跟踪敏感文件：{len(flagged)}", dry_run=dry_run))
    except (OSError, subprocess.TimeoutExpired):
        checks.append(Check("untracked_sensitive", "warn" if dry_run else "fail", "无法执行 Git 只读扫描"))
    return checks


def run_preflight(*, dry_run: bool) -> list[Check]:
    return configuration_checks(dry_run=dry_run) + runtime_checks(dry_run=dry_run) + tool_checks(dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description="SPI 发布前只读检查")
    parser.add_argument("--dry-run", action="store_true", help="开发环境将生产缺项降级为 warn")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    checks = run_preflight(dry_run=args.dry_run)
    if args.json:
        print(json.dumps([asdict(item) for item in checks], ensure_ascii=False, indent=2))
    else:
        for item in checks:
            print(f"[{item.status.upper():4}] {item.name}: {item.message}")
    return 1 if any(item.status == "fail" for item in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
