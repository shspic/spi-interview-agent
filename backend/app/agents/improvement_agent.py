from collections.abc import Callable

from app.agents.prompts.improvement_prompt import (
    IMPROVEMENT_PROMPT_VERSION,
    build_improvement_messages,
)
from app.agents.schemas import ImprovementInput, ImprovementOutput
from app.agents.structured_llm import invoke_structured


class ImprovementAgent:
    name = "improvement"
    prompt_version = IMPROVEMENT_PROMPT_VERSION

    def __init__(self, llm_call: Callable[[list[dict]], str] | None = None):
        self.llm_call = llm_call

    def generate(self, payload: ImprovementInput) -> ImprovementOutput:
        allowed_turn_ids = {turn.turn_id for turn in payload.turns}
        existing_keys = {
            self._task_key(task.title, task.category, task.source_turn_id)
            for task in payload.existing_tasks
        }

        def validate(result: ImprovementOutput) -> None:
            generated_keys = set()
            for task in result.tasks:
                if (
                    task.source_turn_id is not None
                    and task.source_turn_id not in allowed_turn_ids
                ):
                    raise ValueError("source_turn_id 不属于当前会话")
                key = self._task_key(
                    task.title,
                    task.category,
                    task.source_turn_id,
                )
                if key in existing_keys or key in generated_keys:
                    raise ValueError("改进任务与已有任务重复")
                generated_keys.add(key)

        return invoke_structured(
            build_improvement_messages(payload),
            ImprovementOutput,
            self.llm_call,
            semantic_validator=validate,
        )

    @staticmethod
    def _task_key(
        title: str,
        category: str,
        source_turn_id: int | None,
    ) -> tuple[str, str, int | None]:
        return (" ".join(title.split()).casefold(), category, source_turn_id)
