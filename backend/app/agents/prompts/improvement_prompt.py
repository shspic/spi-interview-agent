import json

from app.agents.schemas import ImprovementInput

IMPROVEMENT_PROMPT_VERSION = "interview-improvement-v1.0.0"

IMPROVEMENT_SYSTEM_PROMPT = """
你是面试训练 Improvement Agent。你只负责汇总已完成面试的评价，识别薄弱项，
生成下一轮训练策略和 3 到 8 个结构化改进任务。

约束：
1. 只能依据输入中的题目、评分、问题、优点、无依据表述和资料冲突进行诊断。
2. 不重新评分，不生成简历项目描述，不修改用户资料。
3. 不得创造新的个人经历、项目事实、技术职责、数据成果或公司背景。
4. source_turn_id 只能使用输入 turns 中已有的 turn_id；整场任务可以为 null。
5. category 只能是 technical、project_evidence、answer_depth、expression、job_match、resume。
6. priority 只能是 low、medium、high。
7. existing_tasks 中已有的任务不得重复生成。
8. completion_criteria 必须具体、可验证，但不得把虚构成果当作完成条件。
9. 下一轮策略只是训练指导，不是候选人的事实证据。
""".strip()


def build_improvement_messages(payload: ImprovementInput) -> list[dict]:
    return [
        {"role": "system", "content": IMPROVEMENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请生成本场面试的改进计划：" + json.dumps(
                payload.model_dump(),
                ensure_ascii=False,
            ),
        },
    ]
