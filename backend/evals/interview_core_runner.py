import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.agents.evaluation_agent import find_added_important_facts
from app.agents.interview_context import (
    MISSING_EVIDENCE,
    build_interviewer_context,
)
from app.agents.prompts.evaluation_prompt import EVALUATION_PROMPT_VERSION
from app.agents.prompts.improvement_prompt import IMPROVEMENT_PROMPT_VERSION
from app.agents.prompts.interviewer_prompt import INTERVIEWER_PROMPT_VERSION
from app.agents.question_progression import (
    build_fallback_question,
    find_duplicate_question,
    infer_question_intents,
    select_target_intent,
)
from app.agents.schemas import (
    EvaluationOutput,
    EvidenceItem,
    EvidenceOutput,
    InterviewHistoryItem,
    InterviewPlanOutput,
    InterviewerInput,
)
from evals.interview_core_cases import INTERVIEW_CORE_CASES


@dataclass
class EvalMetrics:
    total: int = 0
    passed: int = 0
    failed: int = 0
    schema_checks: int = 0
    schema_matches: int = 0
    unsupported_fact_violations: int = 0
    question_checks: int = 0
    duplicate_violations: int = 0
    progression_checks: int = 0
    progression_passed: int = 0
    evidence_checks: int = 0
    evidence_covered: int = 0
    fallback_uses: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        def rate(numerator: int, denominator: int) -> float:
            return round(100 * numerator / denominator, 2) if denominator else 100.0

        return {
            "total_cases": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "schema_compliance_rate": rate(self.schema_matches, self.schema_checks),
            "unsupported_fact_violations": self.unsupported_fact_violations,
            "question_duplicate_rate": rate(
                self.duplicate_violations,
                self.question_checks,
            ),
            "follow_up_progression_rate": rate(
                self.progression_passed,
                self.progression_checks,
            ),
            "evidence_coverage_rate": rate(
                self.evidence_covered,
                self.evidence_checks,
            ),
            "fallback_uses": self.fallback_uses,
            "failures": self.failures,
        }


def _evidence(*, duplicate: bool = False, empty: bool = False) -> EvidenceOutput:
    project_items = []
    if not empty:
        project_items.append(
            EvidenceItem(
                evidence_type="project",
                source_id="synthetic-project-a",
                content="用户负责检索模块并检查日志。",
            )
        )
        if duplicate:
            project_items.append(
                EvidenceItem(
                    evidence_type="project",
                    source_id="synthetic-project-b",
                    content="  用户负责检索模块并检查日志！ ",
                )
            )
    return EvidenceOutput(
        is_sufficient=bool(project_items),
        reason="合成证据",
        best_distance=0.2 if project_items else None,
        sources=project_items,
        context="合成上下文",
        profile_evidence=[],
        project_evidence=project_items,
        resume_evidence=[],
        job_requirements=[
            EvidenceItem(
                evidence_type="job_requirement",
                source_id="synthetic-job-a",
                content="岗位要求后端工程经验。",
            )
        ],
    )


def _interviewer_input(*, duplicate: bool = False, empty: bool = False) -> InterviewerInput:
    histories = [
        InterviewHistoryItem(
            main_question_number=index + 1,
            follow_up_number=0,
            question=f"较早的合成问题 {index + 1}",
            answer=f"较早的合成回答 {index + 1}",
            evaluation_summary="合成评价摘要",
        )
        for index in range(8)
    ]
    return InterviewerInput(
        action="follow_up",
        mode="standard",
        main_question_number=2,
        plan=InterviewPlanOutput(
            planned_main_questions=3,
            focus_areas=["项目经历"],
            strategy="逐步获取真实事实",
            opening_focus="项目背景",
        ),
        evidence=_evidence(duplicate=duplicate, empty=empty),
        history=histories,
        asked_questions=[item.question for item in histories],
        current_answer="这是必须完整保留的当前回答。",
        target_intent="personal_responsibility",
        previous_question="这是必须完整保留的当前问题。",
    )


def _section(context: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in context["sections"] if item["name"] == name)


def _run_context_case(case: dict[str, Any]) -> tuple[bool, str]:
    check = case["assertions"]["check"]
    if check == "prompt_versions":
        versions = {
            INTERVIEWER_PROMPT_VERSION,
            EVALUATION_PROMPT_VERSION,
            IMPROVEMENT_PROMPT_VERSION,
        }
        return versions == {"interviewer_v2", "evaluator_v2", "improvement_v2"}, str(versions)

    duplicate = check == "evidence_deduplication"
    empty = check == "trust_and_missing"
    budget = 1300 if check == "budget_priority" else 12000
    if check == "current_preserved":
        budget = 1000
    context = build_interviewer_context(
        _interviewer_input(duplicate=duplicate, empty=empty),
        budget_chars=budget,
    ).payload
    names = [item["name"] for item in context["sections"]]
    if check == "section_order":
        priorities = [item["priority"] for item in context["sections"]]
        return priorities == sorted(priorities, reverse=True), str(priorities)
    if check == "evidence_deduplication":
        content = _section(context, "verified_user_evidence")["content"]
        return isinstance(content, list) and len(content) == 1, str(content)
    if check == "budget_priority":
        return (
            context["truncated"]
            and "current_exchange" in names
            and "current_unique_goal" in names
            and "older_history" not in names
        ), json.dumps(context, ensure_ascii=False)
    if check == "current_preserved":
        current = _section(context, "current_exchange")["content"]
        return (
            current["question"]["text"] == "这是必须完整保留的当前问题。"
            and current["answer"]["text"] == "这是必须完整保留的当前回答。"
        ), str(current)
    if check == "trust_and_missing":
        current = _section(context, "current_exchange")
        evidence = _section(context, "verified_user_evidence")
        return (
            current["content"]["answer"]["trust"] == "user_claim"
            and evidence["content"] == MISSING_EVIDENCE
        ), f"{current} {evidence}"
    return False, f"未知 context check: {check}"


def _run_question_case(case: dict[str, Any], metrics: EvalMetrics) -> tuple[bool, str]:
    data = case["input_context"]
    assertions = case["assertions"]
    metrics.question_checks += 1
    if "expected_duplicate" in assertions:
        duplicate = find_duplicate_question(data["candidate"], data["asked"])
        passed = (duplicate is not None) == assertions["expected_duplicate"]
        if not passed:
            metrics.duplicate_violations += 1
        return passed, f"duplicate={duplicate!r}"
    if assertions.get("select_target"):
        selected = select_target_intent("follow_up", data["asked"])
        metrics.progression_checks += 1
        passed = selected == assertions["expected_target"]
        metrics.progression_passed += int(passed)
        return passed, f"selected={selected}"
    if "fallback_target" in assertions:
        question, intent = build_fallback_question(
            assertions["fallback_target"],
            data["asked"],
        )
        metrics.fallback_uses += 1
        passed = find_duplicate_question(question, data["asked"]) is None
        return passed, f"intent={intent}, question={question}"
    intents = infer_question_intents(data["candidate"])
    passed = intents == {assertions["expected_intent"]}
    return passed, f"intents={sorted(intents)}"


def _candidate_output(case: dict[str, Any]) -> dict[str, Any]:
    assertions = case["assertions"]
    score = assertions.get("min_score", assertions.get("max_score", 60))
    output = {
        "technical_accuracy_score": score,
        "evidence_consistency_score": score,
        "answer_depth_score": score,
        "expression_structure_score": score,
        "job_match_score": score,
        "evaluation_summary": (
            "未找到支持证据，需要按真实经历核实。"
            if assertions.get("conservative")
            else "基于当前回答和合成证据的评价。"
        ),
        "problems": [],
        "optimized_answer": assertions.get("optimized_answer", "合成优化回答。"),
        "modification_reason": "仅重组已有事实。",
        "has_evidence_conflict": assertions.get("has_conflict", False),
        "evidence_conflicts": (
            [
                {
                    "claim": "合成冲突声明",
                    "conflict_type": "contradiction",
                    "explanation": "与合成资料不一致。",
                    "evidence_source_ids": ["project_1"],
                }
            ]
            if assertions.get("has_conflict")
            else []
        ),
        "evidence_source_ids": assertions.get("evidence_refs", []),
        "unsupported_claims": assertions.get("unsupported", []),
        "strengths": [],
    }
    if assertions.get("invalid_schema"):
        output.pop("evaluation_summary")
    return output


def _run_evaluation_case(case: dict[str, Any], metrics: EvalMetrics) -> tuple[bool, str]:
    assertions = case["assertions"]
    candidate = _candidate_output(case)
    metrics.schema_checks += 1
    try:
        EvaluationOutput.model_validate(candidate)
        schema_valid = True
    except ValidationError:
        schema_valid = False
    expected_schema_valid = not assertions.get("invalid_schema", False)
    schema_match = schema_valid == expected_schema_valid
    metrics.schema_matches += int(schema_match)
    if not schema_match:
        return False, f"schema_valid={schema_valid}"
    if not schema_valid:
        return True, "无效 Schema 已被正确拒绝"

    data = case["input_context"]
    added = find_added_important_facts(
        answer=data.get("answer", ""),
        evidence_text=data.get("evidence", ""),
        optimized_answer=assertions["optimized_answer"],
    )
    expected_added = assertions.get("expect_added_fact", False)
    if bool(added) != expected_added:
        metrics.unsupported_fact_violations += 1
        return False, f"added_facts={sorted(added)}"
    if assertions.get("has_conflict") and not candidate["has_evidence_conflict"]:
        return False, "未标记预期冲突"
    if assertions.get("conservative"):
        combined = candidate["evaluation_summary"] + candidate["optimized_answer"]
        if not any(word in combined for word in ("证据", "核实", "补充", "不足", "需要")):
            return False, "缺少保守表达"
    if "evidence_refs" in assertions:
        metrics.evidence_checks += 1
        covered = bool(candidate["evidence_source_ids"]) == bool(assertions["evidence_refs"])
        metrics.evidence_covered += int(covered)
        if not covered:
            return False, "证据引用覆盖不符合预期"
    return True, f"added_facts={sorted(added)}"


def run_offline_evaluations() -> EvalMetrics:
    metrics = EvalMetrics(total=len(INTERVIEW_CORE_CASES))
    for case in INTERVIEW_CORE_CASES:
        try:
            if case["operation"] == "context":
                passed, detail = _run_context_case(case)
            elif case["operation"] == "question":
                passed, detail = _run_question_case(case, metrics)
            else:
                passed, detail = _run_evaluation_case(case, metrics)
        except Exception as exc:  # 评测入口必须报告单案例错误并继续
            passed, detail = False, f"{type(exc).__name__}: {exc}"
        if passed:
            metrics.passed += 1
        else:
            metrics.failed += 1
            metrics.failures.append({"id": case["id"], "reason": detail[:300]})
    return metrics
