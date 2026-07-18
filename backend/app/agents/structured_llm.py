import json
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.services.llm_service import LLMServiceError, chat_with_messages

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class StructuredLLMError(Exception):
    pass


def invoke_structured(
    messages: list[dict],
    output_model: type[OutputModel],
    llm_call: Callable[[list[dict]], str] | None = None,
) -> OutputModel:
    call = llm_call or chat_with_messages
    schema = json.dumps(
        output_model.model_json_schema(),
        ensure_ascii=False,
    )
    schema_message = {
        "role": "user",
        "content": (
            "只返回一个完整 JSON 对象，不要使用 Markdown。JSON 必须严格满足："
            f"{schema}"
        ),
    }
    request_messages = [*messages, schema_message]
    last_error = "未知结构错误"

    for attempt in range(2):
        try:
            raw_result = call(request_messages)
            parsed = json.loads(raw_result)
            return output_model.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError, LLMServiceError) as exc:
            last_error = str(exc)
            if attempt == 0:
                request_messages = [
                    *request_messages,
                    {
                        "role": "user",
                        "content": "上一次输出结构无效。请重新输出严格匹配 JSON Schema 的对象。",
                    },
                ]

    raise StructuredLLMError(f"模型连续两次未返回合法结构：{last_error}")
