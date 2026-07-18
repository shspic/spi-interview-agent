from collections.abc import Callable

from app.agents.prompts.supervisor_prompt import (
    SUPERVISOR_PROMPT_VERSION,
    build_decision_messages,
    build_plan_messages,
)
from app.agents.schemas import (
    InterviewPlanInput,
    InterviewPlanOutput,
    SupervisorDecisionInput,
    SupervisorDecisionOutput,
)
from app.agents.structured_llm import invoke_structured


class SupervisorAgent:
    name = "supervisor"
    prompt_version = SUPERVISOR_PROMPT_VERSION

    def __init__(self, llm_call: Callable[[list[dict]], str] | None = None):
        self.llm_call = llm_call

    def create_plan(self, payload: InterviewPlanInput) -> InterviewPlanOutput:
        result = invoke_structured(
            build_plan_messages(payload),
            InterviewPlanOutput,
            self.llm_call,
        )
        return result.model_copy(
            update={"planned_main_questions": payload.planned_main_questions}
        )

    def decide(
        self,
        payload: SupervisorDecisionInput,
    ) -> SupervisorDecisionOutput:
        result = invoke_structured(
            build_decision_messages(payload),
            SupervisorDecisionOutput,
            self.llm_call,
        )
        action = result.action
        reason = result.reason
        if action == "follow_up" and payload.current_follow_up_count >= 2:
            action = (
                "complete"
                if payload.current_main_question >= payload.planned_main_questions
                else "next_main_question"
            )
            reason = "已达到两次追问上限，按计划推进"
        elif action == "complete" and (
            payload.current_main_question < payload.planned_main_questions
        ):
            action = "next_main_question"
            reason = "尚未完成计划主问题数量，继续下一主问题"
        elif action == "next_main_question" and (
            payload.current_main_question >= payload.planned_main_questions
        ):
            action = "complete"
            reason = "已完成计划主问题数量"
        return SupervisorDecisionOutput(action=action, reason=reason)
