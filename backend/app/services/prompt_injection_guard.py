import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)

RISK_INSTRUCTION_OVERRIDE = "instruction_override"
RISK_ROLE_ESCALATION = "role_escalation"
RISK_PROMPT_EXFILTRATION = "prompt_exfiltration"
RISK_CROSS_USER_REQUEST = "cross_user_request"
RISK_SCORE_MANIPULATION = "score_manipulation"
RISK_EVIDENCE_BYPASS = "evidence_bypass"
RISK_RESUME_FABRICATION = "resume_fabrication_request"

UNTRUSTED_CONTENT_PLACEHOLDER = "[检测到不受信指令，已从事实材料中移除]"

_ZERO_WIDTH_PATTERN = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_SEPARATOR_PATTERN = re.compile(r"[\s\W_]+", re.UNICODE)
_SAFE_CONTEXT_PATTERN = re.compile(
    r"(?:防止|防范|防护|检测|识别|阻止|过滤|抵御|讨论|描述|说明|示例|演示|攻击|"
    r"detect|prevent|block|filter|defend|describe|discuss|example|attack)"
    r".{0,24}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GuardResult:
    sanitized_text: str
    risk_types: tuple[str, ...]
    blocked_count: int

    @property
    def is_unsafe(self) -> bool:
        return bool(self.risk_types)


class UnsafeAgentOutputError(ValueError):
    def __init__(self, risk_types: set[str] | tuple[str, ...]):
        self.risk_types = tuple(sorted(risk_types))
        super().__init__("生成结果未通过安全校验")


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _ZERO_WIDTH_PATTERN.sub("", normalized)


def _compact(value: str) -> str:
    return _SEPARATOR_PATTERN.sub("", _normalize(value))


def _is_safe_technical_context(normalized: str, match_start: int) -> bool:
    prefix = normalized[max(0, match_start - 40):match_start]
    prefix = re.split(r"[。！？.!?；;\n]", prefix)[-1]
    return bool(_SAFE_CONTEXT_PATTERN.search(prefix))


def _match_risk(
    normalized: str,
    compact: str,
    pattern: str,
    compact_pattern: str | None = None,
) -> bool:
    match = re.search(pattern, normalized, re.IGNORECASE | re.DOTALL)
    if match and not _is_safe_technical_context(normalized, match.start()):
        return True
    if compact_pattern:
        for clause in re.split(r"[。！？.!?；;\n]", normalized):
            compact_clause = _compact(clause)
            if re.search(compact_pattern, compact_clause, re.IGNORECASE):
                if not _SAFE_CONTEXT_PATTERN.search(clause):
                    return True
        if re.search(compact_pattern, compact, re.IGNORECASE):
            if not any(
                _SAFE_CONTEXT_PATTERN.search(clause)
                for clause in re.split(r"[。！？.!?；;\n]", normalized)
                if re.search(compact_pattern, _compact(clause), re.IGNORECASE)
            ):
                return True
    return False


def detect_prompt_injection(value: str) -> set[str]:
    normalized = _normalize(value)
    compact = _compact(value)
    risks: set[str] = set()

    checks = (
        (
            RISK_INSTRUCTION_OVERRIDE,
            r"(?:忽略|无视|绕过|覆盖|跳过).{0,24}(?:之前|先前|上面|系统|开发者).{0,16}(?:指令|提示词|要求)|"
            r"ignore.{0,40}(?:previous|prior|system|developer).{0,24}(?:instructions?|prompts?)",
            r"(?:忽略|无视|绕过|覆盖|跳过)(?:之前|先前|上面|系统|开发者).{0,12}(?:指令|提示词|要求)|"
            r"ignore(?:previous|prior|system|developer).{0,16}(?:instructions?|prompts?)",
        ),
        (
            RISK_ROLE_ESCALATION,
            r"(?:你现在是|现在你是|请扮演|请充当|切换为).{0,20}(?:管理员|系统|超级用户)|"
            r"(?:act as|you are now|switch to).{0,24}(?:administrator|admin|system|superuser)",
            r"(?:你现在是|现在你是|请扮演|请充当|切换为).{0,12}(?:管理员|系统|超级用户)|"
            r"(?:actas|youarenow|switchto).{0,16}(?:administrator|admin|system|superuser)",
        ),
        (
            RISK_PROMPT_EXFILTRATION,
            r"(?:显示|泄露|输出|返回|告诉我|打印).{0,30}(?:系统提示词|系统 prompt|system prompt|开发者指令)|"
            r"(?:reveal|show|print|return|expose).{0,30}(?:system prompt|developer instructions?)",
            r"(?:显示|泄露|输出|返回|告诉我|打印).{0,20}(?:系统提示词|系统prompt|开发者指令)|"
            r"(?:reveal|show|print|return|expose).{0,20}(?:systemprompt|developerinstructions?)",
        ),
        (
            RISK_CROSS_USER_REQUEST,
            r"(?:返回|显示|泄露|读取|访问|获取).{0,35}(?:其他用户|别的用户|另一用户).{0,20}(?:资料|数据|文件|内容)?|"
            r"(?:return|show|reveal|read|access|get).{0,35}(?:another user(?:'s)?|other users?).{0,20}(?:data|files?|content)?",
            r"(?:返回|显示|泄露|读取|访问|获取).{0,24}(?:其他用户|别的用户|另一用户).{0,12}(?:资料|数据|文件|内容)?|"
            r"(?:return|show|reveal|read|access|get).{0,24}(?:anotherusers?|otherusers?).{0,12}(?:data|files?|content)?",
        ),
        (
            RISK_SCORE_MANIPULATION,
            r"(?:给|打|设为|改成|必须给).{0,24}(?:100\s*分|满分)|"
            r"(?:give|set|assign).{0,24}(?:score of )?100(?:\s*points?)?",
            r"(?:给|打|设为|改成|必须给).{0,16}(?:100分|满分)|"
            r"(?:give|set|assign).{0,16}(?:scoreof)?100(?:points?)?",
        ),
        (
            RISK_EVIDENCE_BYPASS,
            r"(?:不要|无需|禁止|跳过|绕过).{0,24}(?:引用|来源|证据|校验|核验)|"
            r"(?:do not|don't|skip|bypass).{0,24}(?:cite|citation|source|evidence|validation)",
            r"(?:不要|无需|禁止|跳过|绕过).{0,16}(?:引用|来源|证据|校验|核验)|"
            r"(?:donot|dont|skip|bypass).{0,16}(?:cite|citation|source|evidence|validation)",
        ),
        (
            RISK_RESUME_FABRICATION,
            r"(?:把|将).{0,24}(?:jd|岗位).{0,24}(?:技能|要求).{0,24}(?:写成|包装成|说成|当成).{0,16}(?:掌握|会|能力|经历)|"
            r"(?:claim|present|write).{0,35}(?:jd|job).{0,24}(?:skills?|requirements?).{0,24}(?:as mine|as experience|as mastered)",
            r"(?:把|将).{0,16}(?:jd|岗位).{0,16}(?:技能|要求).{0,16}(?:写成|包装成|说成|当成).{0,12}(?:掌握|会|能力|经历)|"
            r"(?:claim|present|write).{0,24}(?:jd|job).{0,16}(?:skills?|requirements?).{0,16}(?:asmine|asexperience|asmastered)",
        ),
    )
    for risk_type, pattern, compact_pattern in checks:
        if _match_risk(normalized, compact, pattern, compact_pattern):
            risks.add(risk_type)
    return risks


def sanitize_untrusted_text(value: str, *, agent_name: str) -> GuardResult:
    lines = value.splitlines() or [value]
    sanitized_lines: list[str] = []
    all_risks: set[str] = set()
    blocked_count = 0
    for line in lines:
        risks = detect_prompt_injection(line)
        if risks:
            all_risks.update(risks)
            blocked_count += 1
            sanitized_lines.append(UNTRUSTED_CONTENT_PLACEHOLDER)
        else:
            sanitized_lines.append(line)

    combined_risks = detect_prompt_injection(value)
    if combined_risks - all_risks:
        all_risks.update(combined_risks)
        blocked_count += 1
        sanitized_lines = [UNTRUSTED_CONTENT_PLACEHOLDER]

    sanitized = "\n".join(sanitized_lines)
    sanitized = re.sub(
        r"</?\s*untrusted[_-]?data\s*>",
        "[不受信数据边界标记已移除]",
        sanitized,
        flags=re.IGNORECASE,
    )
    if all_risks:
        logger.warning(
            "untrusted_content_blocked agent=%s risk_types=%s blocked_count=%s",
            agent_name,
            ",".join(sorted(all_risks)),
            blocked_count,
        )
    return GuardResult(
        sanitized_text=sanitized,
        risk_types=tuple(sorted(all_risks)),
        blocked_count=blocked_count,
    )


def sanitize_untrusted_payload(value: Any, *, agent_name: str) -> Any:
    if isinstance(value, str):
        return sanitize_untrusted_text(value, agent_name=agent_name).sanitized_text
    if isinstance(value, list):
        return [
            sanitize_untrusted_payload(item, agent_name=agent_name)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            sanitize_untrusted_payload(item, agent_name=agent_name)
            for item in value
        )
    if isinstance(value, dict):
        return {
            key: sanitize_untrusted_payload(item, agent_name=agent_name)
            for key, item in value.items()
        }
    return value


def validate_agent_output_texts(
    values: list[str],
    *,
    agent_name: str,
) -> None:
    risks: set[str] = set()
    blocked_count = 0
    for value in values:
        value_risks = detect_prompt_injection(value)
        if value_risks:
            risks.update(value_risks)
            blocked_count += 1
    if not risks:
        return
    logger.warning(
        "unsafe_agent_output_blocked agent=%s risk_types=%s blocked_count=%s",
        agent_name,
        ",".join(sorted(risks)),
        blocked_count,
    )
    raise UnsafeAgentOutputError(risks)
