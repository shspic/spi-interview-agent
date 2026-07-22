from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import AdminAuditLog, User
from scripts import set_admin


@pytest.fixture()
def cli_database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'cli.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    now = datetime.now().isoformat(timespec="seconds")
    db.add_all(
        [
            User(
                username="target_user",
                password_hash="target-password-hash",
                is_active=True,
                is_admin=False,
                is_quota_exempt=False,
                created_at=now,
            ),
            User(
                username="other_admin",
                password_hash="other-password-hash",
                is_active=True,
                is_admin=True,
                is_quota_exempt=False,
                created_at=now,
            ),
        ]
    )
    db.commit()
    db.close()
    monkeypatch.setattr(set_admin, "SessionLocal", session_factory)
    monkeypatch.setattr(set_admin, "require_current_schema", lambda _: None)
    monkeypatch.setattr(set_admin, "engine", engine)
    try:
        yield session_factory
    finally:
        engine.dispose()


def test_cli_dry_run_displays_safe_current_and_target_state(
    cli_database,
    capsys,
):
    set_admin.main([
        "--username",
        "target_user",
        "--grant-admin",
        "--grant-quota-exempt",
    ])
    output = capsys.readouterr().out
    db = cli_database()
    try:
        target = db.query(User).filter_by(username="target_user").one()
        assert target.is_admin is False
        assert target.is_quota_exempt is False
        assert db.query(AdminAuditLog).count() == 0
        assert "user id:" in output
        assert "username: target_user" in output
        assert "当前 is_admin: False" in output
        assert "目标 is_admin: True" in output
        assert "当前 is_quota_exempt: False" in output
        assert "目标 is_quota_exempt: True" in output
        assert "password" not in output.lower()
    finally:
        db.close()


def test_cli_apply_is_scoped_idempotent_audited_and_protects_last_admin(
    cli_database,
):
    grant = [
        "--username",
        "target_user",
        "--grant-admin",
        "--grant-quota-exempt",
        "--apply",
    ]
    set_admin.main(grant)
    set_admin.main(grant)

    db = cli_database()
    try:
        target = db.query(User).filter_by(username="target_user").one()
        other = db.query(User).filter_by(username="other_admin").one()
        assert target.is_admin is True
        assert target.is_quota_exempt is True
        assert target.password_hash == "target-password-hash"
        assert other.is_admin is True
        assert other.is_quota_exempt is False
        assert other.password_hash == "other-password-hash"
        assert db.query(User).count() == 2
        assert db.query(AdminAuditLog).filter_by(target_user_id=target.id).count() == 2
    finally:
        db.close()

    set_admin.main([
        "--username",
        "target_user",
        "--revoke-quota-exempt",
        "--apply",
    ])
    set_admin.main([
        "--username",
        "target_user",
        "--revoke-admin",
        "--apply",
    ])
    with pytest.raises(SystemExit, match="没有其他可用管理员"):
        set_admin.main([
            "--username",
            "other_admin",
            "--revoke-admin",
            "--apply",
        ])

    db = cli_database()
    try:
        target = db.query(User).filter_by(username="target_user").one()
        other = db.query(User).filter_by(username="other_admin").one()
        assert target.is_admin is False
        assert target.is_quota_exempt is False
        assert other.is_admin is True
        actions = {
            log.action
            for log in db.query(AdminAuditLog).filter_by(target_user_id=target.id)
        }
        assert actions == {
            "set_admin",
            "grant_quota_exempt",
            "revoke_admin",
            "revoke_quota_exempt",
        }
    finally:
        db.close()
