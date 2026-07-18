from collections.abc import Callable

from app.agents.prompts.interviewer_prompt import (
    INTERVIEWER_PROMPT_VERSION,
    build_interviewer_messages,
)
from app.agents.schemas import InterviewerInput, InterviewerOutput
from app.agents.structured_llm import invoke_structured


class InterviewerAgent:
    name = "interviewer"
    prompt_version = INTERVIEWER_PROMPT_VERSION

    def __init__(self, llm_call: Callable[[list[dict]], str] | None = None):
        self.llm_call = llm_call

    def generate_question(self, payload: InterviewerInput) -> InterviewerOutput:
        if not payload.evidence.is_sufficient:
            if payload.action == "follow_up":
                question = (
                    "请只基于你的真实经历，进一步说明你个人负责的部分、"
                    "关键技术决策以及最终结果。"
                )
            else:
                question = (
                    "请介绍一个与你目标岗位相关的真实项目，并说明你个人负责的"
                    "部分、关键技术决策和问题解决过程。"
                )
            return InterviewerOutput(
                question=question,
                rationale="可靠项目证据不足，使用不预设经历的开放问题",
                evidence_limited=True,
            )

        result = invoke_structured(
            build_interviewer_messages(payload),
            InterviewerOutput,
            self.llm_call,
        )
        return result.model_copy(update={"evidence_limited": False})
