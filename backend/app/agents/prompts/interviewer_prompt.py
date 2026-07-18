from app.agents.schemas import InterviewerInput

INTERVIEWER_PROMPT_VERSION = "interview-interviewer-v1.0.0"

INTERVIEWER_SYSTEM_PROMPT = """
你是 Interviewer Agent。你只负责生成一个主问题或一个追问，不负责评分。
问题应围绕项目经历、技术实现、架构设计、问题排查、个人职责和目标岗位。
只能把 project_evidence、resume_evidence 和 profile_evidence 作为候选人经历依据。
job_requirements 只能作为岗位要求，不能证明候选人具备某项能力。
不得把证据中不存在的项目、职责、成果或技术栈写成既定事实。
问题必须清晰、单一、可回答。
""".strip()


def build_interviewer_messages(payload: InterviewerInput) -> list[dict]:
    return [
        {"role": "system", "content": INTERVIEWER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请生成下一道面试问题：" + payload.model_dump_json(),
        },
    ]
