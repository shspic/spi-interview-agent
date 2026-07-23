import re
from collections.abc import Callable

from app.agents.interview_context import build_evaluation_context
from app.agents.prompts.evaluation_prompt import (
    EVALUATION_PROMPT_VERSION,
    build_evaluation_messages,
)
from app.agents.schemas import EvaluationInput, EvaluationOutput
from app.agents.structured_llm import invoke_structured
from app.core.config import settings
from app.services.prompt_injection_guard import validate_agent_output_texts

NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?%?")
IMPORTANT_ASCII_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9+.#_-]{2,}")
QUOTED_NAME_PATTERN = re.compile(r"[“\"《]([^”\"》]{2,40})[”\"》]")
IMPORTANT_ASCII_ALLOWLIST = {"star"}
KNOWN_TECH_TOKENS = {
    "chromadb",
    "django",
    "docker",
    "elasticsearch",
    "fastapi",
    "flask",
    "kafka",
    "kubernetes",
    "mongodb",
    "mysql",
    "postgresql",
    "pytorch",
    "rabbitmq",
    "redis",
    "spark",
    "tensorflow",
}
CONSERVATIVE_QUALIFIERS = (
    "未找到支持证据",
    "没有支持证据",
    "无法确认",
    "不能确认",
    "需要核实",
    "需要确认",
    "待核实",
    "待确认",
    "仅为声明",
    "声称",
)


def _is_important_ascii_token(token: str) -> bool:
    normalized = token.casefold()
    return (
        normalized in KNOWN_TECH_TOKENS
        or any(character.isdigit() or character in "+.#_-" for character in token)
        or (token.isupper() and len(token) >= 3)
        or any(character.isupper() for character in token[1:])
    )


def _claim_is_conservatively_qualified(claim: str, text: str) -> bool:
    for sentence in re.split(r"[。！？.!?；;\n]", text):
        if claim in sentence and any(
            qualifier in sentence for qualifier in CONSERVATIVE_QUALIFIERS
        ):
            return True
    return False


def find_added_important_facts(
    *,
    answer: str,
    evidence_text: str,
    optimized_answer: str,
) -> set[str]:
    allowed_fact_text = f"{answer}\n{evidence_text}"
    added: set[str] = {
        f"number:{value}"
        for value in (
            set(NUMBER_PATTERN.findall(optimized_answer))
            - set(NUMBER_PATTERN.findall(allowed_fact_text))
        )
    }
    allowed_ascii_tokens = {
        token.casefold()
        for token in IMPORTANT_ASCII_PATTERN.findall(allowed_fact_text)
    } | IMPORTANT_ASCII_ALLOWLIST
    added.update(
        f"token:{token.casefold()}"
        for token in IMPORTANT_ASCII_PATTERN.findall(optimized_answer)
        if _is_important_ascii_token(token)
        and token.casefold() not in allowed_ascii_tokens
    )
    allowed_quoted_names = set(QUOTED_NAME_PATTERN.findall(allowed_fact_text))
    added.update(
        f"name:{name}"
        for name in QUOTED_NAME_PATTERN.findall(optimized_answer)
        if name not in allowed_quoted_names
    )
    return added


class EvaluationAgent:
    name = "evaluation"
    prompt_version = EVALUATION_PROMPT_VERSION

    def __init__(self, llm_call: Callable[[list[dict]], str] | None = None):
        self.llm_call = llm_call

    def evaluate(self, payload: EvaluationInput) -> EvaluationOutput:
        context = build_evaluation_context(
            payload,
            budget_chars=settings.interview_context_char_budget,
        )
        allowed_user_sources = {
            item.source_id
            for item in [
                *payload.evidence.profile_evidence,
                *payload.evidence.project_evidence,
                *payload.evidence.resume_evidence,
            ]
        }
        evidence_text = "\n".join(
            item.content
            for item in [
                *payload.evidence.profile_evidence,
                *payload.evidence.project_evidence,
                *payload.evidence.resume_evidence,
            ]
        )
        def validate_result(result: EvaluationOutput) -> None:
            result.evidence_source_ids = [
                context.reference_map.get(source_id, source_id)
                for source_id in result.evidence_source_ids
            ]
            for conflict in result.evidence_conflicts:
                conflict.evidence_source_ids = [
                    context.reference_map.get(source_id, source_id)
                    for source_id in conflict.evidence_source_ids
                ]
            validate_agent_output_texts(
                [
                    result.evaluation_summary,
                    result.optimized_answer,
                    result.modification_reason,
                    *result.unsupported_claims,
                    *result.strengths,
                    *(problem.description for problem in result.problems),
                    *(problem.suggestion for problem in result.problems),
                    *(conflict.claim for conflict in result.evidence_conflicts),
                    *(conflict.explanation for conflict in result.evidence_conflicts),
                ],
                agent_name=self.name,
            )
            referenced_ids = set(result.evidence_source_ids)
            for conflict in result.evidence_conflicts:
                referenced_ids.update(conflict.evidence_source_ids)
            unknown_ids = referenced_ids - allowed_user_sources
            if unknown_ids:
                raise ValueError("评价引用了不存在或非用户证据来源")
            added_facts = find_added_important_facts(
                answer=payload.answer,
                evidence_text=evidence_text,
                optimized_answer=result.optimized_answer,
            )
            if added_facts:
                raise ValueError("优化回答新增了无证据关键事实")
            for claim in result.unsupported_claims:
                normalized_claim = claim.strip()
                if (
                    len(normalized_claim) >= 4
                    and normalized_claim in result.optimized_answer
                    and not _claim_is_conservatively_qualified(
                        normalized_claim,
                        result.optimized_answer,
                    )
                ):
                    raise ValueError("优化回答仍包含已识别的无依据内容")
            if result.evidence_conflicts and not result.has_evidence_conflict:
                raise ValueError("资料冲突标记与冲突列表不一致")

        return invoke_structured(
            build_evaluation_messages(payload, context=context),
            EvaluationOutput,
            self.llm_call,
            semantic_validator=validate_result,
        )
