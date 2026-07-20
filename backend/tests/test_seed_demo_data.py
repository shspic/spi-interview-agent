from datetime import datetime

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import FileRecord, TargetJob, User
from scripts.seed_demo_data import cleanup_for_user, seed_for_user


def test_demo_seed_is_idempotent_scoped_and_cleanable(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    user = User(username="seed_demo", password_hash=hash_password("unused-password"), is_active=True, is_admin=False, created_at=datetime.now().isoformat(timespec="seconds"), last_login_at=None)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    first = seed_for_user(db_session, user)
    second = seed_for_user(db_session, user)

    assert set(first["created"]) == {"profile", "target_job", "project_file"}
    assert second["skipped_existing"] is True
    assert db_session.query(FileRecord).filter_by(user_id=user.id).count() == 1
    assert db_session.query(TargetJob).filter_by(user_id=user.id).count() == 1

    result = cleanup_for_user(db_session, user)
    assert set(result["removed"]) == {"profile", "target_job", "project_file"}
    assert db_session.query(FileRecord).filter_by(user_id=user.id).count() == 0
    assert db_session.get(User, user.id) is not None
