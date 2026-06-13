def build_interview_question_messages(
    interview_type: str,
    job_description: str,
    context: str,
    question_index: int,
) -> list[dict]:
    system_message = """
你是一个严谨的 AI 实习模拟面试官。

你必须遵守以下规则：
1. 面试问题必须结合岗位 JD 和本地知识库上下文。
2. 涉及用户经历、项目、技能时，只能基于本地知识库，不得编造。
3. 问题要适合 AI 应用开发、RAG、FastAPI、前后端联调、项目经历等实习面试场景。
4. 每次只生成 1 个问题。
5. 不要直接给答案。
"""

    user_message = f"""
【面试类型】
{interview_type}

【当前题号】
第 {question_index} 题

【岗位 JD】
{job_description}

【本地知识库上下文】
{context}

请生成 1 个模拟面试问题。

输出格式：

# 模拟面试题

问题：...
考察点：...
回答提示：...
"""

    return [
        {"role": "system", "content": system_message.strip()},
        {"role": "user", "content": user_message.strip()},
    ]


def build_interview_evaluation_messages(
    interview_type: str,
    job_description: str,
    question: str,
    user_answer: str,
    context: str,
) -> list[dict]:
    system_message = """
你是一个严格但实用的 AI 实习面试评价官。

你必须遵守以下规则：
1. 只基于岗位 JD、本地知识库和用户回答进行评价。
2. 不得编造用户没有说过的经历。
3. 如果用户回答中有夸大、空泛、逻辑断裂，要明确指出。
4. 评分要偏严格，适合真实实习面试准备。
5. 必须只输出 JSON，不要输出 Markdown，不要使用代码块。
"""

    user_message = f"""
【面试类型】
{interview_type}

【岗位 JD】
{job_description}

【面试问题】
{question}

【用户回答】
{user_answer}

【本地知识库上下文】
{context}

请按照下面 JSON 结构输出评价结果：

{{
  "score_total": 0,
  "content_relevance": 0,
  "personal_match": 0,
  "technical_accuracy": 0,
  "structure_score": 0,
  "risk_control": 0,
  "main_problems": "主要问题说明",
  "suggestions": "改进建议",
  "reference_answer": "参考回答"
}}

评分说明：
- score_total：总分，0 到 100
- content_relevance：内容相关性，0 到 20
- personal_match：个人经历匹配度，0 到 20
- technical_accuracy：技术准确性，0 到 20
- structure_score：表达结构，0 到 20
- risk_control：风险控制，0 到 20
"""

    return [
        {"role": "system", "content": system_message.strip()},
        {"role": "user", "content": user_message.strip()},
    ]