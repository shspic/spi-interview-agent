from openai import OpenAI

from app.core.config import settings


class LLMServiceError(Exception):
    pass


def get_deepseek_client() -> OpenAI:
    if not settings.deepseek_api_key:
        raise LLMServiceError("缺少 DEEPSEEK_API_KEY，请检查 backend/.env")

    return OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )


def chat_completion(
    user_message: str,
    system_message: str = "你是一个严谨的 AI 应用开发助手。",
) -> str:
    if not user_message.strip():
        raise LLMServiceError("user_message 不能为空")

    client = get_deepseek_client()

    try:
        response = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {
                    "role": "system",
                    "content": system_message,
                },
                {
                    "role": "user",
                    "content": user_message,
                },
            ],
            temperature=0.3,
        )

        content = response.choices[0].message.content

        if not content:
            raise LLMServiceError("模型返回内容为空")

        return content

    except Exception as exc:
        raise LLMServiceError(f"DeepSeek 调用失败：{exc}") from exc
    
def chat_with_messages(messages: list[dict]) -> str:
    client = get_deepseek_client()

    try:
        response = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            temperature=0.3,
        )

        content = response.choices[0].message.content

        if not content:
            raise LLMServiceError("模型返回内容为空")

        return content

    except Exception as exc:
        raise LLMServiceError(f"DeepSeek 调用失败：{exc}") from exc