from collections.abc import Sequence


COMMON_FACT_RULES: tuple[str, ...] = (
    "不得编造用户职责、成果、指标、公司、项目或技术细节。",
    "证据不足时必须明确指出不足，不得用流畅表达掩盖事实缺失。",
    "岗位要求只能用于判断匹配度，不能证明用户具备相应经历或能力。",
    "用户原始陈述、资料证据和模型生成内容具有不同可信等级，不得混用。",
)


def build_system_prompt(
    *,
    role: str,
    objective: str,
    allowed_facts: Sequence[str],
    fact_priority: Sequence[str],
    prohibitions: Sequence[str],
    current_goal: str,
    output_format: str,
    failure_handling: str,
) -> str:
    sections = (
        ("角色", (role,)),
        ("任务目标", (objective,)),
        ("允许使用的事实", allowed_facts),
        ("事实优先级", fact_priority),
        ("禁止事项", (*COMMON_FACT_RULES, *prohibitions)),
        ("当前唯一目标", (current_goal,)),
        ("输出格式", (output_format,)),
        ("失败处理", (failure_handling,)),
    )
    return "\n\n".join(
        f"## {title}\n" + "\n".join(f"- {item}" for item in items)
        for title, items in sections
    )
