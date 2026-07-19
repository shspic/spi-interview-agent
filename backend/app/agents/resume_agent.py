import re
from collections.abc import Callable

from app.agents.prompts.resume_prompt import (
    RESUME_PROMPT_VERSION,
    build_resume_messages,
)
from app.agents.schemas import ResumeGenerationInput, ResumeGenerationOutput
from app.agents.structured_llm import invoke_structured

NUMBER_PATTERN = re.compile(r"(?<![\d.])[+-]?\d+(?:\.\d+)?%?")


class ResumeAgent:
    name = "resume"
    prompt_version = RESUME_PROMPT_VERSION

    def __init__(self, llm_call: Callable[[list[dict]], str] | None = None):
        self.llm_call = llm_call

    def generate(self, payload: ResumeGenerationInput) -> ResumeGenerationOutput:
        allowed_source_ids = {
            item.source_id
            for item in [
                *payload.project_evidence,
                *payload.resume_evidence,
                *payload.profile_evidence,
            ]
        }
        trusted_text = self._trusted_text(payload)
        allowed_numbers = set(NUMBER_PATTERN.findall(trusted_text))
        forbidden_claims = self._forbidden_claims(payload)

        def validate(result: ResumeGenerationOutput) -> None:
            invalid_source_ids = set(result.evidence_source_ids) - allowed_source_ids
            if invalid_source_ids:
                raise ValueError("evidence_source_ids 引用了不存在的证据")

            formal_text = self._formal_text(result)
            normalized_formal_text = self._normalize(formal_text)
            for claim in forbidden_claims:
                normalized_claim = self._normalize(claim)
                if normalized_claim and normalized_claim in normalized_formal_text:
                    raise ValueError("正式描述包含无依据或冲突内容")

            new_numbers = set(NUMBER_PATTERN.findall(formal_text)) - allowed_numbers
            if new_numbers:
                raise ValueError("正式描述包含无证据数字或百分比")

            normalized_trusted_text = self._normalize(trusted_text)
            for technology in result.technical_stack:
                if self._normalize(technology) not in normalized_trusted_text:
                    raise ValueError("technical_stack 包含无证据技术栈")
            for statement in [*result.responsibilities, *result.outcomes]:
                if self._normalize(statement) not in normalized_trusted_text:
                    raise ValueError("职责或成果缺少事实证据")

            if not payload.evidence_is_sufficient and not result.warnings:
                raise ValueError("资料不足时必须返回 warnings")

        return invoke_structured(
            build_resume_messages(payload),
            ResumeGenerationOutput,
            self.llm_call,
            semantic_validator=validate,
        )

    @staticmethod
    def _trusted_text(payload: ResumeGenerationInput) -> str:
        evidence_text = [
            item.content
            for item in [
                *payload.project_evidence,
                *payload.resume_evidence,
                *payload.profile_evidence,
            ]
        ]
        interview_text = [
            value
            for turn in payload.interview_turns
            for value in [turn.optimized_answer, *turn.strengths]
        ]
        file_names = [item.filename for item in payload.project_files]
        return "\n".join([*evidence_text, *interview_text, *file_names])

    @staticmethod
    def _forbidden_claims(payload: ResumeGenerationInput) -> list[str]:
        return [
            claim
            for turn in payload.interview_turns
            for claim in [
                *turn.unsupported_claims,
                *(conflict.claim for conflict in turn.evidence_conflicts),
            ]
        ]

    @staticmethod
    def _formal_text(result: ResumeGenerationOutput) -> str:
        return "\n".join(
            [
                result.project_name,
                result.one_line_summary,
                *result.concise_bullets,
                result.detailed_description,
                *result.technical_stack,
                *result.responsibilities,
                *result.challenges,
                *result.solutions,
                *result.outcomes,
                *result.interview_talking_points,
            ]
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(
            character
            for character in value.casefold()
            if character.isalnum()
        )
