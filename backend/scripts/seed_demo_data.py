"""为现有开发/测试账号写入可清理的纯虚构演示数据。"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.db.database import BACKEND_DIR, SessionLocal
from app.db.models import AdminAuditLog, FileRecord, TargetJob, User, UserProfile

DEMO_MARKER = "spi-demo-data-v1"
DEMO_FILENAME = "fictional_background_job_project.md"
DEMO_CONTENT = """# 星轨求职训练平台（纯虚构）

我负责设计数据库驱动的后台任务系统，使用幂等键避免重复创建任务，使用 lease 与 heartbeat 支持 Worker 异常后的恢复，并通过用户所有权条件保证任务隔离。

该内容仅用于本地演示，不对应任何真实公司、用户或生产指标。
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _upload_root() -> Path:
    path = Path(settings.upload_dir)
    return path if path.is_absolute() else BACKEND_DIR / path


def seed_for_user(db, user: User) -> dict:
    now = _now()
    created = []
    if user.profile is None:
        db.add(UserProfile(user_id=user.id, display_name="林舟（虚构）", target_direction="AI 应用 / Python 后端", self_introduction=f"纯虚构演示资料；{DEMO_MARKER}", technical_skills='["Python", "FastAPI", "PostgreSQL", "RAG"]', created_at=now, updated_at=now))
        created.append("profile")

    job = db.query(TargetJob).filter(TargetJob.user_id == user.id, TargetJob.notes == DEMO_MARKER).one_or_none()
    if job is None:
        has_active = db.query(TargetJob).filter(TargetJob.user_id == user.id, TargetJob.is_active.is_(True)).first() is not None
        db.add(TargetJob(user_id=user.id, job_title="AI 应用开发工程师（虚构）", company_name="星轨实验室（虚构）", jd_text="负责基于 FastAPI、RAG 与 Agent 工作流构建可验证的求职训练产品；重视安全、可观测性和可靠性。", notes=DEMO_MARKER, is_active=not has_active, created_at=now, updated_at=now))
        created.append("target_job")

    file_id = f"demo-project-{user.id}"
    record = db.query(FileRecord).filter(FileRecord.file_id == file_id).one_or_none()
    if record is None:
        user_dir = (_upload_root() / str(user.id)).resolve()
        user_dir.mkdir(parents=True, exist_ok=True)
        target = user_dir / DEMO_FILENAME
        if not target.exists():
            target.write_text(DEMO_CONTENT, encoding="utf-8")
        payload = target.read_bytes()
        db.add(FileRecord(user_id=user.id, file_id=file_id, filename=DEMO_FILENAME, file_type="md", file_path=str(target), size_bytes=len(payload), content_sha256=hashlib.sha256(payload).hexdigest(), upload_idempotency_key_hash=None, category="project", status="uploaded", error_message=None, created_at=now, updated_at=now))
        created.append("project_file")

    db.add(AdminAuditLog(admin_user_id=user.id if user.is_admin else None, action="seed_demo_data", target_user_id=user.id, resource_type="demo_data", resource_id=DEMO_MARKER, status="success", detail_summary="已写入纯虚构演示数据；未覆盖现有资料", created_at=now))
    db.commit()
    return {"success": True, "created": created, "skipped_existing": not bool(created)}


def cleanup_for_user(db, user: User) -> dict:
    removed = []
    record = db.query(FileRecord).filter(FileRecord.user_id == user.id, FileRecord.file_id == f"demo-project-{user.id}").one_or_none()
    if record is not None:
        path = Path(record.file_path).resolve()
        expected = (_upload_root() / str(user.id) / DEMO_FILENAME).resolve()
        if path == expected and path.is_file():
            path.unlink()
        db.delete(record)
        removed.append("project_file")
    for job in db.query(TargetJob).filter(TargetJob.user_id == user.id, TargetJob.notes == DEMO_MARKER).all():
        db.delete(job)
        removed.append("target_job")
    if user.profile is not None and user.profile.self_introduction == f"纯虚构演示资料；{DEMO_MARKER}":
        db.delete(user.profile)
        removed.append("profile")
    db.add(AdminAuditLog(admin_user_id=user.id if user.is_admin else None, action="cleanup_demo_data", target_user_id=user.id, resource_type="demo_data", resource_id=DEMO_MARKER, status="success", detail_summary="仅清理本工具创建且仍带标记的演示数据", created_at=_now()))
    db.commit()
    return {"success": True, "removed": removed}


def main() -> int:
    if settings.app_environment not in {"development", "test"}:
        raise SystemExit("演示数据工具仅允许在 development/test 环境运行")
    parser = argparse.ArgumentParser(description="写入或清理纯虚构演示数据")
    parser.add_argument("--username", help="现有本地账号；省略时交互输入")
    parser.add_argument("--cleanup", action="store_true", help="仅清理本工具创建的数据")
    args = parser.parse_args()
    username = (args.username or input("请输入现有演示账号用户名：")).strip().lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).one_or_none()
        if user is None:
            raise SystemExit("账号不存在；工具不会创建带默认密码的账号")
        result = cleanup_for_user(db, user) if args.cleanup else seed_for_user(db, user)
        print("demo_data=" + ("cleaned" if args.cleanup else "ready"))
        print("items=" + ",".join(result.get("removed", result.get("created", []))))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
