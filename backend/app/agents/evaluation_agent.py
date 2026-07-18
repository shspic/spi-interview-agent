import re
from collections.abc import Callable

from app.agents.prompts.evaluation_prompt import (
    EVALUATION_PROMPT_VERSION,
    build_evaluation_messages,
)
from app.agents.schemas import EvaluationInput, EvaluationOutput
from app.agents.structured_llm import invoke_structured

NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?%?")


class EvaluationAgent:
    name = "evaluation"
    prompt_version = EVALUATION_PROMPT_VERSION

    def __init__(self, llm_call: Callable[[list[dict]], str] | None = None):
        self.llm_call = llm_call

    def evaluate(self, payload: EvaluationInput) -> EvaluationOutput:
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
        allowed_numbers = set(
            NUMBER_PATTERN.findall(f"{payload.answer}\n{evidence_text}")
        )

        def validate_result(result: EvaluationOutput) -> None:
            referenced_ids = set(result.evidence_source_ids)
            for conflict in result.evidence_conflicts:
                referenced_ids.update(conflict.evidence_source_ids)
            unknown_ids = referenced_ids - allowed_user_sources
            if unknown_ids:
                raise ValueError("评价引用了不存在或非用户证据来源")
            added_numbers = (
                set(NUMBER_PATTERN.findall(result.optimized_answer))
                - allowed_numbers
            )
            if added_numbers:
                raise ValueError("优化回答新增了无证据数字")
            for claim in result.unsupported_claims:
                normalized_claim = claim.strip()
                if len(normalized_claim) >= 4 and normalized_claim in result.optimized_answer:
                    raise ValueError("优化回答仍包含已识别的无依据内容")
            if result.evidence_conflicts and not result.has_evidence_conflict:
                raise ValueError("资料冲突标记与冲突列表不一致")

        return invoke_structured(
            build_evaluation_messages(payload),
            EvaluationOutput,
            self.llm_call,
            semantic_validator=validate_result,
        )
