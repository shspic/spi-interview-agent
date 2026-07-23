import argparse
import sys
from pathlib import Path

from sqlalchemy import func

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.security import normalize_username
from app.db.database import SessionLocal, engine
from app.db.schema_version import require_current_schema
from app.db.models import User
from app.services.admin_audit_service import add_admin_audit_log


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="设置现有用户的管理员权限和 AI 每日额度豁免。默认仅预览。",
    )
    parser.add_argument("--username", required=True, help="现有用户名")
    admin_group = parser.add_mutually_exclusive_group()
    admin_group.add_argument(
        "--grant-admin",
        dest="admin_target",
        action="store_const",
        const=True,
        help="授予管理员权限",
    )
    admin_group.add_argument(
        "--revoke-admin",
        "--revoke",
        dest="admin_target",
        action="store_const",
        const=False,
        help="撤销管理员权限（--revoke 为兼容别名）",
    )
    quota_group = parser.add_mutually_exclusive_group()
    quota_group.add_argument(
        "--grant-quota-exempt",
        dest="quota_target",
        action="store_const",
        const=True,
        help="授予 AI 每日额度豁免",
    )
    quota_group.add_argument(
        "--revoke-quota-exempt",
        dest="quota_target",
        action="store_const",
        const=False,
        help="撤销 AI 每日额度豁免",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="确认执行；未提供时只显示预览",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    require_current_schema(engine)
    db = SessionLocal()
    try:
        username = normalize_username(args.username)
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            raise SystemExit("指定用户不存在，请先注册该用户。")

        admin_target = args.admin_target
        quota_target = args.quota_target
        if admin_target is None and quota_target is None:
            admin_target = True
        if admin_target is None:
            admin_target = bool(user.is_admin)
        if quota_target is None:
            quota_target = bool(user.is_quota_exempt)

        print(f"user id: {user.id}")
        print(f"username: {user.username}")
        print(f"当前 is_admin: {bool(user.is_admin)}")
        print(f"目标 is_admin: {admin_target}")
        print(f"当前 is_quota_exempt: {bool(user.is_quota_exempt)}")
        print(f"目标 is_quota_exempt: {quota_target}")
        if not args.apply:
            print("未提供 --apply，数据库未修改。")
            return

        if not admin_target and user.is_admin:
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

        changes = []
        if bool(user.is_admin) != admin_target:
            user.is_admin = admin_target
            changes.append((
                "set_admin" if admin_target else "revoke_admin",
                "管理员权限已由管理脚本更新",
            ))
        if bool(user.is_quota_exempt) != quota_target:
            user.is_quota_exempt = quota_target
            changes.append((
                "grant_quota_exempt" if quota_target else "revoke_quota_exempt",
                "AI 每日额度豁免已由管理脚本更新",
            ))
        if not changes:
            print("目标状态已存在，数据库无需修改。")
            return
        for action, detail_summary in changes:
            add_admin_audit_log(
                db,
                admin_user_id=None,
                action=action,
                target_user_id=user.id,
                resource_type="user",
                resource_id=user.id,
                status="success",
                detail_summary=detail_summary,
                commit=False,
            )
        db.commit()
        print("操作完成。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
