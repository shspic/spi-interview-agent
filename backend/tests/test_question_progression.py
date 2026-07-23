import json
from itertools import combinations

from app.agents.interviewer_agent import InterviewerAgent
from app.agents.question_progression import (
    all_fallback_questions,
    build_fallback_question,
    normalize_question,
    question_rejection_reason,
    questions_are_similar,
    select_target_intent,
)
from app.agents.prompts.interviewer_prompt import build_interviewer_messages
from app.agents.schemas import (
    EvidenceItem,
    EvidenceOutput,
    InterviewHistoryItem,
    InterviewPlanOutput,
    InterviewerInput,
    SupervisorEvaluationSummary,
)


def _evidence(*, sufficient: bool = True) -> EvidenceOutput:
    item = EvidenceItem(
        evidence_type="project",
        source_id="project:1",
        content="用户负责后台任务可靠性，并参与技术方案评审。",
        distance=0.2,
    )
    return EvidenceOutput(
        is_sufficient=sufficient,
        reason="测试证据",
        best_distance=0.2 if sufficient else None,
        sources=[item] if sufficient else [],
        context=item.content if sufficient else "",
        profile_evidence=[],
        project_evidence=[item] if sufficient else [],
        resume_evidence=[],
        job_requirements=[],
    )


def _payload(**overrides) -> InterviewerInput:
    values = {
        "action": "follow_up",
        "mode": "deep_dive",
        "main_question_number": 1,
        "plan": InterviewPlanOutput(
            planned_main_questions=1,
            focus_areas=["项目深挖"],
            strategy="逐步核验真实经历",
            opening_focus="项目背景",
        ),
        "evidence": _evidence(),
        "asked_questions": ["请说明这段真实经历的项目背景。"],
        "current_answer": "我参与了这个项目。",
        "covered_intents": ["project_background"],
        "target_intent": "personal_responsibility",
    }
    values.update(overrides)
    return InterviewerInput(**values)


class QuestionLLM:
    def __init__(self, questions: list[str]):
        self.questions = list(questions)
        self.calls = 0
        self.messages: list[list[dict]] = []

    def __call__(self, messages: list[dict]) -> str:
        self.calls += 1
        self.messages.append(messages)
        question = self.questions.pop(0)
        return json.dumps(
            {
                "question": question,
                "rationale": "测试问题",
                "evidence_limited": False,
            },
            ensure_ascii=False,
        )


def test_question_normalization_ignores_spacing_and_punctuation():
    left = "  请说明  你的个人职责， 以及结果。 "
    right = "请说明 你的个人职责,以及结果!"

    assert normalize_question(left) == normalize_question(right)
    assert questions_are_similar(left, right) is True


def test_highly_similar_question_is_detected():
    assert questions_are_similar(
        "请说明你个人负责的部分和关键技术决策。",
        "请具体说明你个人负责的部分与关键技术决策。",
    ) is True


def test_vague_answers_advance_from_responsibility_to_decision_and_result():
    asked_questions: list[str] = []

    first_intent = select_target_intent("follow_up", asked_questions, "回答仍然模糊")
    first_question, _ = build_fallback_question(first_intent, asked_questions)
    asked_questions.append(first_question)
    second_intent = select_target_intent("follow_up", asked_questions, "回答仍然模糊")
    second_question, _ = build_fallback_question(second_intent, asked_questions)
    asked_questions.append(second_question)
    third_intent = select_target_intent("follow_up", asked_questions, "回答仍然模糊")

    assert [first_intent, second_intent, third_intent] == [
        "personal_responsibility",
        "technical_decision",
        "verifiable_result",
    ]


def test_covered_responsibility_is_not_selected_again():
    target = select_target_intent(
        "follow_up",
        ["在这个项目中，哪些工作由你亲自负责？请说明个人职责。"],
        "个人职责仍然不清楚",
    )

    assert target == "technical_decision"


def test_duplicate_generation_retries_once_and_accepts_new_question():
    duplicate = "请说明这段真实经历的项目背景。"
    llm = QuestionLLM(
        [duplicate, "在这段经历中，哪些工作由你亲自负责？"],
    )

    result = InterviewerAgent(llm).generate_question(_payload())

    assert llm.calls == 2
    assert result.question != duplicate
    assert "唯一一次重试" in llm.messages[1][-2]["content"]
    assert "个人职责和责任边界" in llm.messages[1][-2]["content"]


def test_second_duplicate_uses_other_dimension_fallback_without_more_calls():
    duplicate = "请说明这段真实经历的项目背景。"
    llm = QuestionLLM([duplicate, duplicate])

    result = InterviewerAgent(llm).generate_question(
        _payload(target_intent="technical_decision"),
    )

    assert llm.calls == 2
    assert result.question != duplicate
    assert "技术选择" in result.question
    assert "模型两次生成重复或不符合目标的问题" in result.rationale


def test_off_target_or_composite_question_is_rejected():
    reason = question_rejection_reason(
        "你具体承担了哪些任务？遇到的最大技术挑战是什么？",
        target_intent="personal_responsibility",
        asked_questions=[],
        evidence_text="候选人参与后台任务系统开发。",
    )

    assert reason is not None
    assert "多个问句" in reason


def test_unsupported_quoted_project_name_is_rejected():
    reason = question_rejection_reason(
        "请说明你在“功率放大器线性化项目”中的项目背景。",
        target_intent="project_background",
        asked_questions=[],
        evidence_text="候选人参与后台任务系统开发。",
    )

    assert reason == "问题把用户证据中不存在的名称写成了既定事实"


def test_non_chinese_question_retries_once_then_uses_target_fallback():
    llm = QuestionLLM(
        [
            "Расскажите о вашей роли в проекте?",
            "Расскажите о вашей роли в проекте?",
        ]
    )

    result = InterviewerAgent(llm).generate_question(_payload())

    assert llm.calls == 2
    assert "亲自负责" in result.question


def test_all_deterministic_fallbacks_are_pairwise_distinct():
    questions = all_fallback_questions()

    assert len(questions) >= 15
    assert len(questions) == len(set(questions))
    assert all(
        not questions_are_similar(left, right)
        for left, right in combinations(questions, 2)
    )


def test_insufficient_evidence_fallback_uses_progressive_target_without_llm():
    llm = QuestionLLM([])

    result = InterviewerAgent(llm).generate_question(
        _payload(evidence=_evidence(sufficient=False), target_intent="verifiable_result"),
    )

    assert llm.calls == 0
    assert "如何被验证" in result.question
    assert result.evidence_limited is True


def test_prompt_contains_history_evidence_evaluation_coverage_and_single_target():
    payload = _payload(
        history=[
            InterviewHistoryItem(
                main_question_number=1,
                follow_up_number=0,
                question="请说明这段真实经历的项目背景。",
                answer="我参与了这个项目。",
                evaluation_summary="个人职责仍不清晰。",
                evidence_conflicts=[{"claim": "负责全部模块"}],
            )
        ],
        previous_evaluation=SupervisorEvaluationSummary(
            technical_accuracy_score=70,
            evidence_consistency_score=60,
            answer_depth_score=40,
            has_evidence_conflict=True,
            evaluation_summary="个人职责仍不清晰。",
        ),
    )

    content = build_interviewer_messages(payload)[1]["content"]

    assert '"name": "recent_history"' in content
    assert "我参与了这个项目" in content
    assert '"name": "verified_user_evidence"' in content
    assert "个人职责仍不清晰" in content
    assert "负责全部模块" in content
    assert '"covered_intents"' in content
    assert '"name": "current_unique_goal"' in content
    assert "个人职责和责任边界" in content
