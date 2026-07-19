from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.agents import structured_llm
from app.db.models import (
    FileRecord,
    ImprovementTask,
    InterviewSession,
    InterviewTurn,
)
from app.services import evidence_retrieval_service
from app.services.improvement_task_service import create_improvement_task
from app.services.interview_session_service import (
    InterviewTrainingServiceError,
    create_interview_turn,
)

PASSWORD = "strong-password-123"


@pytest.fixture()
def mock_interview_agents(monkeypatch):
    def fake_llm(messages):
        system_message = messages[0]["content"]
        if "Supervisor Agent" in system_message:
            return (
                '{"planned_main_questions":3,'
                '"focus_areas":["project"],'
                '"strategy":"progressive",'
                '"opening_focus":"project ownership"}'
            )
        if "Evidence Agent" in system_message:
            return '{"query":"project ownership and technical decisions"}'
        raise AssertionError("未预期的测试 Agent 调用")

    monkeypatch.setattr(structured_llm, "chat_with_messages", fake_llm)
    monkeypatch.setattr(
        evidence_retrieval_service,
        "search_candidate_chunks",
        lambda **kwargs: {
            "chunks": [],
            "distance_metric": "l2_squared",
        },
    )


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


def create_session(client, headers, mode="quick", **overrides):
    payload = {
        "title": f"{mode} interview",
        "mode": mode,
        "target_job_id": None,
        "selected_project_file_ids": [],
        "previous_session_id": None,
    }
    payload.update(overrides)
    return client.post(
        "/api/interview-sessions",
        headers=headers,
        json=payload,
    )


def create_project_file(db_session, user_id, file_id, category="project"):
    now = datetime.now().isoformat(timespec="seconds")
    record = FileRecord(
        user_id=user_id,
        file_id=file_id,
        filename=f"{file_id}.txt",
        file_type="txt",
        file_path=f"/tmp/{file_id}.txt",
        category=category,
        status="uploaded",
        created_at=now,
        updated_at=now,
    )
    db_session.add(record)
    db_session.commit()
    return record


def create_target_job(client, headers, title="Backend Engineer"):
    return client.post(
        "/api/target-jobs",
        headers=headers,
        json={
            "job_title": title,
            "company_name": "Example Company",
            "jd_text": "Build reliable backend services.",
            "notes": "",
            "is_active": True,
        },
    )


def mark_completed(db_session, session_id):
    interview_session = db_session.get(InterviewSession, session_id)
    now = datetime.now().isoformat(timespec="seconds")
    interview_session.status = "completed"
    interview_session.completed_at = now
    interview_session.updated_at = now
    db_session.commit()
    return interview_session


def test_quick_and_standard_sessions_set_planned_question_counts(
    client,
    db_session,
):
    headers, user_id = register_and_login(client, "alice")
    project = create_project_file(db_session, user_id, "alice-project")
    job = create_target_job(client, headers).json()

    quick = create_session(
        client,
        headers,
        target_job_id=job["id"],
        selected_project_file_ids=[project.file_id],
    )
    standard = create_session(client, headers, mode="standard")

    assert quick.status_code == 201
    assert quick.json()["planned_main_questions"] == 3
    assert quick.json()["status"] == "draft"
    assert quick.json()["target_job"]["id"] == job["id"]
    assert quick.json()["project_files"][0]["file_id"] == project.file_id
    assert standard.status_code == 201
    assert standard.json()["planned_main_questions"] == 5

    filtered = client.get(
        "/api/interview-sessions?status=draft&mode=quick",
        headers=headers,
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["sessions"]] == [
        quick.json()["id"]
    ]


def test_deep_dive_requires_at_least_one_project_file(client):
    headers, _ = register_and_login(client, "alice")

    response = create_session(client, headers, mode="deep_dive")

    assert response.status_code == 400


def test_deep_dive_rejects_non_project_file(client, db_session):
    headers, user_id = register_and_login(client, "alice")
    resume = create_project_file(
        db_session,
        user_id,
        "alice-resume",
        category="resume",
    )

    response = create_session(
        client,
        headers,
        mode="deep_dive",
        selected_project_file_ids=[resume.file_id],
    )

    assert response.status_code == 404


def test_user_cannot_use_other_users_job_or_project_file(client, db_session):
    alice_headers, _ = register_and_login(client, "alice")
    bob_headers, bob_id = register_and_login(client, "bob")
    bob_job = create_target_job(client, bob_headers, "Private Job").json()
    bob_project = create_project_file(db_session, bob_id, "bob-project")

    job_response = create_session(
        client,
        alice_headers,
        target_job_id=bob_job["id"],
    )
    file_response = create_session(
        client,
        alice_headers,
        selected_project_file_ids=[bob_project.file_id],
    )

    assert job_response.status_code == 404
    assert file_response.status_code == 404


def test_previous_session_must_be_own_completed_session(client, db_session):
    alice_headers, _ = register_and_login(client, "alice")
    bob_headers, _ = register_and_login(client, "bob")
    completed = create_session(client, alice_headers).json()
    draft = create_session(client, alice_headers).json()
    bob_completed = create_session(client, bob_headers).json()
    mark_completed(db_session, completed["id"])
    mark_completed(db_session, bob_completed["id"])

    valid = create_session(
        client,
        alice_headers,
        previous_session_id=completed["id"],
    )
    unfinished = create_session(
        client,
        alice_headers,
        previous_session_id=draft["id"],
    )
    cross_user = create_session(
        client,
        alice_headers,
        previous_session_id=bob_completed["id"],
    )

    assert valid.status_code == 201
    assert valid.json()["previous_session"]["id"] == completed["id"]
    assert unfinished.status_code == 404
    assert cross_user.status_code == 404


def test_user_cannot_operate_other_users_session(client):
    alice_headers, _ = register_and_login(client, "alice")
    bob_headers, _ = register_and_login(client, "bob")
    session_id = create_session(client, alice_headers).json()["id"]

    operations = [
        client.get(f"/api/interview-sessions/{session_id}", headers=bob_headers),
        client.patch(
            f"/api/interview-sessions/{session_id}",
            headers=bob_headers,
            json={"title": "forged"},
        ),
        client.post(
            f"/api/interview-sessions/{session_id}/start",
            headers=bob_headers,
        ),
        client.post(
            f"/api/interview-sessions/{session_id}/cancel",
            headers=bob_headers,
        ),
        client.delete(
            f"/api/interview-sessions/{session_id}",
            headers=bob_headers,
        ),
    ]

    assert all(response.status_code == 404 for response in operations)
    assert client.get(
        f"/api/interview-sessions/{session_id}",
        headers=alice_headers,
    ).status_code == 200


def test_draft_session_can_start_and_completed_session_cannot_cancel(
    client,
    db_session,
    mock_interview_agents,
):
    headers, _ = register_and_login(client, "alice")
    started_id = create_session(client, headers).json()["id"]

    started = client.post(
        f"/api/interview-sessions/{started_id}/start",
        headers=headers,
    )

    assert started.status_code == 200
    assert started.json()["status"] == "in_progress"
    assert started.json()["started_at"] is not None
    assert client.post(
        f"/api/interview-sessions/{started_id}/start",
        headers=headers,
    ).status_code == 409

    completed_id = create_session(client, headers).json()["id"]
    mark_completed(db_session, completed_id)
    response = client.post(
        f"/api/interview-sessions/{completed_id}/cancel",
        headers=headers,
    )
    assert response.status_code == 409


def test_main_question_allows_at_most_two_follow_ups(client, db_session):
    headers, user_id = register_and_login(client, "alice")
    session_id = create_session(client, headers).json()["id"]
    main_turn = create_interview_turn(
        db_session,
        user_id,
        session_id,
        question="Main question",
        main_question_number=1,
    )
    first = create_interview_turn(
        db_session,
        user_id,
        session_id,
        question="First follow up",
        parent_turn_id=main_turn.id,
    )
    second = create_interview_turn(
        db_session,
        user_id,
        session_id,
        question="Second follow up",
        parent_turn_id=first.id,
    )

    assert [main_turn.follow_up_number, first.follow_up_number, second.follow_up_number] == [
        0,
        1,
        2,
    ]
    with pytest.raises(InterviewTrainingServiceError) as error:
        create_interview_turn(
            db_session,
            user_id,
            session_id,
            question="Third follow up",
            parent_turn_id=main_turn.id,
        )
    assert error.value.status_code == 409


def test_parent_turn_cannot_cross_sessions(client, db_session):
    headers, user_id = register_and_login(client, "alice")
    first_session_id = create_session(client, headers).json()["id"]
    second_session_id = create_session(client, headers).json()["id"]
    first_main = create_interview_turn(
        db_session,
        user_id,
        first_session_id,
        question="Main question",
        main_question_number=1,
    )

    with pytest.raises(InterviewTrainingServiceError) as error:
        create_interview_turn(
            db_session,
            user_id,
            second_session_id,
            question="Invalid follow up",
            parent_turn_id=first_main.id,
        )
    assert error.value.status_code == 400


def test_improvement_tasks_are_isolated_and_can_toggle_status(client, db_session):
    alice_headers, alice_id = register_and_login(client, "alice")
    bob_headers, _ = register_and_login(client, "bob")
    session_id = create_session(client, alice_headers).json()["id"]
    turn = create_interview_turn(
        db_session,
        alice_id,
        session_id,
        question="Main question",
        main_question_number=1,
    )
    task = create_improvement_task(
        db_session,
        alice_id,
        session_id,
        turn_id=turn.id,
        title="Add technical evidence",
        description="Explain the implementation detail.",
        category="technical",
        priority="high",
    )

    alice_list = client.get(
        f"/api/improvement-tasks?status=pending&category=technical&session_id={session_id}",
        headers=alice_headers,
    )
    bob_list = client.get("/api/improvement-tasks", headers=bob_headers)

    assert [item["id"] for item in alice_list.json()["tasks"]] == [task.id]
    assert bob_list.json()["tasks"] == []
    assert client.patch(
        f"/api/improvement-tasks/{task.id}",
        headers=bob_headers,
        json={"status": "completed"},
    ).status_code == 404

    completed = client.patch(
        f"/api/improvement-tasks/{task.id}",
        headers=alice_headers,
        json={"status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None

    pending = client.patch(
        f"/api/improvement-tasks/{task.id}",
        headers=alice_headers,
        json={"status": "pending"},
    )
    assert pending.status_code == 200
    assert pending.json()["completed_at"] is None

    detail = client.get(
        f"/api/interview-sessions/{session_id}",
        headers=alice_headers,
    ).json()
    assert [item["id"] for item in detail["turns"]] == [turn.id]
    assert [item["id"] for item in detail["improvement_tasks"]] == [task.id]


def test_deleting_session_cascades_turns_and_tasks(client, db_session):
    headers, user_id = register_and_login(client, "alice")
    session_id = create_session(client, headers).json()["id"]
    turn = create_interview_turn(
        db_session,
        user_id,
        session_id,
        question="Main question",
        main_question_number=1,
    )
    task = create_improvement_task(
        db_session,
        user_id,
        session_id,
        turn_id=turn.id,
        title="Improve answer",
        description="Use a clearer structure.",
        category="expression",
        priority="medium",
    )

    response = client.delete(
        f"/api/interview-sessions/{session_id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert db_session.get(InterviewSession, session_id) is None
    assert db_session.get(InterviewTurn, turn.id) is None
    assert db_session.get(ImprovementTask, task.id) is None


def test_all_training_endpoints_require_authentication(client):
    requests = [
        client.post(
            "/api/interview-sessions",
            json={"title": "test", "mode": "quick"},
        ),
        client.get("/api/interview-sessions"),
        client.get("/api/interview-sessions/1"),
        client.patch("/api/interview-sessions/1", json={"title": "test"}),
        client.delete("/api/interview-sessions/1"),
        client.post("/api/interview-sessions/1/start"),
        client.post("/api/interview-sessions/1/cancel"),
        client.get("/api/improvement-tasks"),
        client.patch("/api/improvement-tasks/1", json={"status": "completed"}),
    ]

    assert all(response.status_code == 401 for response in requests)


def test_request_bodies_reject_user_id_and_unknown_fields(client):
    headers, _ = register_and_login(client, "alice")
    forged = create_session(client, headers, user_id=999)
    unknown = create_session(client, headers, unexpected="value")
    session_id = create_session(client, headers).json()["id"]
    status_patch = client.patch(
        f"/api/interview-sessions/{session_id}",
        headers=headers,
        json={"status": "completed"},
    )
    task_patch = client.patch(
        "/api/improvement-tasks/999",
        headers=headers,
        json={"status": "completed", "user_id": 999},
    )

    assert forged.status_code == 422
    assert unknown.status_code == 422
    assert status_patch.status_code == 422
    assert task_patch.status_code == 422


@pytest.mark.parametrize(
    "score_field",
    [
        "technical_accuracy_score",
        "evidence_consistency_score",
        "answer_depth_score",
        "expression_structure_score",
        "job_match_score",
        "total_score",
    ],
)
def test_turn_score_fields_are_limited_to_zero_through_one_hundred(
    client,
    db_session,
    score_field,
):
    headers, user_id = register_and_login(client, "alice")
    session_id = create_session(client, headers).json()["id"]
    turn = create_interview_turn(
        db_session,
        user_id,
        session_id,
        question="Main question",
        main_question_number=1,
    )
    setattr(turn, score_field, 101)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
