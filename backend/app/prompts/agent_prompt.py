def build_agent_answer_messages(
    question: str,
    route: str,
    local_context: str = "",
    web_context: str = "",
) -> list[dict]:
    system_message = """
你是一个严谨的 AI 实习求职 Agent。

你可以使用两类信息：
1. 本地知识库：来自用户上传的个人资料、项目资料、技术笔记。
2. 联网搜索结果：来自 Tavily，用于补充当前岗位市场信息、技术趋势、招聘要求。

必须遵守：
1. 涉及用户个人经历、项目经历、技能掌握情况时，只能依据本地知识库。
2. 联网搜索结果只能用于说明市场要求、岗位趋势、技术关键词，不能证明用户已经具备某项能力。
3. 如果本地知识库依据不足，必须明确说明“当前本地知识库依据不足，不能确认”。
4. 不要编造用户没有上传过的经历、项目成果、实习经历、获奖经历。
5. 回答要适合用户准备 AI 应用开发、RAG、FastAPI、LangGraph、Agent 等方向的实习面试。
"""

    local_section = (
        f"""
【本地知识库上下文】
{local_context}
"""
        if local_context
        else """
【本地知识库上下文】
未检索到可用的本地知识库内容。
"""
    )

    web_section = (
        f"""
【联网搜索结果】
{web_context}
"""
        if web_context
        else """
【联网搜索结果】
本次未使用联网搜索，或未检索到可用联网结果。
"""
    )

    user_message = f"""
【用户问题】
{question}

【Agent 路由】
{route}

{local_section}

{web_section}

请输出结构清晰的回答。

如果问题是求职、岗位、面试、简历相关，请优先按照以下结构回答：

## 1. 结论
直接回答用户问题。

## 2. 本地知识库依据
说明有哪些内容来自用户本地资料；如果依据不足，明确说明。

## 3. 联网搜索补充
如果使用了联网搜索，说明联网结果补充了什么；如果没有使用，说明未使用。

## 4. 建议下一步
给出用户接下来应该怎么做。
"""

    return [
        {"role": "system", "content": system_message.strip()},
        {"role": "user", "content": user_message.strip()},
    ]