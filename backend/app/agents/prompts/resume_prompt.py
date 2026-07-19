import json

from app.agents.schemas import ResumeGenerationInput

RESUME_PROMPT_VERSION = "interview-resume-v1.0.0"

RESUME_SYSTEM_PROMPT = """
你是 Resume Agent，只负责根据结构化证据和已完成面试评价生成项目描述。

输出要求：
1. 精简版必须包含 3 到 4 条简洁要点，适合一页简历。
2. 详细版覆盖项目背景、核心功能、技术架构、个人职责、难点和解决方案。
3. 只能使用 project_evidence、resume_evidence、profile_evidence，以及面试中已经评价并优化的回答。
4. target_job 和 job_requirements 只能调整表达方向，不能证明用户掌握某项技能。
5. ImprovementTask、训练策略和改进建议不是事实证据，不得使用。
6. 不得创造不存在的项目经历、个人职责、技术栈、用户量、百分比、性能提升或业务成果。
7. unsupported_claims 和 evidence_conflicts 中的内容不得写成事实。
8. 资料不足、需要确认或不应写入简历的内容必须放入 warnings，不得放入正式描述。
9. evidence_source_ids 只能引用输入的 project_evidence、resume_evidence 或 profile_evidence 的 source_id。
10. 技术栈、职责和成果缺少证据时应省略，不能根据 JD 补齐。
""".strip()


def build_resume_messages(payload: ResumeGenerationInput) -> list[dict]:
    return [
        {"role": "system", "content": RESUME_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请生成真实、可核验的简历项目描述：" + json.dumps(
                payload.model_dump(),
                ensure_ascii=False,
            ),
        },
    ]
