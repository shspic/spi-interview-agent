import re
import unicodedata
from dataclasses import asdict, dataclass
from time import perf_counter


SEMANTIC_WEIGHT = 0.70
LEXICAL_WEIGHT = 0.30
CONTENT_COVERAGE_WEIGHT = 0.75
EXACT_PHRASE_WEIGHT = 0.15
FILENAME_COVERAGE_WEIGHT = 0.10
NEAR_DUPLICATE_THRESHOLD = 0.75
NEAR_DUPLICATE_PENALTY = 0.12

_ASCII_TERM_PATTERN = re.compile(r"[a-z0-9]+(?:[.+#_-][a-z0-9]+)*")
_CHINESE_SEQUENCE_PATTERN = re.compile(r"[\u3400-\u9fff]+")


@dataclass(frozen=True)
class RankingStats:
    candidate_count: int
    distance_filtered_count: int
    category_filtered_count: int
    duplicate_filtered_count: int
    near_duplicate_penalty_count: int
    final_count: int
    latency_ms: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class _ScoredChunk:
    chunk: dict
    semantic_score: float
    lexical_score: float
    combined_score: float
    source_key: str
    normalized_content: str
    content_terms: frozenset[str]


def candidate_pool_size(
    top_k: int,
    candidate_multiplier: int,
    max_candidates: int,
) -> int:
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")
    if candidate_multiplier < 1:
        raise ValueError("candidate_multiplier 必须大于等于 1")
    if max_candidates < 1:
        raise ValueError("max_candidates 必须大于等于 1")
    if top_k > max_candidates:
        raise ValueError("top_k 不能超过最大候选数量")
    return min(max_candidates, max(top_k, top_k * candidate_multiplier))


def normalize_text(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum()
    )


def extract_terms(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    terms = set(_ASCII_TERM_PATTERN.findall(normalized))
    for sequence in _CHINESE_SEQUENCE_PATTERN.findall(normalized):
        if len(sequence) <= 2:
            terms.add(sequence)
            continue
        terms.add(sequence)
        terms.update(
            sequence[index:index + 2]
            for index in range(len(sequence) - 1)
        )
    return frozenset(terms)


def _coverage(query_terms: frozenset[str], target_terms: frozenset[str]) -> float:
    if not query_terms:
        return 0.0
    return len(query_terms & target_terms) / len(query_terms)


def _source_key(chunk: dict) -> str:
    metadata = chunk.get("metadata") or {}
    file_id = str(metadata.get("file_id") or "")
    chunk_index = metadata.get("chunk_index")
    return f"{file_id}:{chunk_index}" if chunk_index is not None else file_id


def _score_chunk(
    query_terms: frozenset[str],
    normalized_query: str,
    chunk: dict,
    distance_threshold: float,
    trusted_file_names: dict[str, str],
) -> _ScoredChunk:
    content = str(chunk.get("content") or "")
    metadata = chunk.get("metadata") or {}
    file_id = str(metadata.get("file_id") or "")
    distance = float(chunk["distance"])
    semantic_score = max(
        0.0,
        min(1.0, 1.0 - max(distance, 0.0) / distance_threshold),
    )
    content_terms = extract_terms(content)
    filename_terms = extract_terms(trusted_file_names.get(file_id, ""))
    exact_phrase = float(
        bool(normalized_query)
        and normalized_query in normalize_text(content)
    )
    lexical_score = min(
        1.0,
        CONTENT_COVERAGE_WEIGHT * _coverage(query_terms, content_terms)
        + EXACT_PHRASE_WEIGHT * exact_phrase
        + FILENAME_COVERAGE_WEIGHT * _coverage(query_terms, filename_terms),
    )
    return _ScoredChunk(
        chunk=chunk,
        semantic_score=semantic_score,
        lexical_score=lexical_score,
        combined_score=(
            SEMANTIC_WEIGHT * semantic_score
            + LEXICAL_WEIGHT * lexical_score
        ),
        source_key=_source_key(chunk),
        normalized_content=normalize_text(content),
        content_terms=content_terms,
    )


def _base_sort_key(item: _ScoredChunk) -> tuple:
    return (
        -item.combined_score,
        float(item.chunk["distance"]),
        item.source_key,
        item.normalized_content,
    )


def _term_similarity(first: _ScoredChunk, second: _ScoredChunk) -> float:
    union = first.content_terms | second.content_terms
    if not union:
        return 1.0 if first.normalized_content == second.normalized_content else 0.0
    return len(first.content_terms & second.content_terms) / len(union)


def _is_adjacent_same_file(first: _ScoredChunk, second: _ScoredChunk) -> bool:
    first_metadata = first.chunk.get("metadata") or {}
    second_metadata = second.chunk.get("metadata") or {}
    if first_metadata.get("file_id") != second_metadata.get("file_id"):
        return False
    first_index = first_metadata.get("chunk_index")
    second_index = second_metadata.get("chunk_index")
    return (
        isinstance(first_index, int)
        and not isinstance(first_index, bool)
        and isinstance(second_index, int)
        and not isinstance(second_index, bool)
        and abs(first_index - second_index) <= 1
    )


def rerank_chunks(
    query: str,
    chunks: list[dict],
    *,
    top_k: int,
    distance_threshold: float,
    trusted_file_names: dict[str, str] | None = None,
    allowed_categories: set[str] | None = None,
) -> tuple[list[dict], RankingStats]:
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")
    if distance_threshold <= 0:
        raise ValueError("distance_threshold 必须大于 0")

    started = perf_counter()
    trusted_file_names = trusted_file_names or {}
    query_terms = extract_terms(query)
    normalized_query = normalize_text(query)
    scored: list[_ScoredChunk] = []
    distance_filtered_count = 0
    category_filtered_count = 0

    for chunk in chunks:
        distance = chunk.get("distance")
        if (
            not isinstance(distance, (int, float))
            or isinstance(distance, bool)
            or float(distance) > distance_threshold
        ):
            distance_filtered_count += 1
            continue
        metadata = chunk.get("metadata") or {}
        if (
            allowed_categories is not None
            and metadata.get("category") not in allowed_categories
        ):
            category_filtered_count += 1
            continue
        scored.append(
            _score_chunk(
                query_terms,
                normalized_query,
                chunk,
                distance_threshold,
                trusted_file_names,
            )
        )

    scored.sort(key=_base_sort_key)
    unique: list[_ScoredChunk] = []
    fingerprints: set[str] = set()
    duplicate_filtered_count = 0
    for item in scored:
        fingerprint = item.normalized_content or item.source_key
        if fingerprint in fingerprints:
            duplicate_filtered_count += 1
            continue
        fingerprints.add(fingerprint)
        unique.append(item)

    selected: list[_ScoredChunk] = []
    pending = list(unique)
    penalized_source_keys: set[str] = set()
    while pending and len(selected) < top_k:
        adjusted: list[tuple[float, float, str, str, _ScoredChunk]] = []
        for item in pending:
            penalized = any(
                _is_adjacent_same_file(item, existing)
                and _term_similarity(item, existing) >= NEAR_DUPLICATE_THRESHOLD
                for existing in selected
            )
            if penalized:
                penalized_source_keys.add(item.source_key)
            score = item.combined_score - (
                NEAR_DUPLICATE_PENALTY if penalized else 0.0
            )
            adjusted.append(
                (
                    -score,
                    float(item.chunk["distance"]),
                    item.source_key,
                    item.normalized_content,
                    item,
                )
            )
        adjusted.sort(key=lambda value: value[:4])
        chosen = adjusted[0]
        selected.append(chosen[4])
        pending.remove(chosen[4])

    latency_ms = round((perf_counter() - started) * 1000, 6)
    return (
        [item.chunk for item in selected],
        RankingStats(
            candidate_count=len(chunks),
            distance_filtered_count=distance_filtered_count,
            category_filtered_count=category_filtered_count,
            duplicate_filtered_count=duplicate_filtered_count,
            near_duplicate_penalty_count=len(penalized_source_keys),
            final_count=len(selected),
            latency_ms=latency_ms,
        ),
    )
