def build_rag_chat_messages(question: str, context: str) -> list[dict]:
    system_message = """
你是一个严谨的 AI 实习面试训练助手。

你必须遵守以下规则：
1. 优先基于提供的【本地知识库上下文】回答。
2. 如果上下文不足以确认个人经历、项目经历、实习经历、技能掌握程度，必须明确说明“当前知识库依据不足，不能编造”。
3. 不要把通用知识包装成用户自己的经历。
4. 回答要适合面试场景，结构清晰，表达自然。
5. 如果能回答，请给出“推荐回答”“依据来源”“可能追问”“风险提示”。
"""

    user_message = f"""
【用户问题】
{question}

【本地知识库上下文】
{context}

请按照下面格式回答：

## 1. 推荐回答
...

## 2. 回答依据
...

## 3. 可能追问
1. ...
2. ...

## 4. 回答风险提示
...
"""

    return [
        {"role": "system", "content": system_message.strip()},
        {"role": "user", "content": user_message.strip()},
    ]