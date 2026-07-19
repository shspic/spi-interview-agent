import re
from dataclasses import asdict, dataclass

from app.services.retrieval_ranking import extract_terms, normalize_text, rerank_chunks


HARD_REJECT_DISTANCE = 1.15
ADAPTIVE_EXPANSION_DISTANCE = 1.10
BORDERLINE_MIN_LEXICAL = 0.07
STRONG_LEXICAL = 0.18

_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?%?")
_AMOUNT_CUE_PATTERN = re.compile(
    r"多少|几(?:个|天|台|条|名|次|毫秒|秒)|营收|收入|吞吐量|\bqps\b",
    re.IGNORECASE,
)
_EXISTENCE_CUE_PATTERN = re.compile(r"是否|有没有|有无|是不是|包含|采用|使用.*吗|达到.*吗")
_NEGATION_PATTERN = re.compile(
    r"未使用|未采用|未部署|没有|不使用|不包含|未达到|未给出|未说明|无法确认|并非"
)
_MISSING_INFORMATION_PATTERN = re.compile(
    r"(?:本文|本段|文档|材料|资料).{0,8}(?:没有|未)(?:给出|陈述|说明|记录)"
)
_ASCII_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[.+#_-][a-z0-9]+)*", re.IGNORECASE)
_GENERIC_ASCII_TERMS = {
    "api",
    "backend",
    "chinese",
    "citation",
    "collection",
    "dependency",
    "embedding",
    "experience",
    "frontend",
    "injection",
    "inspection",
    "management",
    "organization",
    "access",
    "photo",
    "platform",
    "project",
    "python",
    "rest",
    "source",
    "state",
    "topic",
    "user",
}


@dataclass(frozen=True)
class CandidateDecision:
    source_key: str
    accepted: bool
    confidence: float
    reason: str
    distance: float
    content_coverage: float
    filename_coverage: float
    lexical_score: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalDecision:
    ranked_candidates: list[dict]
    accepted_candidates: list[dict]
    sufficient: bool
    confidence: float
    decision_reason: str
    candidate_decisions: list[CandidateDecision]
    filtered_counts: dict[str, int]


def _coverage(query_terms: frozenset[str], target_terms: frozenset[str]) -> float:
    if not query_terms:
        return 0.0
    return len(query_terms & target_terms) / len(query_terms)


def _source_key(chunk: dict) -> str:
    metadata = chunk.get("metadata") or {}
    file_id = str(metadata.get("file_id") or "")
    chunk_index = metadata.get("chunk_index")
    return f"{file_id}:{chunk_index}" if chunk_index is not None else file_id


def _technical_terms(value: str) -> frozenset[str]:
    return frozenset(
        term.casefold()
        for term in re.findall(r"[a-z0-9]+", value, re.IGNORECASE)
        if len(term) >= 2
        and not term.isdigit()
        and term.casefold() not in _GENERIC_ASCII_TERMS
    )


def _numeric_request_is_supported(query: str, content: str) -> bool:
    query_numbers = set(_NUMBER_PATTERN.findall(query))
    content_numbers = set(_NUMBER_PATTERN.findall(content))
    if query_numbers and not query_numbers <= content_numbers:
        return False
    if _AMOUNT_CUE_PATTERN.search(query) and not content_numbers:
        return False
    return True


def _is_keyword_stuffing(query: str, content: str) -> bool:
    query_ascii = set(term.casefold() for term in _ASCII_TOKEN_PATTERN.findall(query))
    content_ascii = set(term.casefold() for term in _ASCII_TOKEN_PATTERN.findall(content))
    return len(content_ascii) >= 6 and len(query_ascii & content_ascii) <= 1


def _candidate_signals(
    query: str,
    chunk: dict,
    trusted_file_names: dict[str, str],
) -> dict:
    content = str(chunk.get("content") or "")
    metadata = chunk.get("metadata") or {}
    file_id = str(metadata.get("file_id") or "")
    query_terms = extract_terms(query)
    content_coverage = _coverage(query_terms, extract_terms(content))
    filename_coverage = _coverage(
        query_terms,
        extract_terms(trusted_file_names.get(file_id, "")),
    )
    exact_phrase = bool(normalize_text(query)) and normalize_text(query) in normalize_text(content)
    lexical_score = min(
        1.0,
        0.75 * content_coverage
        + 0.15 * float(exact_phrase)
        + 0.10 * filename_coverage,
    )
    query_technical_terms = _technical_terms(query)
    content_technical_terms = _technical_terms(content)
    filename_technical_terms = _technical_terms(trusted_file_names.get(file_id, ""))
    technical_terms_supported = (
        not query_technical_terms
        or bool(query_technical_terms & content_technical_terms)
        or (
            bool(query_technical_terms & filename_technical_terms)
            and content_coverage >= BORDERLINE_MIN_LEXICAL
        )
        or content_coverage >= 0.50
    )
    return {
        "content": content,
        "content_coverage": content_coverage,
        "filename_coverage": filename_coverage,
        "exact_phrase": exact_phrase,
        "lexical_score": lexical_score,
        "technical_terms_supported": technical_terms_supported,
        "explicit_negation": bool(_NEGATION_PATTERN.search(content))
        and not _MISSING_INFORMATION_PATTERN.search(content),
        "numeric_supported": _numeric_request_is_supported(query, content),
        "keyword_stuffing": _is_keyword_stuffing(query, content),
    }


def decide_retrieval_evidence(
    query: str,
    chunks: list[dict],
    *,
    top_k: int,
    high_confidence_distance: float,
    trusted_file_names: dict[str, str] | None = None,
    allowed_categories: set[str] | None = None,
) -> RetrievalDecision:
    """对安全过滤后的候选进行排序，并独立判断能否作为事实证据。"""
    trusted_file_names = trusted_file_names or {}
    ranked, ranking_stats = rerank_chunks(
        query,
        chunks,
        top_k=max(top_k, min(len(chunks), top_k * 2)),
        distance_threshold=HARD_REJECT_DISTANCE,
        trusted_file_names=trusted_file_names,
        allowed_categories=allowed_categories,
    )
    signal_rows = [
        (chunk, _candidate_signals(query, chunk, trusted_file_names))
        for chunk in ranked
    ]
    support_fingerprints = {
        normalize_text(signals["content"])
        for _chunk, signals in signal_rows
        if signals["content_coverage"] >= BORDERLINE_MIN_LEXICAL
        and not signals["keyword_stuffing"]
    }
    has_independent_support = len(support_fingerprints) >= 2
    existence_query = bool(_EXISTENCE_CUE_PATTERN.search(query))
    decisions: list[CandidateDecision] = []
    accepted: list[dict] = []

    for chunk, signals in signal_rows:
        distance = float(chunk["distance"])
        lexical_score = float(signals["lexical_score"])
        content_coverage = float(signals["content_coverage"])
        filename_coverage = float(signals["filename_coverage"])
        reason = "rejected_low_lexical_support"
        accepted_candidate = False

        if distance > HARD_REJECT_DISTANCE:
            reason = "rejected_distance"
        elif not signals["numeric_supported"]:
            reason = "rejected_numeric_mismatch"
        elif not signals["technical_terms_supported"]:
            reason = "rejected_missing_technical_phrase"
        elif signals["keyword_stuffing"]:
            reason = "rejected_keyword_stuffing"
        elif distance <= high_confidence_distance and (
            distance <= min(0.35, high_confidence_distance)
            or lexical_score >= BORDERLINE_MIN_LEXICAL
            or signals["exact_phrase"]
            or signals["technical_terms_supported"] and bool(_technical_terms(query))
        ):
            accepted_candidate = True
            reason = "accepted_high_confidence"
        elif signals["explicit_negation"] and content_coverage >= BORDERLINE_MIN_LEXICAL:
            accepted_candidate = True
            reason = "accepted_borderline_with_support"
        elif lexical_score >= STRONG_LEXICAL:
            accepted_candidate = True
            reason = "accepted_borderline_with_support"
        elif existence_query and content_coverage >= 0.14:
            accepted_candidate = True
            reason = "accepted_borderline_with_support"
        elif (
            not existence_query
            and has_independent_support
            and content_coverage >= BORDERLINE_MIN_LEXICAL
        ):
            accepted_candidate = True
            reason = "accepted_borderline_with_support"
        elif (
            filename_coverage >= 0.25
            and content_coverage >= BORDERLINE_MIN_LEXICAL
        ):
            accepted_candidate = True
            reason = "accepted_borderline_with_support"

        confidence = max(
            0.0,
            min(
                1.0,
                0.65 * (1.0 - distance / HARD_REJECT_DISTANCE)
                + 0.30 * lexical_score
                + 0.05 * float(has_independent_support),
            ),
        )
        decisions.append(
            CandidateDecision(
                source_key=_source_key(chunk),
                accepted=accepted_candidate,
                confidence=round(confidence, 6),
                reason=reason,
                distance=distance,
                content_coverage=round(content_coverage, 6),
                filename_coverage=round(filename_coverage, 6),
                lexical_score=round(lexical_score, 6),
            )
        )
        if accepted_candidate and len(accepted) < top_k:
            accepted.append(chunk)

    accepted_decisions = [item for item in decisions if item.accepted]
    confidence = max((item.confidence for item in accepted_decisions), default=0.0)
    if accepted:
        decision_reason = accepted_decisions[0].reason
    elif any(item.reason == "rejected_distance" for item in decisions):
        decision_reason = "rejected_distance"
    else:
        decision_reason = "rejected_no_answer"
    filtered_counts = {
        **ranking_stats.as_dict(),
        "confidence_filtered_count": sum(not item.accepted for item in decisions),
    }
    return RetrievalDecision(
        ranked_candidates=ranked[:top_k],
        accepted_candidates=accepted,
        sufficient=bool(accepted),
        confidence=round(confidence, 6),
        decision_reason=decision_reason,
        candidate_decisions=decisions,
        filtered_counts=filtered_counts,
    )


def should_expand_candidate_pool(decision: RetrievalDecision, *, top_k: int) -> bool:
    if not decision.ranked_candidates:
        return False
    return len(decision.accepted_candidates) < min(2, top_k)
