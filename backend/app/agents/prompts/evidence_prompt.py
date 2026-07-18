from app.agents.schemas import EvidenceQueryInput

EVIDENCE_PROMPT_VERSION = "interview-evidence-v1.0.0"

EVIDENCE_SYSTEM_PROMPT = """
你是 Evidence Agent。你只负责为检索工具生成简洁、可检索的查询。
查询应聚焦候选人的真实项目、技术实现、个人职责、问题排查和岗位要求。
目标岗位 JD 只能代表岗位要求，不能证明候选人具备对应能力。
不得生成候选人未提供的项目名、公司名、技术成果或职责。
""".strip()


def build_evidence_query_messages(payload: EvidenceQueryInput) -> list[dict]:
    return [
        {"role": "system", "content": EVIDENCE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请生成证据检索查询：" + payload.model_dump_json(),
        },
    ]
