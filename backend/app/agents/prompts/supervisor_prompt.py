import json

from app.agents.schemas import InterviewPlanInput, SupervisorDecisionInput

SUPERVISOR_PROMPT_VERSION = "interview-supervisor-v1.0.0"

SUPERVISOR_SYSTEM_PROMPT = """
你是面试流程 Supervisor Agent。你只负责制定计划和决定流程走向。
你不能访问数据库或向量库，不能假设候选人拥有输入中未出现的经历。
你不负责生成具体题目，不负责评分。
计划必须遵守服务端给出的主问题数量。
决策只能是 follow_up、next_main_question 或 complete。
仅当回答过于简略、缺少技术细节、未说明个人职责或与证据存在明显张力时追问。
追问不是强制动作。
""".strip()


def build_plan_messages(payload: InterviewPlanInput) -> list[dict]:
    return [
        {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请制定本场面试计划：" + json.dumps(
                payload.model_dump(),
                ensure_ascii=False,
            ),
        },
    ]


def build_decision_messages(payload: SupervisorDecisionInput) -> list[dict]:
    return [
        {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请判断下一步流程：" + payload.model_dump_json(),
        },
    ]
