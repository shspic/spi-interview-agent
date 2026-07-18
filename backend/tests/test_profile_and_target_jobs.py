from datetime import datetime

from app.core.config import settings
from app.db.models import FileRecord, TargetJob, UserProfile

PASSWORD = "strong-password-123"


def register_and_login(client, username):
    register_response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "invite_code": "test-invite-code",
        },
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login_response.status_code == 200
    payload = login_response.json()

    return (
        {"Authorization": f"Bearer {payload['access_token']}"},
        payload["user"]["id"],
    )


def create_job(client, headers, title, is_active=False):
    return client.post(
        "/api/target-jobs",
        headers=headers,
        json={
            "job_title": title,
            "company_name": "测试公司",
            "jd_text": f"{title} 的岗位描述",
            "notes": "测试备注",
            "is_active": is_active,
        },
    )


def test_user_can_create_and_update_own_profile(client, db_session):
    headers, user_id = register_and_login(client, "alice")

    empty_response = client.get("/api/profile", headers=headers)
    assert empty_response.status_code == 200
    assert empty_response.json()["profile"] is None

    create_response = client.put(
        "/api/profile",
        headers=headers,
        json={
            "display_name": "Alice",
            "target_direction": "RAG 应用开发",
            "self_introduction": "关注 AI 应用工程。",
            "technical_skills": ["Python", " FastAPI ", "python", ""],
        },
    )
    assert create_response.status_code == 200
    created_profile = create_response.json()
    assert created_profile["user_id"] == user_id
    assert created_profile["technical_skills"] == ["Python", "FastAPI"]

    update_response = client.put(
        "/api/profile",
        headers=headers,
        json={
            "display_name": "Alice Chen",
            "target_direction": "AI 应用开发",
            "self_introduction": "持续完善项目经历。",
            "technical_skills": ["Python", "LangGraph"],
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["display_name"] == "Alice Chen"
    assert db_session.query(UserProfile).filter_by(user_id=user_id).count() == 1


def test_user_cannot_access_another_users_profile(client):
    alice_headers, alice_id = register_and_login(client, "alice")
    bob_headers, bob_id = register_and_login(client, "bob")

    assert client.put(
        "/api/profile",
        headers=alice_headers,
        json={
            "display_name": "Alice",
            "target_direction": "AI",
            "self_introduction": "private",
            "technical_skills": ["Python"],
        },
    ).status_code == 200

    bob_profile = client.get("/api/profile", headers=bob_headers)
    assert bob_profile.status_code == 200
    assert bob_profile.json()["profile"] is None

    forged_response = client.put(
        "/api/profile",
        headers=bob_headers,
        json={
            "user_id": alice_id,
            "display_name": "Bob",
            "target_direction": "Backend",
            "self_introduction": "own profile",
            "technical_skills": ["SQL"],
        },
    )
    assert forged_response.status_code == 422

    bob_save = client.put(
        "/api/profile",
        headers=bob_headers,
        json={
            "display_name": "Bob",
            "target_direction": "Backend",
            "self_introduction": "own profile",
            "technical_skills": ["SQL"],
        },
    )
    assert bob_save.status_code == 200
    assert bob_save.json()["user_id"] == bob_id


def test_user_can_create_multiple_jobs_with_only_one_active(client, db_session):
    headers, user_id = register_and_login(client, "alice")

    first = create_job(client, headers, "AI 工程师", is_active=True)
    second = create_job(client, headers, "后端工程师", is_active=True)

    assert first.status_code == 201
    assert second.status_code == 201

    jobs_response = client.get("/api/target-jobs", headers=headers)
    jobs = jobs_response.json()["jobs"]
    assert len(jobs) == 2
    assert sum(job["is_active"] for job in jobs) == 1
    assert next(job for job in jobs if job["is_active"])["id"] == second.json()["id"]
    assert (
        db_session.query(TargetJob)
        .filter(TargetJob.user_id == user_id, TargetJob.is_active.is_(True))
        .count()
        == 1
    )

    activate_first = client.post(
        f"/api/target-jobs/{first.json()['id']}/activate",
        headers=headers,
    )
    assert activate_first.status_code == 200
    assert activate_first.json()["is_active"] is True

    active_jobs = [
        job
        for job in client.get("/api/target-jobs", headers=headers).json()["jobs"]
        if job["is_active"]
    ]
    assert [job["id"] for job in active_jobs] == [first.json()["id"]]


def test_user_cannot_operate_another_users_job(client):
    alice_headers, _ = register_and_login(client, "alice")
    bob_headers, _ = register_and_login(client, "bob")
    job_response = create_job(client, alice_headers, "私有岗位", is_active=True)
    job_id = job_response.json()["id"]

    assert client.get(
        f"/api/target-jobs/{job_id}", headers=bob_headers
    ).status_code == 404
    assert client.put(
        f"/api/target-jobs/{job_id}",
        headers=bob_headers,
        json={
            "job_title": "伪造修改",
            "company_name": "其他公司",
            "jd_text": "不应成功",
            "notes": "",
        },
    ).status_code == 404
    assert client.post(
        f"/api/target-jobs/{job_id}/activate", headers=bob_headers
    ).status_code == 404
    assert client.delete(
        f"/api/target-jobs/{job_id}", headers=bob_headers
    ).status_code == 404

    owner_response = client.get(
        f"/api/target-jobs/{job_id}", headers=alice_headers
    )
    assert owner_response.status_code == 200
    assert owner_response.json()["job_title"] == "私有岗位"


def test_deleting_active_job_allows_no_active_job(client):
    headers, _ = register_and_login(client, "alice")
    job = create_job(client, headers, "当前目标", is_active=True).json()

    delete_response = client.delete(
        f"/api/target-jobs/{job['id']}", headers=headers
    )
    assert delete_response.status_code == 200
    assert client.get("/api/target-jobs", headers=headers).json()["jobs"] == []


def test_legacy_file_category_defaults_to_other(client, db_session, tmp_path):
    headers, user_id = register_and_login(client, "alice")
    now = datetime.now().isoformat(timespec="seconds")
    record = FileRecord(
        user_id=user_id,
        file_id="legacy-file",
        filename="legacy.txt",
        file_type="txt",
        file_path=str(tmp_path / "legacy.txt"),
        status="uploaded",
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(record)
    db_session.commit()

    response = client.get("/api/files", headers=headers)

    assert response.status_code == 200
    assert response.json()["files"][0]["category"] == "other"


def test_file_categories_remain_isolated_by_user(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    alice_headers, _ = register_and_login(client, "alice")
    bob_headers, _ = register_and_login(client, "bob")

    alice_upload = client.post(
        "/api/files/upload",
        headers=alice_headers,
        files={"file": ("resume.txt", b"resume content", "text/plain")},
        data={"category": "resume"},
    )
    bob_upload = client.post(
        "/api/files/upload",
        headers=bob_headers,
        files={"file": ("project.txt", b"project content", "text/plain")},
        data={"category": "project"},
    )

    assert alice_upload.status_code == 200
    assert alice_upload.json()["category"] == "resume"
    assert bob_upload.status_code == 200
    assert bob_upload.json()["category"] == "project"

    alice_files = client.get("/api/files", headers=alice_headers).json()["files"]
    bob_files = client.get("/api/files", headers=bob_headers).json()["files"]

    assert [(item["filename"], item["category"]) for item in alice_files] == [
        ("resume.txt", "resume")
    ]
    assert [(item["filename"], item["category"]) for item in bob_files] == [
        ("project.txt", "project")
    ]
