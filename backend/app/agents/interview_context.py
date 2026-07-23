import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.agents.question_progression import INTENT_LABELS
from app.agents.schemas import EvaluationInput, ImprovementInput, InterviewerInput
from app.services.prompt_injection_guard import sanitize_untrusted_payload


CONTEXT_VERSION = "interview_context_v1"
MISSING_EVIDENCE = "未找到支持证据"
_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[，。！？；：、,.!?;:…—\-~·“”‘’\"'（）()\[\]【】<>《》]+")


@dataclass(frozen=True)
class InterviewContext:
    payload: dict[str, Any]
    reference_map: dict[str, str]

    @property
    def char_count(self) -> int:
        return len(json.dumps(self.payload, ensure_ascii=False, separators=(",", ":")))


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = _PUNCTUATION.sub(" ", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()


def _section(
    name: str,
    priority: int,
    trust: str,
    content: Any,
) -> dict[str, Any]:
    return {
        "name": name,
        "priority": priority,
        "trust": trust,
        "content": content,
    }


class _BudgetedSections:
    def __init__(self, budget_chars: int, mandatory: list[dict[str, Any]]):
        self.budget_chars = budget_chars
        self.sections = list(mandatory)
        self.omitted_items = 0

    def _serialized_length(self, sections: list[dict[str, Any]]) -> int:
        payload = {
            "context_version": CONTEXT_VERSION,
            "budget_chars": self.budget_chars,
            "truncated": False,
            "omitted_items": 0,
            "sections": sections,
        }
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    def add_items(
        self,
        *,
        name: str,
        priority: int,
        trust: str,
        items: list[Any],
        empty_value: Any | None = None,
        preserve_empty: bool = False,
    ) -> list[Any]:
        kept: list[Any] = []
        for item in items:
            candidate_content: Any = [*kept, item]
            candidate = [
                *self.sections,
                _section(name, priority, trust, candidate_content),
            ]
            if self._serialized_length(candidate) <= self.budget_chars:
                kept.append(item)
            else:
                self.omitted_items += 1
        content = kept if kept else empty_value
        if content is None:
            return []
        candidate = [*self.sections, _section(name, priority, trust, content)]
        if self._serialized_length(candidate) <= self.budget_chars or (
            preserve_empty and not items
        ):
            self.sections = candidate
            return kept
        elif items:
            self.omitted_items += len(kept)
        return []

    def build(self) -> dict[str, Any]:
        serialized_length = self._serialized_length(self.sections)
        return {
            "context_version": CONTEXT_VERSION,
            "budget_chars": self.budget_chars,
            "truncated": self.omitted_items > 0 or serialized_length > self.budget_chars,
            "mandatory_over_budget": serialized_length > self.budget_chars,
            "omitted_items": self.omitted_items,
            "sections": self.sections,
        }


def _deduplicate_evidence(
    payload: Any,
    *,
    agent_name: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    groups = (
        ("profile", "profile", payload.profile_evidence),
        ("project", "project", payload.project_evidence),
        ("resume", "resume", payload.resume_evidence),
        ("jd", "job_requirement", payload.job_requirements),
    )
    counters: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    evidence: list[dict[str, Any]] = []
    reference_map: dict[str, str] = {}
    for prefix, evidence_type, items in groups:
        for item in items:
            safe_content = sanitize_untrusted_payload(
                item.content,
                agent_name=agent_name,
            )
            trust_group = "job" if evidence_type == "job_requirement" else "user"
            key = (trust_group, _normalize(safe_content))
            if not key[1] or key in seen:
                continue
            seen.add(key)
            counters[prefix] = counters.get(prefix, 0) + 1
            reference_id = f"{prefix}_{counters[prefix]}"
            reference_map[reference_id] = item.source_id
            evidence.append(
                {
                    "ref": reference_id,
                    "type": evidence_type,
                    "content": safe_content,
                }
            )
    return evidence, reference_map


def _split_evidence(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    user_evidence = [item for item in items if item["type"] != "job_requirement"]
    job_requirements = [item for item in items if item["type"] == "job_requirement"]
    return user_evidence, job_requirements


def _history_items(safe_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    items: list[dict[str, Any]] = []
    for index, history in enumerate(safe_history, start=1):
        key = (_normalize(history["question"]), _normalize(history["answer"] or ""))
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "ref": f"turn_{index}",
                "question": {
                    "trust": "model_generated",
                    "text": history["question"],
                },
                "answer": {
                    "trust": "user_claim",
                    "text": history["answer"] or "未回答",
                },
                "evaluation": {
                    "trust": "model_generated",
                    "summary": history["evaluation_summary"] or "暂无评价",
                    "conflicts": history["evidence_conflicts"],
                },
            }
        )
    return items


def build_interviewer_context(
    payload: InterviewerInput,
    *,
    budget_chars: int,
) -> InterviewContext:
    safe = sanitize_untrusted_payload(payload.model_dump(), agent_name="interviewer")
    evidence, reference_map = _deduplicate_evidence(
        payload.evidence,
        agent_name="interviewer",
    )
    user_evidence, job_requirements = _split_evidence(evidence)
    history = _history_items(safe["history"])
    recent_history = history[-4:]
    older_history = history[:-4]
    current_exchange = {
        "question": {
            "trust": "model_generated",
            "text": safe["previous_question"] or "尚无上一题",
        },
        "answer": {
            "trust": "user_claim",
            "text": safe["current_answer"] or "尚无当前回答",
        },
    }
    goal = {
        "action": safe["action"],
        "intent": payload.target_intent,
        "description": INTENT_LABELS[payload.target_intent],
        "covered_intents": safe["covered_intents"],
        "follow_up_reason": safe["follow_up_reason"] or "无",
    }
    mandatory = [
        _section("current_exchange", 100, "mixed", current_exchange),
        _section("current_unique_goal", 100, "system_controlled", goal),
    ]
    builder = _BudgetedSections(budget_chars, mandatory)
    kept_user_evidence = builder.add_items(
        name="verified_user_evidence",
        priority=90,
        trust="verified_user_source",
        items=user_evidence,
        empty_value=(
            "存在用户证据，但因上下文预算未载入"
            if user_evidence
            else MISSING_EVIDENCE
        ),
        preserve_empty=True,
    )
    builder.add_items(
        name="confirmed_fact_refs",
        priority=85,
        trust="verified_user_source",
        items=[item["ref"] for item in kept_user_evidence],
        empty_value=(
            "存在用户证据，但因上下文预算未载入"
            if user_evidence
            else MISSING_EVIDENCE
        ),
        preserve_empty=True,
    )
    builder.add_items(
        name="job_requirements",
        priority=80,
        trust="job_requirement_not_user_fact",
        items=job_requirements,
        empty_value=(
            "存在岗位要求，但因上下文预算未载入"
            if job_requirements
            else MISSING_EVIDENCE
        ),
        preserve_empty=True,
    )
    current_evaluation = []
    if safe["previous_evaluation"]:
        current_evaluation.append(safe["previous_evaluation"])
    builder.add_items(
        name="current_evaluation_and_conflicts",
        priority=70,
        trust="model_generated",
        items=current_evaluation,
        empty_value="暂无上一轮评价",
    )
    builder.add_items(
        name="asked_questions",
        priority=65,
        trust="model_generated",
        items=[
            {"ref": f"asked_{index}", "question": question}
            for index, question in reversed(
                list(enumerate(safe["asked_questions"], start=1))
            )
        ],
        empty_value="暂无已问题目",
    )
    builder.add_items(
        name="recent_history",
        priority=60,
        trust="mixed",
        items=list(reversed(recent_history)),
        empty_value="暂无历史",
    )
    builder.add_items(
        name="older_history",
        priority=40,
        trust="mixed",
        items=list(reversed(older_history)),
    )
    builder.add_items(
        name="interview_plan",
        priority=30,
        trust="model_generated_guidance",
        items=[safe["plan"]],
    )
    return InterviewContext(builder.build(), reference_map)


def build_evaluation_context(
    payload: EvaluationInput,
    *,
    budget_chars: int,
) -> InterviewContext:
    safe = sanitize_untrusted_payload(payload.model_dump(), agent_name="evaluation")
    evidence, reference_map = _deduplicate_evidence(
        payload.evidence,
        agent_name="evaluation",
    )
    user_evidence, job_requirements = _split_evidence(evidence)
    mandatory = [
        _section(
            "current_exchange",
            100,
            "user_claim",
            {"question": safe["question"], "answer": safe["answer"]},
        ),
        _section(
            "current_unique_goal",
            100,
            "system_controlled",
            "只评价当前回答并给出有证据边界的优化回答",
        ),
    ]
    builder = _BudgetedSections(budget_chars, mandatory)
    kept_user_evidence = builder.add_items(
        name="verified_user_evidence",
        priority=90,
        trust="verified_user_source",
        items=user_evidence,
        empty_value=(
            "存在用户证据，但因上下文预算未载入"
            if user_evidence
            else MISSING_EVIDENCE
        ),
        preserve_empty=True,
    )
    builder.add_items(
        name="confirmed_fact_refs",
        priority=85,
        trust="verified_user_source",
        items=[item["ref"] for item in kept_user_evidence],
        empty_value=(
            "存在用户证据，但因上下文预算未载入"
            if user_evidence
            else MISSING_EVIDENCE
        ),
        preserve_empty=True,
    )
    builder.add_items(
        name="job_requirements",
        priority=80,
        trust="job_requirement_not_user_fact",
        items=job_requirements,
        empty_value=(
            "存在岗位要求，但因上下文预算未载入"
            if job_requirements
            else MISSING_EVIDENCE
        ),
        preserve_empty=True,
    )
    return InterviewContext(builder.build(), reference_map)


def build_improvement_context(
    payload: ImprovementInput,
    *,
    budget_chars: int,
) -> InterviewContext:
    safe = sanitize_untrusted_payload(payload.model_dump(), agent_name="improvement")
    mandatory = [
        _section(
            "current_unique_goal",
            100,
            "system_controlled",
            "仅依据既有评价生成下一轮训练策略和不重复的改进任务",
        ),
        _section(
            "session_scores",
            90,
            "model_generated_evaluation",
            {
                "mode": safe["mode"],
                "overall_score": safe["overall_score"],
                "dimension_scores": safe["dimension_scores"],
            },
        ),
    ]
    builder = _BudgetedSections(budget_chars, mandatory)
    target_job = []
    if safe["target_job_title"] or safe["target_company_name"]:
        target_job.append(
            {
                "job_title": safe["target_job_title"],
                "company_name": safe["target_company_name"],
            }
        )
    builder.add_items(
        name="job_target",
        priority=80,
        trust="job_requirement_not_user_fact",
        items=target_job,
        empty_value=MISSING_EVIDENCE,
    )
    turns = []
    seen_turns: set[str] = set()
    for turn in reversed(safe["turns"]):
        key = _normalize(json.dumps(turn, ensure_ascii=False, sort_keys=True))
        if key in seen_turns:
            continue
        seen_turns.add(key)
        turns.append(turn)
    builder.add_items(
        name="recent_evaluations",
        priority=70,
        trust="model_generated_evaluation",
        items=turns,
    )
    existing_tasks = []
    seen_tasks: set[tuple[str, str, Any]] = set()
    for task in safe["existing_tasks"]:
        key = (
            _normalize(task["title"]),
            task["category"],
            task["source_turn_id"],
        )
        if key in seen_tasks:
            continue
        seen_tasks.add(key)
        existing_tasks.append(task)
    builder.add_items(
        name="existing_tasks",
        priority=60,
        trust="model_generated_guidance",
        items=existing_tasks,
        empty_value="暂无已有任务",
    )
    return InterviewContext(builder.build(), {})
