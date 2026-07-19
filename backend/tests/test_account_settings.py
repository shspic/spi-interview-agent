from datetime import datetime

from app.core.config import settings
from app.core.security import hash_password
from auth_test_utils import session_headers
from app.db.models import (
    DailyUsageCounter,
    FileRecord,
    HistoryRecord,
    InterviewSession,
    TargetJob,
    UsageEvent,
    User,
    UserDataDeletionLog,
    UserProfile,
)
from app.services import account_data_service

OLD_PASSWORD = "old-password-123"
NEW_PASSWORD = "new-password-456"


def add_user(db_session, username: str) -> User:
    now = datetime.now().isoformat(timespec="seconds")
    user = User(
        username=username,
        password_hash=hash_password(OLD_PASSWORD),
        is_active=True,
        is_admin=False,
        created_at=now,
        last_login_at=None,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def auth_headers(db_session, user: User) -> dict:
    return session_headers(db_session, user)


def test_user_can_change_password_and_old_password_stops_working(client, db_session):
    user = add_user(db_session, "change_password")

    response = client.post(
        "/api/auth/change-password",
        headers=auth_headers(db_session, user),
        json={
            "current_password": OLD_PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    client.get("/api/auth/csrf")
    old_login = client.post(
        "/api/auth/login",
        json={"username": user.username, "password": OLD_PASSWORD},
    )
    new_login = client.post(
        "/api/auth/login",
        json={"username": user.username, "password": NEW_PASSWORD},
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_change_password_rejects_wrong_same_and_extra_fields(client, db_session):
    user = add_user(db_session, "change_rejected")
    common = {"headers": auth_headers(db_session, user)}

    wrong = client.post(
        "/api/auth/change-password",
        json={
            "current_password": "wrong-password",
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
        **common,
    )
    same = client.post(
        "/api/auth/change-password",
        json={
            "current_password": OLD_PASSWORD,
            "new_password": OLD_PASSWORD,
            "confirm_password": OLD_PASSWORD,
        },
        **common,
    )
    extra = client.post(
        "/api/auth/change-password",
        json={
            "current_password": OLD_PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
            "user_id": user.id,
        },
        **common,
    )

    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "当前密码错误"
    assert same.status_code == 400
    assert same.json()["detail"] == "新密码不能与当前密码相同"
    assert extra.status_code == 422


def add_cleanup_data(db_session, user: User, file_path, suffix: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    db_session.add_all(
        [
            UserProfile(
                user_id=user.id,
                display_name=f"profile-{suffix}",
                target_direction="backend",
                self_introduction="intro",
                technical_skills="[]",
                created_at=now,
                updated_at=now,
            ),
            TargetJob(
                user_id=user.id,
                job_title="backend",
                company_name="company",
                jd_text="jd",
                notes="",
                is_active=True,
                created_at=now,
                updated_at=now,
            ),
            FileRecord(
                user_id=user.id,
                file_id=f"file-{suffix}",
                filename=file_path.name,
                file_type="txt",
                file_path=str(file_path),
                category="project",
                status="indexed",
                created_at=now,
                updated_at=now,
            ),
            HistoryRecord(
                user_id=user.id,
                record_id=f"history-{suffix}",
                mode="chat",
                user_input="question",
                ai_output="answer",
                created_at=now,
            ),
            InterviewSession(
                user_id=user.id,
                title=f"session-{suffix}",
                mode="quick",
                status="draft",
                planned_main_questions=3,
                current_main_question=0,
                selected_project_file_ids=[],
                created_at=now,
                updated_at=now,
            ),
            UsageEvent(
                user_id=user.id,
                usage_type="chat",
                usage_date="2026-07-19",
                idempotency_key=f"usage-{suffix}",
                status="succeeded",
                amount=1,
                reserved_at=now,
                completed_at=now,
                created_at=now,
                updated_at=now,
            ),
            DailyUsageCounter(
                user_id=user.id,
                usage_type="chat",
                usage_date="2026-07-19",
                used=1,
                reserved=0,
                updated_at=now,
            ),
        ]
    )
    db_session.commit()


def test_cleanup_preview_and_execution_are_user_scoped_and_keep_configuration(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    first = add_user(db_session, "cleanup_first")
    second = add_user(db_session, "cleanup_second")
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_root))
    first_file = upload_root / str(first.id) / "first.txt"
    second_file = upload_root / str(second.id) / "second.txt"
    first_file.parent.mkdir(parents=True)
    second_file.parent.mkdir(parents=True)
    first_file.write_text("first", encoding="utf-8")
    second_file.write_text("second", encoding="utf-8")
    add_cleanup_data(db_session, first, first_file, "first")
    add_cleanup_data(db_session, second, second_file, "second")
    vector_users = []
    monkeypatch.setattr(
        account_data_service,
        "delete_user_vectors",
        lambda user_id: vector_users.append(user_id),
    )

    preview = client.post(
        "/api/account/data-cleanup-preview",
        headers=auth_headers(db_session, first),
        json={},
    )
    forged = client.post(
        "/api/account/data-cleanup-preview",
        headers=auth_headers(db_session, first),
        json={"user_id": second.id},
    )
    assert preview.status_code == 200
    assert preview.json()["estimated_counts"]["files"] == 1
    assert forged.status_code == 422

    response = client.post(
        "/api/account/data-cleanup",
        headers=auth_headers(db_session, first),
        json={"current_password": OLD_PASSWORD, "confirm": "DELETE_MY_DATA"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert vector_users == [first.id]
    assert not first_file.exists()
    assert second_file.exists()
    assert db_session.get(User, first.id) is not None
    assert db_session.query(UserProfile).filter_by(user_id=first.id).count() == 1
    assert db_session.query(TargetJob).filter_by(user_id=first.id).count() == 1
    assert db_session.query(UsageEvent).filter_by(user_id=first.id).count() == 1
    assert db_session.query(DailyUsageCounter).filter_by(user_id=first.id).count() == 1
    assert db_session.query(FileRecord).filter_by(user_id=first.id).count() == 0
    assert db_session.query(FileRecord).filter_by(user_id=second.id).count() == 1
    assert db_session.query(UserDataDeletionLog).filter_by(
        user_id=first.id,
        status="success",
    ).count() == 1

    repeated = client.post(
        "/api/account/data-cleanup",
        headers=auth_headers(db_session, first),
        json={"current_password": OLD_PASSWORD, "confirm": "DELETE_MY_DATA"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["deleted_counts"]["files"] == 0


def test_cleanup_rejects_bad_credentials_and_reports_vector_failure(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    user = add_user(db_session, "cleanup_failure")
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_root))
    file_path = upload_root / str(user.id) / "failure.txt"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("failure", encoding="utf-8")
    add_cleanup_data(db_session, user, file_path, "failure")

    wrong_password = client.post(
        "/api/account/data-cleanup",
        headers=auth_headers(db_session, user),
        json={"current_password": "wrong-password", "confirm": "DELETE_MY_DATA"},
    )
    wrong_confirm = client.post(
        "/api/account/data-cleanup",
        headers=auth_headers(db_session, user),
        json={"current_password": OLD_PASSWORD, "confirm": "wrong"},
    )
    assert wrong_password.status_code == 400
    assert wrong_confirm.status_code == 422

    monkeypatch.setattr(
        account_data_service,
        "delete_user_vectors",
        lambda user_id: (_ for _ in ()).throw(RuntimeError("vector failed")),
    )
    response = client.post(
        "/api/account/data-cleanup",
        headers=auth_headers(db_session, user),
        json={"current_password": OLD_PASSWORD, "confirm": "DELETE_MY_DATA"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["failed_items"][0]["error_type"] == "RuntimeError"
    assert file_path.exists()
    assert db_session.query(FileRecord).filter_by(user_id=user.id).count() == 1
    assert db_session.query(UserDataDeletionLog).filter_by(
        user_id=user.id,
        status="failed",
    ).count() == 3
