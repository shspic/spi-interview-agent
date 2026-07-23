from datetime import datetime
from auth_test_utils import cookie_headers, prepare_preauth

import pytest

from app.agents import evidence_agent, structured_llm
from app.agents.schemas import EvidenceItem, EvidenceOutput, InterviewPlanOutput
from app.agents.structured_llm import StructuredLLMError, invoke_structured
from app.db.models import (
    AgentRun,
    FileRecord,
    InterviewSession,
    InterviewTurn,
    UsageEvent,
)
from app.services import evidence_retrieval_service

PASSWORD = "strong-password-123"


class FakeInterviewLLM:
    def __init__(
        self,
        decisions=None,
        fail_interviewer_after=None,
        interviewer_questions=None,
    ):
        self.decisions = list(decisions or ["next_main_question"])
        self.fail_interviewer_after = fail_interviewer_after
        self.interviewer_questions = list(interviewer_questions or [])
        self.interviewer_calls = 0
        self.calls = 0

    def __call__(self, messages):
        self.calls += 1
        system_message = messages[0]["content"]
        user_message = messages[1]["content"]
        if "Supervisor Agent" in system_message:
            if "制定本场面试计划" in user_message:
                return (
                    '{"planned_main_questions":1,'
                    '"focus_areas":["project ownership","architecture"],'
                    '"strategy":"progressive technical interview",'
                    '"opening_focus":"project responsibility"}'
                )
            action = self.decisions.pop(0) if self.decisions else "complete"
            return f'{{"action":"{action}","reason":"test decision"}}'
        if "Evidence Agent" in system_message:
            return '{"query":"project ownership architecture troubleshooting"}'
        if "Evaluation Agent" in system_message:
            source_ids = (
                '["project-file"]'
                if '"is_sufficient":true' in user_message
                else "[]"
            )
            return (
                '{"technical_accuracy_score":80,'
                '"evidence_consistency_score":75,'
                '"answer_depth_score":70,'
                '"expression_structure_score":85,'
                '"job_match_score":65,'
                '"evaluation_summary":"Solid answer with room for detail",'
                '"problems":[],"optimized_answer":"Detailed answer",'
                '"modification_reason":"Use a clearer structure",'
                '"has_evidence_conflict":false,"evidence_conflicts":[],'
                f'"evidence_source_ids":{source_ids},'
                '"unsupported_claims":[],"strengths":["Clear structure"]}'
            )
        if "Interviewer Agent" in system_message:
            self.interviewer_calls += 1
            if (
                self.fail_interviewer_after is not None
                and self.interviewer_calls > self.fail_interviewer_after
            ):
                return "invalid interviewer output"
            intent_questions = {
                "project_background": "请说明这段真实项目的项目背景和当时目标。",
                "personal_responsibility": "在这段经历中，哪些工作由你亲自负责？",
                "technical_decision": "请说明一个具体技术决策及其取舍依据。",
                "challenge_solution": "最棘手的难点是什么，请说明实际解决步骤。",
                "verifiable_result": "最终结果如何被验证？",
                "collaboration_reflection": "请说明一次真实协作或复盘。",
                "role_expertise": "这段经历体现了哪项岗位能力？",
            }
            target_intent = next(
                (
                    intent
                    for intent in intent_questions
                    if f'"intent": "{intent}"' in user_message
                ),
                "project_background",
            )
            question = (
                self.interviewer_questions.pop(0)
                if self.interviewer_questions
                else intent_questions[target_intent]
            )
            return (
                '{"question":"Generated question '
                f'{self.interviewer_calls}?",'
                '"rationale":"grounded in evidence",'
                '"evidence_limited":false}'
            ).replace(f"Generated question {self.interviewer_calls}?", question)
        raise AssertionError("未预期的测试 LLM 调用")


def register_and_login(client, username):
    prepare_preauth(client)
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "invite_code": "test-invite-code",
        },
    )
    assert response.status_code == 201
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    payload = response.json()
    return (
        cookie_headers(client),
        payload["user"]["id"],
    )


def create_session(client, headers, mode="quick"):
    response = client.post(
        "/api/interview-sessions",
        headers=headers,
        json={
            "title": f"{mode} agent interview",
            "mode": mode,
            "selected_project_file_ids": [],
        },
    )
    assert response.status_code == 201
    return response.json()


def sufficient_evidence():
    item = EvidenceItem(
        evidence_type="project",
        source_id="project-file",
        filename="project.txt",
        content="Implemented a RAG service and owned retrieval debugging.",
        distance=0.2,
    )
    return EvidenceOutput(
        is_sufficient=True,
        reason="reliable project evidence",
        best_distance=0.2,
        sources=[item],
        context=item.content,
        profile_evidence=[],
        project_evidence=[item],
        resume_evidence=[],
        job_requirements=[],
    )


def install_fake_agents(monkeypatch, fake_llm, evidence=None):
    monkeypatch.setattr(structured_llm, "chat_with_messages", fake_llm)
    monkeypatch.setattr(
        evidence_agent,
        "retrieve_interview_evidence",
        lambda **kwargs: evidence or sufficient_evidence(),
    )


def start_session(client, headers, session_id):
    return client.post(
        f"/api/interview-sessions/{session_id}/start",
        headers=headers,
    )


def answer_turn(client, headers, session_id, turn_id, answer="Detailed answer"):
    return client.post(
        f"/api/interview-sessions/{session_id}/answer",
        headers=headers,
        json={"turn_id": turn_id, "answer": answer},
    )


def test_quick_start_generates_first_question_and_agent_runs(
    client,
    db_session,
    monkeypatch,
):
    fake_llm = FakeInterviewLLM()
    install_fake_agents(monkeypatch, fake_llm)
    headers, user_id = register_and_login(client, "alice")
    session = create_session(client, headers)

    response = start_session(client, headers, session["id"])

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "in_progress"
    assert payload["planned_main_questions"] == 3
    assert payload["interview_plan"]["planned_main_questions"] == 3
    assert payload["current_question"]["main_question_number"] == 1
    assert payload["current_question"]["follow_up_number"] == 0
    detail = client.get(
        f"/api/interview-sessions/{session['id']}",
        headers=headers,
    ).json()
    assert detail["current_question"]["id"] == payload["current_question"]["id"]
    assert detail["completed_main_questions"] == 0
    assert detail["current_follow_up_count"] == 0
    assert detail["is_completed"] is False
    assert detail["agent_execution_summary"]["run_id"]
    runs = (
        db_session.query(AgentRun)
        .filter(AgentRun.session_id == session["id"], AgentRun.user_id == user_id)
        .order_by(AgentRun.id)
        .all()
    )
    assert [run.agent_name for run in runs] == [
        "supervisor",
        "evidence",
        "interviewer",
    ]
    assert all(run.prompt_version and run.latency_ms >= 0 for run in runs)
    assert all(run.status == "success" and run.error is None for run in runs)
    assert db_session.query(UsageEvent).filter_by(
        user_id=user_id,
        usage_type="multi_agent_task",
        status="succeeded",
    ).count() == 1


def test_standard_start_uses_five_question_plan(client, monkeypatch):
    install_fake_agents(monkeypatch, FakeInterviewLLM())
    headers, _ = register_and_login(client, "alice")
    session = create_session(client, headers, mode="standard")

    response = start_session(client, headers, session["id"])

    assert response.status_code == 200
    assert response.json()["interview_plan"]["planned_main_questions"] == 5


def test_repeated_start_does_not_duplicate_first_question(
    client,
    db_session,
    monkeypatch,
):
    install_fake_agents(monkeypatch, FakeInterviewLLM())
    headers, _ = register_and_login(client, "alice")
    session_id = create_session(client, headers)["id"]

    assert start_session(client, headers, session_id).status_code == 200
    assert start_session(client, headers, session_id).status_code == 409
    assert db_session.query(InterviewTurn).filter_by(session_id=session_id).count() == 1
    assert db_session.query(UsageEvent).filter_by(
        usage_type="multi_agent_task",
        status="succeeded",
    ).count() == 1


def test_user_cannot_start_or_answer_another_users_session(client, monkeypatch):
    install_fake_agents(monkeypatch, FakeInterviewLLM())
    alice_headers, _ = register_and_login(client, "alice")
    bob_headers, _ = register_and_login(client, "bob")
    session_id = create_session(client, alice_headers)["id"]
    started = start_session(client, alice_headers, session_id).json()

    assert start_session(client, bob_headers, session_id).status_code == 404
    assert answer_turn(
        client,
        bob_headers,
        session_id,
        started["current_question"]["id"],
    ).status_code == 404


def test_answer_generates_next_main_question_and_rejects_repeat(
    client,
    db_session,
    monkeypatch,
):
    install_fake_agents(
        monkeypatch,
        FakeInterviewLLM(decisions=["next_main_question"]),
    )
    headers, _ = register_and_login(client, "alice")
    session_id = create_session(client, headers)["id"]
    first_turn = start_session(client, headers, session_id).json()["current_question"]

    response = answer_turn(client, headers, session_id, first_turn["id"])

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"]["action"] == "next_main_question"
    assert payload["current_question"]["main_question_number"] == 2
    assert payload["completed_main_questions"] == 1
    stored = db_session.get(InterviewTurn, first_turn["id"])
    assert stored.user_answer == "Detailed answer"
    assert stored.answered_at is not None
    assert answer_turn(
        client,
        headers,
        session_id,
        first_turn["id"],
    ).status_code == 409


def test_supervisor_follow_up_creates_follow_up_number_one(client, monkeypatch):
    install_fake_agents(monkeypatch, FakeInterviewLLM(decisions=["follow_up"]))
    headers, _ = register_and_login(client, "alice")
    session_id = create_session(client, headers)["id"]
    first_turn = start_session(client, headers, session_id).json()["current_question"]

    response = answer_turn(client, headers, session_id, first_turn["id"])

    assert response.status_code == 200
    assert response.json()["decision"]["action"] == "follow_up"
    assert response.json()["current_question"]["follow_up_number"] == 1


def test_follow_up_is_limited_to_two_then_moves_forward(client, monkeypatch):
    install_fake_agents(
        monkeypatch,
        FakeInterviewLLM(decisions=["follow_up", "follow_up", "follow_up"]),
    )
    headers, _ = register_and_login(client, "alice")
    session_id = create_session(client, headers)["id"]
    current = start_session(client, headers, session_id).json()["current_question"]

    first_follow_up = answer_turn(
        client,
        headers,
        session_id,
        current["id"],
    ).json()["current_question"]
    second_follow_up = answer_turn(
        client,
        headers,
        session_id,
        first_follow_up["id"],
    ).json()["current_question"]
    response = answer_turn(
        client,
        headers,
        session_id,
        second_follow_up["id"],
    )

    assert first_follow_up["follow_up_number"] == 1
    assert second_follow_up["follow_up_number"] == 2
    assert response.status_code == 200
    assert response.json()["decision"]["action"] == "next_main_question"
    assert response.json()["current_question"]["main_question_number"] == 2


def test_repeated_model_questions_retry_once_then_progress_and_save_distinct_turns(
    client,
    db_session,
    monkeypatch,
):
    repeated_question = "请说明这段真实经历的项目背景。"
    llm = FakeInterviewLLM(
        decisions=["follow_up", "follow_up"],
        interviewer_questions=[repeated_question] * 5,
    )
    install_fake_agents(monkeypatch, llm)
    headers, _ = register_and_login(client, "alice")
    session_id = create_session(client, headers)["id"]

    main_question = start_session(client, headers, session_id).json()[
        "current_question"
    ]
    first_follow_up = answer_turn(
        client,
        headers,
        session_id,
        main_question["id"],
        answer="我参与了这个项目。",
    ).json()["current_question"]
    second_follow_up = answer_turn(
        client,
        headers,
        session_id,
        first_follow_up["id"],
        answer="我参与了这个项目。",
    ).json()["current_question"]

    questions = [
        main_question["question"],
        first_follow_up["question"],
        second_follow_up["question"],
    ]
    stored_turns = (
        db_session.query(InterviewTurn)
        .filter(InterviewTurn.session_id == session_id)
        .order_by(InterviewTurn.sequence_number.asc())
        .all()
    )
    assert llm.interviewer_calls == 5
    assert len(set(questions)) == 3
    assert [turn.question for turn in stored_turns] == questions
    assert [turn.follow_up_number for turn in stored_turns] == [0, 1, 2]
    assert "亲自负责" in first_follow_up["question"]
    assert "技术选择" in second_follow_up["question"]


def test_session_completes_after_planned_main_questions(client, monkeypatch):
    install_fake_agents(
        monkeypatch,
        FakeInterviewLLM(
            decisions=["next_main_question", "next_main_question", "complete"]
        ),
    )
    headers, _ = register_and_login(client, "alice")
    session_id = create_session(client, headers)["id"]
    current = start_session(client, headers, session_id).json()["current_question"]

    for _ in range(2):
        current = answer_turn(
            client,
            headers,
            session_id,
            current["id"],
        ).json()["current_question"]
    completed = answer_turn(client, headers, session_id, current["id"])

    assert completed.status_code == 200
    payload = completed.json()
    assert payload["status"] == "completed"
    assert payload["is_completed"] is True
    assert payload["current_question"] is None
    assert payload["completed_main_questions"] == 3


def test_non_current_turn_and_user_id_field_are_rejected(client, monkeypatch):
    install_fake_agents(monkeypatch, FakeInterviewLLM())
    headers, _ = register_and_login(client, "alice")
    first_session = create_session(client, headers)["id"]
    second_session = create_session(client, headers)["id"]
    first_turn = start_session(client, headers, first_session).json()["current_question"]
    second_turn = start_session(client, headers, second_session).json()["current_question"]

    assert answer_turn(
        client,
        headers,
        first_session,
        second_turn["id"],
    ).status_code == 409
    forged = client.post(
        f"/api/interview-sessions/{first_session}/answer",
        headers=headers,
        json={
            "turn_id": first_turn["id"],
            "answer": "answer",
            "user_id": 999,
        },
    )
    assert forged.status_code == 422


def test_insufficient_evidence_uses_open_question_without_fabrication(
    client,
    monkeypatch,
):
    fake_llm = FakeInterviewLLM()
    monkeypatch.setattr(structured_llm, "chat_with_messages", fake_llm)
    monkeypatch.setattr(
        evidence_retrieval_service,
        "search_candidate_chunks",
        lambda **kwargs: {"chunks": [], "distance_metric": "l2_squared"},
    )
    headers, _ = register_and_login(client, "alice")
    session_id = create_session(client, headers)["id"]

    response = start_session(client, headers, session_id)

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_limited"] is True
    assert "真实项目" in payload["current_question"]["question"]
    assert "Generated question" not in payload["current_question"]["question"]


def test_evidence_retrieval_forces_user_filter_and_rejects_low_relevance(
    client,
    db_session,
    monkeypatch,
):
    headers, user_id = register_and_login(client, "alice")
    session_id = create_session(client, headers)["id"]
    now = datetime.now().isoformat(timespec="seconds")
    db_session.add(
        FileRecord(
            user_id=user_id,
            file_id="project-file",
            filename="project.txt",
            file_type="txt",
            file_path="project.txt",
            category="project",
            status="indexed",
            created_at=now,
            updated_at=now,
        )
    )
    db_session.commit()
    captured = {}

    def fake_search(query, user_id, candidate_k):
        captured["user_id"] = user_id
        return {
            "chunks": [
                {
                    "content": "unrelated content",
                    "metadata": {
                        "file_id": "project-file",
                        "filename": "project.txt",
                    },
                    "distance": 1.2,
                }
            ]
        }

    monkeypatch.setattr(
        evidence_retrieval_service,
        "search_candidate_chunks",
        fake_search,
    )
    result = evidence_retrieval_service.retrieve_interview_evidence(
        db_session,
        user_id,
        session_id,
        "query",
    )

    assert captured["user_id"] == user_id
    assert result.is_sufficient is False
    assert result.best_distance == 1.2
    assert result.project_evidence == []
    assert result.sources == []


def test_invalid_llm_structure_retries_once_then_succeeds():
    responses = iter(
        [
            "not-json",
            '{"planned_main_questions":3,"focus_areas":["project"],'
            '"strategy":"test","opening_focus":"test"}',
        ]
    )
    calls = []

    def fake_call(messages):
        calls.append(messages)
        return next(responses)

    result = invoke_structured(
        [{"role": "system", "content": "test"}],
        InterviewPlanOutput,
        fake_call,
    )

    assert result.planned_main_questions == 3
    assert len(calls) == 2


def test_two_invalid_structures_return_controlled_error_and_log_failure(
    client,
    db_session,
    monkeypatch,
):
    calls = []

    def invalid_llm(messages):
        calls.append(messages)
        return "invalid"

    monkeypatch.setattr(structured_llm, "chat_with_messages", invalid_llm)
    headers, _ = register_and_login(client, "alice")
    session_id = create_session(client, headers)["id"]

    response = start_session(client, headers, session_id)

    assert response.status_code == 502
    assert len(calls) == 2
    interview_session = db_session.get(InterviewSession, session_id)
    assert interview_session.status == "draft"
    assert db_session.query(InterviewTurn).filter_by(session_id=session_id).count() == 0
    failed_run = db_session.query(AgentRun).filter_by(session_id=session_id).one()
    assert failed_run.agent_name == "supervisor"
    assert failed_run.status == "error"
    assert failed_run.prompt_version


def test_next_question_failure_preserves_answer_and_supports_recovery(
    client,
    db_session,
    monkeypatch,
):
    failing_llm = FakeInterviewLLM(
        decisions=["next_main_question"],
        fail_interviewer_after=1,
    )
    install_fake_agents(monkeypatch, failing_llm)
    headers, _ = register_and_login(client, "alice")
    session_id = create_session(client, headers)["id"]
    first_turn = start_session(client, headers, session_id).json()["current_question"]

    failed = answer_turn(
        client,
        headers,
        session_id,
        first_turn["id"],
        answer="Persistent answer",
    )

    assert failed.status_code == 502
    stored = db_session.get(InterviewTurn, first_turn["id"])
    answered_at = stored.answered_at
    assert stored.user_answer == "Persistent answer"
    assert db_session.query(InterviewTurn).filter_by(session_id=session_id).count() == 1

    install_fake_agents(
        monkeypatch,
        FakeInterviewLLM(decisions=["next_main_question"]),
    )
    recovered = answer_turn(
        client,
        headers,
        session_id,
        first_turn["id"],
        answer="Persistent answer",
    )

    assert recovered.status_code == 200
    assert recovered.json()["current_question"]["main_question_number"] == 2
    db_session.refresh(stored)
    assert stored.answered_at == answered_at


def test_structured_llm_raises_after_second_invalid_result():
    calls = []

    def invalid_call(messages):
        calls.append(messages)
        return "invalid"

    with pytest.raises(StructuredLLMError):
        invoke_structured(
            [{"role": "system", "content": "test"}],
            InterviewPlanOutput,
            invalid_call,
        )
    assert len(calls) == 2
