from datetime import datetime

from app.core.config import settings
from app.core.security import create_access_token
from app.db.models import (
    AdminAuditLog,
    FileRecord,
    HistoryRecord,
    ImprovementTask,
    InterviewSession,
    InterviewTurn,
    TargetJob,
    User,
    UserProfile,
)
from app.services import data_retention_service


def add_user(db_session, username: str, is_admin: bool = False) -> User:
    now = datetime.now().isoformat(timespec="seconds")
    user = User(
        username=username,
        password_hash="unused-test-password-hash",
        is_active=True,
        is_admin=is_admin,
        created_at=now,
        last_login_at=None,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def add_session_tree(db_session, user_id: int, created_at: str) -> InterviewSession:
    interview_session = InterviewSession(
        user_id=user_id,
        title="old session",
        mode="quick",
        status="completed",
        planned_main_questions=3,
        current_main_question=1,
        selected_project_file_ids=[],
        created_at=created_at,
        updated_at=created_at,
        completed_at=created_at,
    )
    db_session.add(interview_session)
    db_session.flush()
    turn = InterviewTurn(
        session_id=interview_session.id,
        user_id=user_id,
        sequence_number=1,
        main_question_number=1,
        follow_up_number=0,
        question="question",
        question_type="main",
        user_answer="answer",
        has_evidence_conflict=False,
        created_at=created_at,
        updated_at=created_at,
    )
    db_session.add(turn)
    db_session.flush()
    db_session.add(
        ImprovementTask(
            user_id=user_id,
            session_id=interview_session.id,
            turn_id=turn.id,
            title="task",
            description="description",
            completion_criteria="done",
            category="technical",
            priority="high",
            status="pending",
            dedupe_key="old-task",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    db_session.commit()
    return interview_session


def test_cleanup_preview_preserves_data_and_cleanup_respects_retention_scope(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    admin = add_user(db_session, "cleanup_admin", is_admin=True)
    user = add_user(db_session, "cleanup_user")
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_root))
    old = "2000-01-01T00:00:00"
    recent = datetime.now().isoformat(timespec="seconds")
    old_file_path = upload_root / str(user.id) / "old.txt"
    old_file_path.parent.mkdir(parents=True)
    old_file_path.write_text("old", encoding="utf-8")
    recent_file_path = upload_root / str(user.id) / "recent.txt"
    recent_file_path.write_text("recent", encoding="utf-8")
    db_session.add_all(
        [
            UserProfile(
                user_id=user.id,
                display_name="user",
                target_direction="backend",
                self_introduction="intro",
                technical_skills="[]",
                created_at=old,
                updated_at=old,
            ),
            TargetJob(
                user_id=user.id,
                job_title="backend",
                company_name="company",
                jd_text="jd",
                notes="",
                is_active=True,
                created_at=old,
                updated_at=old,
            ),
            FileRecord(
                user_id=user.id,
                file_id="old-file",
                filename="old.txt",
                file_type="txt",
                file_path=str(old_file_path),
                category="project",
                status="indexed",
                created_at=old,
                updated_at=old,
            ),
            FileRecord(
                user_id=user.id,
                file_id="missing-old-file",
                filename="missing.txt",
                file_type="txt",
                file_path=str(upload_root / str(user.id) / "missing.txt"),
                category="other",
                status="indexed",
                created_at=old,
                updated_at=old,
            ),
            FileRecord(
                user_id=user.id,
                file_id="recent-file",
                filename="recent.txt",
                file_type="txt",
                file_path=str(recent_file_path),
                category="project",
                status="indexed",
                created_at=recent,
                updated_at=recent,
            ),
            HistoryRecord(
                user_id=user.id,
                record_id="old-history",
                mode="chat",
                user_input="old",
                ai_output="old",
                created_at=old,
            ),
            HistoryRecord(
                user_id=user.id,
                record_id="recent-history",
                mode="chat",
                user_input="recent",
                ai_output="recent",
                created_at=recent,
            ),
        ]
    )
    db_session.commit()
    session = add_session_tree(db_session, user.id, old)
    session_id = session.id
    vector_calls = []
    monkeypatch.setattr(
        data_retention_service,
        "delete_file_vectors",
        lambda user_id, file_id: vector_calls.append((user_id, file_id)),
    )

    preview = client.post(
        "/api/admin/maintenance/cleanup-preview",
        headers=headers(admin),
    )
    assert preview.status_code == 200
    assert preview.json()["estimated_counts"]["files"] == 2
    assert old_file_path.exists()
    assert db_session.query(HistoryRecord).count() == 2

    response = client.post(
        "/api/admin/maintenance/cleanup",
        headers=headers(admin),
        json={"confirm": "DELETE_EXPIRED_DATA"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert set(vector_calls) == {
        (user.id, "old-file"),
        (user.id, "missing-old-file"),
    }
    assert not old_file_path.exists()
    assert recent_file_path.exists()
    assert db_session.get(User, user.id) is not None
    assert db_session.query(UserProfile).filter_by(user_id=user.id).count() == 1
    assert db_session.query(TargetJob).filter_by(user_id=user.id).count() == 1
    assert db_session.query(FileRecord).filter_by(file_id="recent-file").count() == 1
    assert db_session.query(HistoryRecord).filter_by(
        record_id="recent-history"
    ).count() == 1
    assert db_session.get(InterviewSession, session_id) is None
    assert db_session.query(InterviewTurn).filter_by(session_id=session_id).count() == 0
    assert db_session.query(ImprovementTask).filter_by(
        session_id=session_id
    ).count() == 0
    assert db_session.query(AdminAuditLog).filter_by(
        action="cleanup_data",
        status="success",
    ).count() == 1

    repeated = client.post(
        "/api/admin/maintenance/cleanup",
        headers=headers(admin),
        json={"confirm": "DELETE_EXPIRED_DATA"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["deleted_counts"]["files"] == 0


def test_cleanup_reports_vector_failure_and_keeps_file_record(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    admin = add_user(db_session, "cleanup_fail_admin", is_admin=True)
    user = add_user(db_session, "cleanup_fail_user")
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_root))
    old = "2000-01-01T00:00:00"
    file_path = upload_root / str(user.id) / "failed.txt"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("old", encoding="utf-8")
    db_session.add(
        FileRecord(
            user_id=user.id,
            file_id="failed-file",
            filename="failed.txt",
            file_type="txt",
            file_path=str(file_path),
            category="project",
            status="indexed",
            created_at=old,
            updated_at=old,
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        data_retention_service,
        "delete_file_vectors",
        lambda user_id, file_id: (_ for _ in ()).throw(RuntimeError("failed")),
    )

    response = client.post(
        "/api/admin/maintenance/cleanup",
        headers=headers(admin),
        json={"confirm": "DELETE_EXPIRED_DATA"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["failed_items"][0]["error_type"] == "RuntimeError"
    assert db_session.query(FileRecord).filter_by(file_id="failed-file").count() == 1
    assert file_path.exists()
    assert db_session.query(AdminAuditLog).filter_by(
        action="cleanup_data",
        status="failed",
    ).count() == 1
