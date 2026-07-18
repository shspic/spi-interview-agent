import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.security import normalize_username
from app.db.database import SessionLocal, init_db
from app.db.models import FileRecord, HistoryRecord, InterviewRecord, User
from app.services.vector_store import get_collection


def parse_args():
    parser = argparse.ArgumentParser(
        description="将旧版未归属数据显式迁移给指定的现有用户。默认仅预览。",
    )
    parser.add_argument("--username", required=True, help="接收旧数据的现有用户名")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="确认执行迁移；未提供时只显示待迁移数量",
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

        legacy_files = db.query(FileRecord).filter(FileRecord.user_id.is_(None)).all()
        legacy_history = (
            db.query(HistoryRecord).filter(HistoryRecord.user_id.is_(None)).all()
        )
        legacy_interviews = (
            db.query(InterviewRecord).filter(InterviewRecord.user_id.is_(None)).all()
        )

        print(f"目标用户：{user.username}（id={user.id}）")
        print(f"待迁移文件记录：{len(legacy_files)}")
        print(f"待迁移历史记录：{len(legacy_history)}")
        print(f"待迁移面试记录：{len(legacy_interviews)}")

        if not args.apply:
            print("当前为预览模式。确认无误后增加 --apply 再次执行。")
            return

        for record in legacy_files:
            record.user_id = user.id

        for record in legacy_history:
            record.user_id = user.id

        for record in legacy_interviews:
            record.user_id = user.id

        db.commit()

        owned_file_ids = {
            record.file_id
            for record in db.query(FileRecord).filter(FileRecord.user_id == user.id).all()
        }
        collection = get_collection()
        vector_data = collection.get(include=["metadatas"])
        vector_ids = vector_data.get("ids", []) or []
        metadatas = vector_data.get("metadatas", []) or []
        update_ids = []
        update_metadatas = []

        for vector_id, metadata in zip(vector_ids, metadatas):
            current_metadata = metadata or {}

            if (
                current_metadata.get("user_id") is None
                and current_metadata.get("file_id") in owned_file_ids
            ):
                update_ids.append(vector_id)
                update_metadatas.append({**current_metadata, "user_id": user.id})

        if update_ids:
            collection.update(ids=update_ids, metadatas=update_metadatas)

        print(f"迁移完成，已补充用户归属的向量片段：{len(update_ids)}")
        print("旧文件物理路径保持不变；后续按该用户重建索引时会写入用户隔离向量。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
