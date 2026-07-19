import argparse
import sys
from pathlib import Path

from sqlalchemy import func

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.security import normalize_username
from app.db.database import SessionLocal, init_db
from app.db.models import User
from app.services.admin_audit_service import add_admin_audit_log


def parse_args():
    parser = argparse.ArgumentParser(
        description="提升或取消现有用户的管理员权限。默认仅预览。",
    )
    parser.add_argument("--username", required=True, help="现有用户名")
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="取消管理员权限；默认操作为提升管理员",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="确认执行；未提供时只显示预览",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    init_db()
    db = SessionLocal()
    try:
        username = normalize_username(args.username)
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            raise SystemExit("指定用户不存在，请先注册该用户。")

        action_name = "取消管理员权限" if args.revoke else "提升为管理员"
        print(f"预览：用户 {user.username} 将被{action_name}。")
        if not args.apply:
            print("未提供 --apply，数据库未修改。")
            return

        if args.revoke and user.is_admin:
            other_active_admins = (
                db.query(func.count(User.id))
                .filter(
                    User.is_admin.is_(True),
                    User.is_active.is_(True),
                    User.id != user.id,
                )
                .scalar()
                or 0
            )
            if other_active_admins == 0:
                raise SystemExit("操作已拒绝：系统中没有其他可用管理员。")

        user.is_admin = not args.revoke
        add_admin_audit_log(
            db,
            admin_user_id=None,
            action="revoke_admin" if args.revoke else "set_admin",
            target_user_id=user.id,
            resource_type="user",
            resource_id=user.id,
            status="success",
            detail_summary="管理员初始化脚本已执行",
            commit=False,
        )
        db.commit()
        print("操作完成。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
