from collections.abc import Callable

from app.agents.interview_context import build_interviewer_context
from app.agents.prompts.interviewer_prompt import (
    INTERVIEWER_PROMPT_VERSION,
    build_interviewer_messages,
)
from app.agents.question_progression import (
    INTENT_LABELS,
    build_fallback_question,
    question_rejection_reason,
)
from app.agents.schemas import InterviewerInput, InterviewerOutput
from app.agents.structured_llm import invoke_structured
from app.core.config import settings


class InterviewerAgent:
    name = "interviewer"
    prompt_version = INTERVIEWER_PROMPT_VERSION

    def __init__(self, llm_call: Callable[[list[dict]], str] | None = None):
        self.llm_call = llm_call

    @staticmethod
    def _rejection_reason(
        result: InterviewerOutput,
        payload: InterviewerInput,
    ) -> str | None:
        evidence_text = "\n".join(
            item.content
            for item in [
                *payload.evidence.profile_evidence,
                *payload.evidence.project_evidence,
                *payload.evidence.resume_evidence,
            ]
        )
        return question_rejection_reason(
            result.question,
            target_intent=payload.target_intent,
            asked_questions=payload.asked_questions,
            evidence_text=evidence_text,
        )

    def generate_question(self, payload: InterviewerInput) -> InterviewerOutput:
        if not payload.evidence.is_sufficient:
            question, fallback_intent = build_fallback_question(
                payload.target_intent,
                payload.asked_questions,
            )
            return InterviewerOutput(
                question=question,
                rationale=(
                    "可靠项目证据不足，使用不预设经历且聚焦"
                    f"{INTENT_LABELS[fallback_intent]}的确定性问题"
                ),
                evidence_limited=True,
            )

        context = build_interviewer_context(
            payload,
            budget_chars=settings.interview_context_char_budget,
        )
        result = invoke_structured(
            build_interviewer_messages(payload, context=context),
            InterviewerOutput,
            self.llm_call,
        )
        rejection_reason = self._rejection_reason(result, payload)
        if rejection_reason is None:
            return result.model_copy(update={"evidence_limited": False})

        retry_result = invoke_structured(
            build_interviewer_messages(
                payload,
                rejected_question=result.question,
                rejection_reason=rejection_reason,
                context=context,
            ),
            InterviewerOutput,
            self.llm_call,
        )
        if self._rejection_reason(retry_result, payload) is None:
            return retry_result.model_copy(update={"evidence_limited": False})

        fallback_question, fallback_intent = build_fallback_question(
            payload.target_intent,
            payload.asked_questions,
        )
        return InterviewerOutput(
            question=fallback_question,
            rationale=(
                "模型两次生成重复或不符合目标的问题，改用聚焦"
                f"{INTENT_LABELS[fallback_intent]}的确定性问题"
            ),
            evidence_limited=False,
        )
