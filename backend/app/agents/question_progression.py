import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal, TypeAlias


QuestionIntent: TypeAlias = Literal[
    "project_background",
    "personal_responsibility",
    "technical_decision",
    "challenge_solution",
    "verifiable_result",
    "collaboration_reflection",
    "role_expertise",
]

QUESTION_INTENTS: tuple[QuestionIntent, ...] = (
    "project_background",
    "personal_responsibility",
    "technical_decision",
    "challenge_solution",
    "verifiable_result",
    "collaboration_reflection",
    "role_expertise",
)

INTENT_LABELS: dict[QuestionIntent, str] = {
    "project_background": "项目背景和待解决问题",
    "personal_responsibility": "个人职责和责任边界",
    "technical_decision": "具体技术决策和取舍依据",
    "challenge_solution": "难点和实际解决过程",
    "verifiable_result": "可量化或可验证结果",
    "collaboration_reflection": "协作方式和复盘",
    "role_expertise": "岗位专业能力",
}

_FOLLOW_UP_PRIORITY: tuple[QuestionIntent, ...] = (
    "personal_responsibility",
    "technical_decision",
    "verifiable_result",
    "challenge_solution",
    "collaboration_reflection",
    "role_expertise",
    "project_background",
)
_MAIN_QUESTION_PRIORITY: tuple[QuestionIntent, ...] = (
    "project_background",
    "challenge_solution",
    "role_expertise",
    "collaboration_reflection",
    "personal_responsibility",
    "technical_decision",
    "verifiable_result",
)

_INTENT_KEYWORDS: dict[QuestionIntent, tuple[str, ...]] = {
    "project_background": (
        "项目背景",
        "业务背景",
        "研究背景",
        "背景与动机",
        "应用场景",
        "要解决",
        "当时的目标",
        "约束条件",
    ),
    "personal_responsibility": (
        "个人负责",
        "亲自负责",
        "个人职责",
        "职责边界",
        "责任边界",
        "承担的工作",
        "具体承担",
        "个人贡献",
    ),
    "technical_decision": (
        "技术决策",
        "技术选择",
        "方案选择",
        "架构决策",
        "取舍依据",
        "方案取舍",
        "技术方案",
        "权衡",
        "为什么选择",
    ),
    "challenge_solution": (
        "技术难点",
        "技术挑战",
        "最棘手",
        "排查过程",
        "解决过程",
        "解决步骤",
        "故障定位",
        "如何克服",
    ),
    "verifiable_result": (
        "最终结果",
        "量化结果",
        "可验证",
        "如何验证",
        "验收",
        "实际效果",
        "反馈",
    ),
    "collaboration_reflection": (
        "协作",
        "合作",
        "团队分工",
        "沟通",
        "复盘",
    ),
    "role_expertise": (
        "目标岗位",
        "岗位能力",
        "专业能力",
        "核心能力",
    ),
}

_PUNCTUATION_PATTERN = re.compile(
    r"[，。！？；：、,.!?;:…—\-~·“”‘’\"'（）()\[\]【】<>《》]+"
)
_WHITESPACE_PATTERN = re.compile(r"\s+")

_FALLBACK_QUESTIONS: dict[QuestionIntent, tuple[str, ...]] = {
    "project_background": (
        "请基于一段真实项目经历，说明当时的背景以及需要解决的业务或技术目标。",
        "请换一段真实经历，说明它的应用场景和当时最重要的约束条件。",
    ),
    "personal_responsibility": (
        "在这段经历中，哪些工作由你亲自负责？请只说明真实的职责边界。",
        "请区分整体成果和你的个人贡献，说明其中一项由你独立推进的工作。",
    ),
    "technical_decision": (
        "针对刚才的工作，你亲自做过哪一个关键技术选择？请说明当时的取舍依据。",
        "请说明一个由你参与决定的方案选择，以及你比较过的替代方案。",
    ),
    "challenge_solution": (
        "过程中最棘手的一个难点是什么？请说明你实际采取的排查或解决步骤。",
        "请说明一次真实的故障或阻塞，以及你如何定位原因并推进解决。",
    ),
    "verifiable_result": (
        "这项工作的结果如何被验证？如无量化指标，可说明验收现象、反馈或其他真实依据。",
        "请说明方案落地后的实际效果；如果没有指标，请如实描述可观察到的变化。",
    ),
    "collaboration_reflection": (
        "这项工作中你如何与他人协作？请说明一次真实分工或复盘。",
        "请说明一次团队意见不一致的情况，以及你实际采用的沟通和推进方式。",
    ),
    "role_expertise": (
        "结合目标岗位，这段真实经历最能体现你的哪项专业能力？请说明具体行为。",
        "请选择目标岗位的一项核心要求，说明你在哪段真实经历中实际运用过它。",
        "面对一项你尚不熟悉的岗位要求，请说明你曾如何用真实行动补足相关能力。",
    ),
}


def normalize_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question).casefold().strip()
    normalized = _PUNCTUATION_PATTERN.sub(" ", normalized)
    return _WHITESPACE_PATTERN.sub(" ", normalized).strip()


def _character_ngrams(value: str, size: int = 2) -> set[str]:
    compact = value.replace(" ", "")
    if len(compact) < size:
        return {compact} if compact else set()
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


def infer_question_intents(question: str) -> set[QuestionIntent]:
    normalized = normalize_question(question).replace(" ", "")
    return {
        intent
        for intent, keywords in _INTENT_KEYWORDS.items()
        if any(keyword.replace(" ", "") in normalized for keyword in keywords)
    }


def infer_covered_intents(questions: list[str]) -> list[QuestionIntent]:
    covered: set[QuestionIntent] = set()
    for question in questions:
        covered.update(infer_question_intents(question))
    return [intent for intent in QUESTION_INTENTS if intent in covered]


def questions_are_similar(left: str, right: str) -> bool:
    normalized_left = normalize_question(left)
    normalized_right = normalize_question(right)
    if normalized_left == normalized_right:
        return True

    compact_left = normalized_left.replace(" ", "")
    compact_right = normalized_right.replace(" ", "")
    if min(len(compact_left), len(compact_right)) < 8:
        return False

    sequence_ratio = SequenceMatcher(None, compact_left, compact_right).ratio()
    left_ngrams = _character_ngrams(normalized_left)
    right_ngrams = _character_ngrams(normalized_right)
    union = left_ngrams | right_ngrams
    ngram_jaccard = len(left_ngrams & right_ngrams) / len(union) if union else 0.0
    length_ratio = min(len(compact_left), len(compact_right)) / max(
        len(compact_left), len(compact_right)
    )

    if sequence_ratio >= 0.84 or ngram_jaccard >= 0.72:
        return True
    if (
        (compact_left in compact_right or compact_right in compact_left)
        and length_ratio >= 0.72
    ):
        return True

    shared_intents = infer_question_intents(left) & infer_question_intents(right)
    return bool(shared_intents) and (
        (sequence_ratio >= 0.72 and ngram_jaccard >= 0.48)
        or (sequence_ratio >= 0.55 and ngram_jaccard >= 0.30)
    )


def find_duplicate_question(candidate: str, asked_questions: list[str]) -> str | None:
    return next(
        (
            asked_question
            for asked_question in asked_questions
            if questions_are_similar(candidate, asked_question)
        ),
        None,
    )


def question_rejection_reason(
    candidate: str,
    *,
    target_intent: QuestionIntent,
    asked_questions: list[str],
    evidence_text: str,
) -> str | None:
    if find_duplicate_question(candidate, asked_questions) is not None:
        return "与已经问过的问题重复或高度近似"
    if len(re.findall(r"[\u3400-\u9fff]", candidate)) < 4:
        return "问题不是清晰的中文问题"
    if candidate.count("？") + candidate.count("?") > 1:
        return "问题包含多个问句，没有聚焦唯一目标"

    candidate_intents = infer_question_intents(candidate)
    if target_intent not in candidate_intents:
        return f"问题没有聚焦{INTENT_LABELS[target_intent]}"
    extra_intents = candidate_intents - {target_intent}
    if extra_intents:
        labels = "、".join(INTENT_LABELS[intent] for intent in extra_intents)
        return f"问题混入了其他考察目标：{labels}"

    normalized_evidence = normalize_question(evidence_text).replace(" ", "")
    quoted_phrases = re.findall(r"[“\"《]([^”\"》]{2,})[”\"》]", candidate)
    for phrase in quoted_phrases:
        normalized_phrase = normalize_question(phrase).replace(" ", "")
        if len(normalized_phrase) >= 4 and normalized_phrase not in normalized_evidence:
            return "问题把用户证据中不存在的名称写成了既定事实"
    return None


def select_target_intent(
    action: Literal["main_question", "follow_up"],
    asked_questions: list[str],
    follow_up_reason: str | None = None,
) -> QuestionIntent:
    covered = set(infer_covered_intents(asked_questions))
    priority = _FOLLOW_UP_PRIORITY if action == "follow_up" else _MAIN_QUESTION_PRIORITY

    if action == "follow_up" and follow_up_reason:
        for intent in priority:
            if intent not in covered and intent in infer_question_intents(follow_up_reason):
                return intent

    return next((intent for intent in priority if intent not in covered), priority[0])


def build_fallback_question(
    target_intent: QuestionIntent,
    asked_questions: list[str],
) -> tuple[str, QuestionIntent]:
    ordered_intents = (
        target_intent,
        *(
            intent
            for intent in _FOLLOW_UP_PRIORITY
            if intent != target_intent
        ),
    )
    for intent in ordered_intents:
        for question in _FALLBACK_QUESTIONS[intent]:
            if find_duplicate_question(question, asked_questions) is None:
                return question, intent
    raise ValueError("确定性问题池中没有未使用的问题")


def all_fallback_questions() -> tuple[str, ...]:
    return tuple(
        question
        for intent in QUESTION_INTENTS
        for question in _FALLBACK_QUESTIONS[intent]
    )
