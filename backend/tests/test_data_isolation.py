from datetime import datetime

from app.core.security import create_access_token, hash_password
from app.db.models import FileRecord, HistoryRecord, InterviewRecord, User


def create_user(db_session, username):
    user = User(
        username=username,
        password_hash=hash_password("strong-password-123"),
        is_active=True,
        is_admin=False,
        created_at=datetime.now().isoformat(timespec="seconds"),
        last_login_at=None,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def auth_headers(user):
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def create_file_record(db_session, user, file_path, file_id="file-b"):
    now = datetime.now().isoformat(timespec="seconds")
    record = FileRecord(
        user_id=user.id,
        file_id=file_id,
        filename="private.txt",
        file_type="txt",
        file_path=str(file_path),
        status="uploaded",
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(record)
    db_session.commit()
    return record


def test_user_cannot_view_another_users_files(client, db_session, tmp_path):
    user_a = create_user(db_session, "alice")
    user_b = create_user(db_session, "bob")
    file_path = tmp_path / "private.txt"
    file_path.write_text("private", encoding="utf-8")
    create_file_record(db_session, user_b, file_path)

    response = client.get("/api/files", headers=auth_headers(user_a))

    assert response.status_code == 200
    assert response.json()["files"] == []


def test_user_cannot_delete_another_users_file(
    client,
    db_session,
    tmp_path,
    monkeypatch,
):
    user_a = create_user(db_session, "alice")
    user_b = create_user(db_session, "bob")
    file_path = tmp_path / "private.txt"
    file_path.write_text("private", encoding="utf-8")
    record = create_file_record(db_session, user_b, file_path)
    vector_delete_called = False

    def fake_delete_file_vectors(user_id, file_id):
        nonlocal vector_delete_called
        vector_delete_called = True

    monkeypatch.setattr(
        "app.api.files.delete_file_vectors",
        fake_delete_file_vectors,
    )

    response = client.delete(
        f"/api/files/{record.file_id}",
        headers=auth_headers(user_a),
    )

    assert response.status_code == 404
    assert db_session.query(FileRecord).filter(FileRecord.id == record.id).first()
    assert file_path.exists()
    assert not vector_delete_called


def test_user_cannot_view_another_users_history_or_interview(
    client,
    db_session,
):
    user_a = create_user(db_session, "alice")
    user_b = create_user(db_session, "bob")
    now = datetime.now().isoformat(timespec="seconds")
    history = HistoryRecord(
        user_id=user_b.id,
        record_id="history-b",
        mode="chat",
        user_input="private question",
        ai_output="private answer",
        sources="[]",
        used_web_search=0,
        web_sources="[]",
        route_reason="",
        execution_steps="[]",
        created_at=now,
    )
    interview = InterviewRecord(
        user_id=user_b.id,
        session_id="interview-b",
        interview_type="test",
        job_description="private jd",
        question_index=1,
        question="private question",
        user_answer="private answer",
        score_total=80,
        content_relevance=16,
        personal_match=16,
        technical_accuracy=16,
        structure_score=16,
        risk_control=16,
        main_problems="",
        suggestions="",
        reference_answer="",
        created_at=now,
    )
    db_session.add_all([history, interview])
    db_session.commit()
    headers = auth_headers(user_a)

    history_response = client.get(
        f"/api/history/{history.record_id}",
        headers=headers,
    )
    interview_response = client.get(
        f"/api/interview-records/{interview.session_id}",
        headers=headers,
    )

    assert history_response.status_code == 404
    assert interview_response.status_code == 404
