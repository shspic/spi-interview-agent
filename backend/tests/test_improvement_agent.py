import json
from datetime import datetime
from auth_test_utils import cookie_headers, prepare_preauth

import pytest

from app.agents import evidence_agent, structured_llm
from app.agents.improvement_agent import ImprovementAgent
from app.agents.schemas import (
    EvidenceOutput,
    ImprovementInput,
    ImprovementTurnInput,
)
from app.agents.structured_llm import StructuredLLMError
from app.db.models import (
    AgentRun,
    FileRecord,
    ImprovementTask,
    InterviewSession,
    InterviewTurn,
)
from app.services.improvement_task_service import create_improvement_task
from app.services.interview_session_service import create_interview_turn

PASSWORD = "strong-password-123"
DIMENSIONS = {
    "technical_accuracy_score": 80.0,
    "evidence_consistency_score": 70.0,
    "answer_depth_score": 60.0,
    "expression_structure_score": 90.0,
    "job_match_score": 75.0,
}


def register_and_login(client, username):
    prepare_preauth(client)
    assert client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "invite_code": "test-invite-code",
        },
    ).status_code == 201
    payload = client.post(
        "/api/auth/login",
        json={"username": username, "password": PASSWORD},
    ).json()
    return (
        cookie_headers(client),
        payload["user"]["id"],
    )


def create_session(client, headers, **overrides):
    payload = {"title": "improvement interview", "mode": "quick"}
    payload.update(overrides)
    response = client.post(
        "/api/interview-sessions",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def valid_improvement_output(source_turn_id=None):
    categories = ["technical", "answer_depth", "expression"]
    return {
        "overall_diagnosis": "技术细节和回答深度需要优先改善",
        "strongest_dimensions": ["expression_structure_score"],
        "weakest_dimensions": ["answer_depth_score"],
        "next_round_strategy": "下一轮优先追问技术决策和个人职责",
        "tasks": [
            {
                "title": f"改进任务 {index + 1}",
                "description": "基于本轮评价补充可验证的回答细节",
                "category": category,
                "priority": "high" if index == 0 else "medium",
                "source_turn_id": source_turn_id if index == 0 else None,
                "completion_criteria": "完成一次结构化口述并覆盖问题、方案和结果",
            }
            for index, category in enumerate(categories)
        ],
    }


def improvement_input(turn_id=1):
    return ImprovementInput(
        mode="quick",
        overall_score=72,
        dimension_scores=DIMENSIONS,
        turns=[
            ImprovementTurnInput(
                turn_id=turn_id,
                question="请说明你的技术决策。",
                technical_accuracy_score=80,
                evidence_consistency_score=70,
                answer_depth_score=60,
                expression_structure_score=90,
                job_match_score=75,
                total_score=74,
                evaluation_summary="回答清晰，但技术取舍说明不足。",
            )
        ],
    )


class ImprovementFlowLLM:
    def __init__(self, improvement_responses=None):
        self.improvement_responses = list(improvement_responses or [])
        self.improvement_calls = 0
        self.plan_messages = []
        self.calls = []

    def __call__(self, messages):
        system_message = messages[0]["content"]
        user_message = messages[1]["content"]
        self.calls.append((system_message, user_message))
        if "Improvement Agent" in system_message:
            self.improvement_calls += 1
            if self.improvement_responses:
                response = self.improvement_responses.pop(0)
                return response if isinstance(response, str) else json.dumps(response)
            return json.dumps(valid_improvement_output())
        if "Supervisor Agent" in system_message:
            if "制定本场面试计划" in user_message:
                self.plan_messages.append(user_message)
                return json.dumps(
                    {
                        "planned_main_questions": 3,
                        "focus_areas": ["技术决策"],
                        "strategy": "围绕改进方向训练",
                        "opening_focus": "个人职责",
                    },
                    ensure_ascii=False,
                )
            return '{"action":"complete","reason":"计划题目已完成"}'
        if "Evaluation Agent" in system_message:
            return json.dumps(
                {
                    "technical_accuracy_score": 80,
                    "evidence_consistency_score": 70,
                    "answer_depth_score": 60,
                    "expression_structure_score": 90,
                    "job_match_score": 75,
                    "evaluation_summary": "回答清晰但深度不足",
                    "problems": [],
                    "optimized_answer": "我会按真实经历补充技术决策。",
                    "modification_reason": "补充结构和技术取舍",
                    "has_evidence_conflict": False,
                    "evidence_conflicts": [],
                    "evidence_source_ids": [],
                    "unsupported_claims": [],
                    "strengths": ["表达清晰"],
                },
                ensure_ascii=False,
            )
        if "Evidence Agent" in system_message:
            return '{"query":"technical decision and responsibility"}'
        if "Interviewer Agent" in system_message:
            return json.dumps(
                {
                    "question": "请说明你在项目中的实际职责。",
                    "rationale": "训练个人职责表达",
                    "evidence_limited": True,
                },
                ensure_ascii=False,
            )
        raise AssertionError("未预期的 LLM 调用")


def install_flow(monkeypatch, llm):
    monkeypatch.setattr(structured_llm, "chat_with_messages", llm)
    monkeypatch.setattr(
        evidence_agent,
        "retrieve_interview_evidence",
        lambda **kwargs: EvidenceOutput(
            is_sufficient=False,
            reason="测试中无用户事实证据",
            best_distance=None,
            sources=[],
            context="",
            profile_evidence=[],
            project_evidence=[],
            resume_evidence=[],
            job_requirements=[],
        ),
    )


def prepare_in_progress_session(client, db_session, headers, user_id):
    session = create_session(client, headers)
    interview_session = db_session.get(InterviewSession, session["id"])
    now = datetime.now().isoformat(timespec="seconds")
    interview_session.status = "in_progress"
    interview_session.planned_main_questions = 1
    interview_session.current_main_question = 1
    interview_session.started_at = now
    interview_session.interview_plan = {
        "planned_main_questions": 1,
        "focus_areas": ["技术决策"],
        "strategy": "逐步追问",
        "opening_focus": "项目职责",
    }
    interview_session.updated_at = now
    db_session.commit()
    turn = create_interview_turn(
        db_session,
        user_id,
        session["id"],
        question="请说明你的技术决策。",
        main_question_number=1,
    )
    return interview_session, turn


def mark_completed_with_score(db_session, session_id, scores=None):
    interview_session = db_session.get(InterviewSession, session_id)
    now = datetime.now().isoformat(timespec="seconds")
    interview_session.status = "completed"
    interview_session.completed_at = now
    interview_session.overall_score = None if scores is None else scores["overall"]
    interview_session.dimension_scores = (
        None if scores is None else scores["dimensions"]
    )
    interview_session.updated_at = now
    db_session.commit()
    return interview_session


def add_scored_turn(db_session, user_id, session_id):
    turn = create_interview_turn(
        db_session,
        user_id,
        session_id,
        question="请说明你的技术决策。",
        main_question_number=1,
    )
    turn.user_answer = "我按真实经历说明了技术决策。"
    turn.technical_accuracy_score = 80
    turn.evidence_consistency_score = 70
    turn.answer_depth_score = 60
    turn.expression_structure_score = 90
    turn.job_match_score = 75
    turn.total_score = 74
    turn.evaluation_summary = "回答清晰，但技术取舍说明不足。"
    turn.problems = []
    turn.evidence_conflicts = []
    turn.unsupported_claims = []
    turn.strengths = ["表达清晰"]
    turn.answered_at = datetime.now().isoformat(timespec="seconds")
    db_session.commit()
    return turn


def test_completion_generates_tasks_and_agent_run(
    client,
    db_session,
    monkeypatch,
):
    llm = ImprovementFlowLLM()
    install_flow(monkeypatch, llm)
    headers, user_id = register_and_login(client, "alice")
    interview_session, turn = prepare_in_progress_session(
        client,
        db_session,
        headers,
        user_id,
    )

    response = client.post(
        f"/api/interview-sessions/{interview_session.id}/answer",
        headers=headers,
        json={"turn_id": turn.id, "answer": "我负责技术方案取舍。"},
    )

    runs = db_session.query(AgentRun).filter_by(
        session_id=interview_session.id
    ).all()
    assert response.status_code == 200, (
        response.text,
        [(run.agent_name, run.status, run.error) for run in runs],
        llm.calls,
    )
    assert response.json()["status"] == "completed"
    assert response.json()["improvement_status"] == "completed"
    tasks = db_session.query(ImprovementTask).filter_by(
        session_id=interview_session.id
    ).all()
    assert 3 <= len(tasks) <= 8
    assert all(task.completion_criteria for task in tasks)
    run = db_session.query(AgentRun).filter_by(
        session_id=interview_session.id,
        agent_name="improvement",
    ).one()
    assert run.prompt_version == "improvement_v2"
    assert run.status == "success"
    assert run.latency_ms >= 0


def test_invalid_category_and_source_turn_retry_once():
    invalid_category = valid_improvement_output()
    invalid_category["tasks"][0]["category"] = "invalid"
    responses = iter(
        [json.dumps(invalid_category), json.dumps(valid_improvement_output())]
    )
    calls = []
    agent = ImprovementAgent(lambda messages: calls.append(messages) or next(responses))
    assert len(agent.generate(improvement_input()).tasks) == 3
    assert len(calls) == 2

    invalid_priority = valid_improvement_output()
    invalid_priority["tasks"][0]["priority"] = "urgent"
    responses = iter(
        [json.dumps(invalid_priority), json.dumps(valid_improvement_output())]
    )
    calls = []
    agent = ImprovementAgent(lambda messages: calls.append(messages) or next(responses))
    assert len(agent.generate(improvement_input()).tasks) == 3
    assert len(calls) == 2

    invalid_source = valid_improvement_output(source_turn_id=999)
    responses = iter(
        [json.dumps(invalid_source), json.dumps(valid_improvement_output(1))]
    )
    calls = []
    agent = ImprovementAgent(lambda messages: calls.append(messages) or next(responses))
    assert agent.generate(improvement_input(1)).tasks[0].source_turn_id == 1
    assert len(calls) == 2


def test_source_turn_cannot_cross_session_or_user(client, db_session, monkeypatch):
    headers, user_id = register_and_login(client, "alice")
    other_headers, other_user_id = register_and_login(client, "bob")
    source = create_session(client, headers)
    other = create_session(client, other_headers)
    source_turn = add_scored_turn(db_session, user_id, source["id"])
    other_turn = add_scored_turn(db_session, other_user_id, other["id"])
    mark_completed_with_score(
        db_session,
        source["id"],
        {"overall": 74, "dimensions": DIMENSIONS},
    )
    llm = ImprovementFlowLLM(
        [
            valid_improvement_output(other_turn.id),
            valid_improvement_output(source_turn.id),
        ]
    )
    install_flow(monkeypatch, llm)

    response = client.post(
        f"/api/interview-sessions/{source['id']}/improvements/retry",
        headers=headers,
    )

    assert response.status_code == 200
    assert llm.improvement_calls == 2
    assert response.json()["tasks"][0]["turn_id"] == source_turn.id


def test_generation_failure_preserves_completed_and_retry_is_idempotent(
    client,
    db_session,
    monkeypatch,
):
    headers, user_id = register_and_login(client, "alice")
    session = create_session(client, headers)
    add_scored_turn(db_session, user_id, session["id"])
    mark_completed_with_score(
        db_session,
        session["id"],
        {"overall": 74, "dimensions": DIMENSIONS},
    )
    llm = ImprovementFlowLLM(
        ["invalid json", "still invalid", valid_improvement_output()]
    )
    install_flow(monkeypatch, llm)

    failed = client.post(
        f"/api/interview-sessions/{session['id']}/improvements/retry",
        headers=headers,
    )
    stored = db_session.get(InterviewSession, session["id"])
    assert failed.status_code == 502
    assert stored.status == "completed"
    assert stored.improvement_status == "failed"
    assert db_session.query(AgentRun).filter_by(
        session_id=session["id"], agent_name="improvement", status="error"
    ).count() == 1

    recovered = client.post(
        f"/api/interview-sessions/{session['id']}/improvements/retry",
        headers=headers,
    )
    assert recovered.status_code == 200
    assert recovered.json()["generated"] is True
    task_count = db_session.query(ImprovementTask).filter_by(
        session_id=session["id"]
    ).count()

    repeated = client.post(
        f"/api/interview-sessions/{session['id']}/improvements/retry",
        headers=headers,
    )
    assert repeated.status_code == 200
    assert repeated.json()["generated"] is False
    assert db_session.query(ImprovementTask).filter_by(
        session_id=session["id"]
    ).count() == task_count
    assert llm.improvement_calls == 3


def test_automatic_generation_failure_does_not_rollback_completion(
    client,
    db_session,
    monkeypatch,
):
    llm = ImprovementFlowLLM(["invalid json", "still invalid"])
    install_flow(monkeypatch, llm)
    headers, user_id = register_and_login(client, "alice")
    interview_session, turn = prepare_in_progress_session(
        client,
        db_session,
        headers,
        user_id,
    )

    response = client.post(
        f"/api/interview-sessions/{interview_session.id}/answer",
        headers=headers,
        json={"turn_id": turn.id, "answer": "我按真实情况说明技术取舍。"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["improvement_status"] == "failed"
    stored = db_session.get(InterviewSession, interview_session.id)
    assert stored.overall_score is not None
    assert db_session.query(ImprovementTask).filter_by(
        session_id=interview_session.id
    ).count() == 0


def test_user_cannot_retry_other_users_improvements(
    client,
    db_session,
):
    alice_headers, alice_id = register_and_login(client, "alice")
    bob_headers, _ = register_and_login(client, "bob")
    session = create_session(client, alice_headers)
    add_scored_turn(db_session, alice_id, session["id"])
    mark_completed_with_score(
        db_session,
        session["id"],
        {"overall": 74, "dimensions": DIMENSIONS},
    )

    response = client.post(
        f"/api/interview-sessions/{session['id']}/improvements/retry",
        headers=bob_headers,
    )

    assert response.status_code == 404


def test_retry_session_copies_scope_but_not_turns(client, db_session):
    headers, user_id = register_and_login(client, "alice")
    job = client.post(
        "/api/target-jobs",
        headers=headers,
        json={
            "job_title": "Backend Engineer",
            "company_name": "Example",
            "jd_text": "Build backend systems.",
            "notes": "",
            "is_active": True,
        },
    ).json()
    now = datetime.now().isoformat(timespec="seconds")
    project = FileRecord(
        user_id=user_id,
        file_id="project-file",
        filename="project.txt",
        file_type="txt",
        file_path="/tmp/project.txt",
        category="project",
        status="uploaded",
        created_at=now,
        updated_at=now,
    )
    db_session.add(project)
    db_session.commit()
    source = create_session(
        client,
        headers,
        mode="deep_dive",
        target_job_id=job["id"],
        selected_project_file_ids=[project.file_id],
    )
    turn = add_scored_turn(db_session, user_id, source["id"])
    mark_completed_with_score(
        db_session,
        source["id"],
        {"overall": 74, "dimensions": DIMENSIONS},
    )
    first_task = create_improvement_task(
        db_session,
        user_id,
        source["id"],
        turn_id=turn.id,
        title="补充技术取舍",
        description="练习技术决策表达",
        completion_criteria="完成一次口述",
        category="technical",
        priority="high",
    )
    client.patch(
        f"/api/improvement-tasks/{first_task.id}",
        headers=headers,
        json={"status": "completed"},
    )
    create_improvement_task(
        db_session,
        user_id,
        source["id"],
        title="补充回答深度",
        description="练习完整回答",
        category="answer_depth",
        priority="medium",
    )

    response = client.post(
        f"/api/interview-sessions/{source['id']}/retry",
        headers=headers,
    )

    assert response.status_code == 201
    retry = response.json()
    assert retry["status"] == "draft"
    assert retry["previous_session"]["id"] == source["id"]
    assert retry["mode"] == "deep_dive"
    assert retry["target_job"]["id"] == job["id"]
    assert retry["selected_project_file_ids"] == [project.file_id]
    assert "再次练习" in retry["title"]
    assert retry["previous_task_count"] == 2
    assert retry["completed_task_count"] == 1
    assert retry["task_completion_rate"] == 50.0
    assert db_session.query(InterviewTurn).filter_by(
        session_id=retry["id"]
    ).count() == 0


def test_retry_requires_own_completed_session(client, db_session):
    alice_headers, _ = register_and_login(client, "alice")
    bob_headers, _ = register_and_login(client, "bob")
    draft = create_session(client, alice_headers)
    assert client.post(
        f"/api/interview-sessions/{draft['id']}/retry",
        headers=alice_headers,
    ).status_code == 409
    mark_completed_with_score(
        db_session,
        draft["id"],
        {"overall": 74, "dimensions": DIMENSIONS},
    )
    assert client.post(
        f"/api/interview-sessions/{draft['id']}/retry",
        headers=bob_headers,
    ).status_code == 404


def test_retry_plan_uses_strategy_as_guidance(client, db_session, monkeypatch):
    llm = ImprovementFlowLLM()
    install_flow(monkeypatch, llm)
    headers, user_id = register_and_login(client, "alice")
    source = create_session(client, headers)
    mark_completed_with_score(
        db_session,
        source["id"],
        {"overall": 74, "dimensions": DIMENSIONS},
    )
    stored = db_session.get(InterviewSession, source["id"])
    stored.next_round_strategy = "优先训练技术决策，不作为个人事实"
    db_session.commit()
    create_improvement_task(
        db_session,
        user_id,
        source["id"],
        title="明确个人职责",
        description="按真实经历练习",
        completion_criteria="清楚区分个人与团队职责",
        category="project_evidence",
        priority="high",
    )
    retry = client.post(
        f"/api/interview-sessions/{source['id']}/retry",
        headers=headers,
    ).json()

    started = client.post(
        f"/api/interview-sessions/{retry['id']}/start",
        headers=headers,
    )

    runs = db_session.query(AgentRun).filter_by(session_id=retry["id"]).all()
    assert started.status_code == 200, (
        started.text,
        [(run.agent_name, run.status, run.error) for run in runs],
        llm.calls,
    )
    assert "优先训练技术决策" in llm.plan_messages[0]
    assert "明确个人职责" in llm.plan_messages[0]
    assert started.json()["evidence_limited"] is True


def test_comparison_calculates_deltas_categories_and_task_rate(
    client,
    db_session,
):
    headers, user_id = register_and_login(client, "alice")
    previous = create_session(client, headers)
    previous_turn = add_scored_turn(db_session, user_id, previous["id"])
    previous_dimensions = dict(DIMENSIONS)
    mark_completed_with_score(
        db_session,
        previous["id"],
        {"overall": 70, "dimensions": previous_dimensions},
    )
    tasks = [
        create_improvement_task(
            db_session,
            user_id,
            previous["id"],
            turn_id=previous_turn.id,
            title=f"对比任务 {index}",
            description="训练任务",
            category="technical",
            priority="medium",
        )
        for index in range(2)
    ]
    client.patch(
        f"/api/improvement-tasks/{tasks[0].id}",
        headers=headers,
        json={"status": "completed"},
    )
    retry = client.post(
        f"/api/interview-sessions/{previous['id']}/retry",
        headers=headers,
    ).json()
    current_dimensions = dict(previous_dimensions)
    current_dimensions["technical_accuracy_score"] = 85.0
    current_dimensions["answer_depth_score"] = 55.0
    mark_completed_with_score(
        db_session,
        retry["id"],
        {"overall": 75, "dimensions": current_dimensions},
    )

    response = client.get(
        f"/api/interview-sessions/{retry['id']}/comparison",
        headers=headers,
    )

    assert response.status_code == 200
    comparison = response.json()
    assert comparison["comparable"] is True
    assert comparison["overall_delta"] == 5.0
    assert comparison["dimension_deltas"]["technical_accuracy_score"] == 5.0
    assert comparison["dimension_deltas"]["answer_depth_score"] == -5.0
    assert "technical_accuracy_score" in comparison["improved_dimensions"]
    assert "answer_depth_score" in comparison["regressed_dimensions"]
    assert "job_match_score" in comparison["unchanged_dimensions"]
    assert comparison["previous_task_count"] == 2
    assert comparison["completed_task_count"] == 1
    assert comparison["task_completion_rate"] == 50.0
    assert "不是严格的同题实验" in comparison["note"]
    detail = client.get(
        f"/api/interview-sessions/{retry['id']}",
        headers=headers,
    ).json()
    assert detail["comparison_available"] is True


def test_comparison_reports_missing_scores_and_is_user_isolated(
    client,
    db_session,
):
    alice_headers, _ = register_and_login(client, "alice")
    bob_headers, _ = register_and_login(client, "bob")
    previous = create_session(client, alice_headers)
    mark_completed_with_score(
        db_session,
        previous["id"],
        {"overall": 70, "dimensions": DIMENSIONS},
    )
    retry = client.post(
        f"/api/interview-sessions/{previous['id']}/retry",
        headers=alice_headers,
    ).json()
    mark_completed_with_score(db_session, retry["id"], None)

    missing = client.get(
        f"/api/interview-sessions/{retry['id']}/comparison",
        headers=alice_headers,
    )
    forbidden = client.get(
        f"/api/interview-sessions/{retry['id']}/comparison",
        headers=bob_headers,
    )

    assert missing.status_code == 200
    assert missing.json()["comparable"] is False
    assert "缺少总分" in missing.json()["reason"]
    assert forbidden.status_code == 404


def test_task_filters_source_summary_status_and_unknown_fields(
    client,
    db_session,
):
    headers, user_id = register_and_login(client, "alice")
    session = create_session(client, headers)
    turn = add_scored_turn(db_session, user_id, session["id"])
    task = create_improvement_task(
        db_session,
        user_id,
        session["id"],
        turn_id=turn.id,
        title="高优先级任务",
        description="练习技术表达",
        completion_criteria="完成一次结构化回答",
        category="technical",
        priority="high",
    )

    listed = client.get(
        "/api/improvement-tasks?priority=high&category=technical",
        headers=headers,
    )
    assert [item["id"] for item in listed.json()["tasks"]] == [task.id]
    assert listed.json()["tasks"][0]["source_turn"]["id"] == turn.id
    assert listed.json()["tasks"][0]["completion_criteria"]

    completed = client.patch(
        f"/api/improvement-tasks/{task.id}",
        headers=headers,
        json={"status": "completed"},
    ).json()
    assert completed["completed_at"] is not None
    pending = client.patch(
        f"/api/improvement-tasks/{task.id}",
        headers=headers,
        json={"status": "pending"},
    ).json()
    assert pending["completed_at"] is None
    assert client.patch(
        f"/api/improvement-tasks/{task.id}",
        headers=headers,
        json={"status": "completed", "user_id": 999, "score": 100},
    ).status_code == 422


def test_new_endpoints_require_authentication(client):
    assert client.post(
        "/api/interview-sessions/1/improvements/retry"
    ).status_code == 401
    assert client.post("/api/interview-sessions/1/retry").status_code == 401
    assert client.get(
        "/api/interview-sessions/1/comparison"
    ).status_code == 401


def test_improvement_agent_second_invalid_response_is_controlled():
    agent = ImprovementAgent(lambda messages: "not json")
    with pytest.raises(StructuredLLMError):
        agent.generate(improvement_input())
