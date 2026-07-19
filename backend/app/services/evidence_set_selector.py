from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from time import perf_counter

from app.services.retrieval_query_analysis import QueryAnalysis, QueryFacet
from app.services.retrieval_ranking import extract_terms, normalize_text


SET_RELEVANCE_WEIGHT = 0.55
SET_FACET_WEIGHT = 0.30
SET_SOURCE_WEIGHT = 0.10
SET_PROJECT_WEIGHT = 0.05
SET_NEAR_DUPLICATE_THRESHOLD = 0.62


@dataclass(frozen=True)
class EvidenceSetStats:
    covered_facets: tuple[str, ...]
    missing_facets: tuple[str, ...]
    independent_source_count: int
    duplicate_filtered_count: int
    project_filtered_count: int
    project_consistency: float
    selected_count: int
    selector_latency_ms: float

    def as_dict(self) -> dict:
        return asdict(self)


def source_key(chunk: dict) -> str:
    metadata = chunk.get("metadata") or {}
    file_id = str(metadata.get("file_id") or "")
    chunk_index = metadata.get("chunk_index")
    return f"{file_id}:{chunk_index}" if chunk_index is not None else file_id


def _file_id(chunk: dict) -> str:
    return str((chunk.get("metadata") or {}).get("file_id") or "")


def _facet_is_covered(facet: QueryFacet, chunk: dict, filename: str) -> bool:
    haystack = normalize_text(str(chunk.get("content") or ""))
    if any(
        "_" not in term
        and len(normalize_text(term)) >= 2
        and normalize_text(term) in haystack
        for term in facet.terms
    ):
        return True
    concepts = [item for item in facet.text.split() if item]
    if concepts:
        for concept in concepts:
            aliases = [concept]
            aliases.extend(
                term
                for term in facet.terms
                if term == concept or concept in term or term in concept
            )
            if any(
                len(normalize_text(alias)) >= 2
                and normalize_text(alias) in haystack
                for alias in aliases
            ):
                return True
    facet_terms = extract_terms(" ".join(facet.terms))
    chunk_terms = extract_terms(str(chunk.get("content") or ""))
    meaningful = {term for term in facet_terms if len(normalize_text(term)) >= 2}
    if not meaningful:
        return False
    return len(meaningful & chunk_terms) / len(meaningful) >= 0.08


def covered_facets_for_chunk(
    analysis: QueryAnalysis,
    chunk: dict,
    trusted_file_names: dict[str, str],
) -> frozenset[str]:
    filename = trusted_file_names.get(_file_id(chunk), "")
    return frozenset(
        facet.key
        for facet in analysis.required_facets
        if _facet_is_covered(facet, chunk, filename)
    )


def _content_similarity(first: dict, second: dict) -> float:
    first_normalized = normalize_text(str(first.get("content") or ""))
    second_normalized = normalize_text(str(second.get("content") or ""))
    if first_normalized == second_normalized:
        return 1.0
    first_terms = extract_terms(str(first.get("content") or ""))
    second_terms = extract_terms(str(second.get("content") or ""))
    union = first_terms | second_terms
    if not union:
        return 0.0
    term_similarity = len(first_terms & second_terms) / len(union)
    sequence_similarity = SequenceMatcher(
        None,
        first_normalized,
        second_normalized,
        autojunk=False,
    ).ratio()
    return max(term_similarity, sequence_similarity)


def _is_adjacent(first: dict, second: dict) -> bool:
    first_metadata = first.get("metadata") or {}
    second_metadata = second.get("metadata") or {}
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


def _is_redundant(candidate: dict, selected: list[dict]) -> bool:
    for existing in selected:
        similarity = _content_similarity(candidate, existing)
        if similarity >= 0.95:
            return True
        if _is_adjacent(candidate, existing) and similarity >= SET_NEAR_DUPLICATE_THRESHOLD:
            return True
    return False


def _project_consistent(
    analysis: QueryAnalysis,
    chunk: dict,
    trusted_file_names: dict[str, str],
) -> bool:
    if not analysis.project_constraints:
        return True
    filename = trusted_file_names.get(_file_id(chunk), "")
    metadata = chunk.get("metadata") or {}
    haystack = normalize_text(
        str(chunk.get("content") or "")
        if metadata.get("category") == "resume"
        else filename
    )
    return any(
        normalize_text(project) in haystack
        for project in analysis.project_constraints
    )


def _source_type_consistent(analysis: QueryAnalysis, chunk: dict) -> bool:
    metadata = chunk.get("metadata") or {}
    if metadata.get("category") != "resume":
        return True
    query = analysis.normalized_query.casefold()
    resume_cues = ("候选人", "简历", "个人经历", "本人", "用户本人", "他实际")
    return not analysis.project_constraints or any(cue in query for cue in resume_cues)


def _matched_projects(
    analysis: QueryAnalysis,
    chunk: dict,
    trusted_file_names: dict[str, str],
) -> frozenset[str]:
    filename = trusted_file_names.get(_file_id(chunk), "")
    haystack = normalize_text(f"{filename} {chunk.get('content') or ''}")
    return frozenset(
        project
        for project in analysis.project_constraints
        if normalize_text(project) in haystack
    )


def _is_shared_stack_only(analysis: QueryAnalysis, chunk: dict) -> bool:
    if analysis.intent != "comparison":
        return False
    content = str(chunk.get("content") or "").casefold()
    common_terms = ("fastapi", "sqlite", "react", "jwt", "rest")
    unique_terms = (
        "bge",
        "chroma",
        "rag",
        "ocr",
        "pandas",
        "polars",
        "duckdb",
        "管理员",
        "额度",
        "分析",
        "识别",
        "知识库",
    )
    return (
        sum(term in content for term in common_terms) >= 4
        and not any(term in content for term in unique_terms)
    )


def select_evidence_set(
    candidates: list[dict],
    *,
    analysis: QueryAnalysis,
    top_k: int,
    trusted_file_names: dict[str, str] | None = None,
) -> tuple[list[dict], EvidenceSetStats]:
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")
    started = perf_counter()
    trusted_file_names = trusted_file_names or {}
    project_filtered_count = 0
    eligible = []
    for rank, chunk in enumerate(candidates):
        if not _project_consistent(analysis, chunk, trusted_file_names):
            project_filtered_count += 1
            continue
        if not _source_type_consistent(analysis, chunk):
            project_filtered_count += 1
            continue
        if _is_shared_stack_only(analysis, chunk):
            project_filtered_count += 1
            continue
        facet_keys = covered_facets_for_chunk(analysis, chunk, trusted_file_names)
        if any(facet.critical for facet in analysis.required_facets) and not facet_keys:
            continue
        eligible.append(
            (
                rank,
                chunk,
                facet_keys,
            )
        )

    selected: list[dict] = []
    covered: set[str] = set()
    selected_files: set[str] = set()
    selected_projects: set[str] = set()
    duplicate_filtered_count = 0
    duplicate_keys: set[str] = set()
    pending = list(eligible)
    while pending and len(selected) < top_k:
        scored = []
        redundant_ids: set[int] = set()
        uncovered = {
            facet.key
            for facet in analysis.required_facets
            if facet.critical and facet.key not in covered
        }
        facet_gain_available = any(
            bool(item[2] & uncovered)
            and not _is_redundant(item[1], selected)
            for item in pending
        )
        missing_projects = set(analysis.project_constraints) - selected_projects
        project_gain_available = (
            analysis.intent == "comparison"
            and bool(missing_projects)
            and any(
                bool(
                    _matched_projects(analysis, item[1], trusted_file_names)
                    & missing_projects
                )
                and (not facet_gain_available or bool(item[2] & uncovered))
                and not _is_redundant(item[1], selected)
                for item in pending
            )
        )
        for rank, chunk, facet_keys in pending:
            if _is_redundant(chunk, selected):
                redundant_ids.add(id(chunk))
                key = source_key(chunk)
                if key not in duplicate_keys:
                    duplicate_keys.add(key)
                    duplicate_filtered_count += 1
                continue
            new_facets = facet_keys & uncovered
            if facet_gain_available and not new_facets:
                continue
            matched_projects = _matched_projects(
                analysis,
                chunk,
                trusted_file_names,
            )
            new_projects = matched_projects & missing_projects
            if project_gain_available and not new_projects:
                continue
            relevance = 1.0 - rank / max(1, len(eligible))
            facet_gain = len(new_facets) / max(1, len(analysis.required_facets))
            source_gain = float(bool(_file_id(chunk)) and _file_id(chunk) not in selected_files)
            score = (
                SET_RELEVANCE_WEIGHT * relevance
                + SET_FACET_WEIGHT * facet_gain
                + SET_SOURCE_WEIGHT * source_gain
                + SET_PROJECT_WEIGHT * float(bool(new_projects) or not missing_projects)
            )
            scored.append(
                (
                    -score,
                    rank,
                    float(chunk.get("distance", 999.0)),
                    source_key(chunk),
                    chunk,
                    facet_keys,
                )
            )
        if not scored:
            break
        scored.sort(key=lambda item: item[:4])
        chosen = scored[0]
        selected.append(chosen[4])
        covered.update(chosen[5])
        selected_files.add(_file_id(chosen[4]))
        selected_projects.update(
            _matched_projects(analysis, chosen[4], trusted_file_names)
        )
        pending = [
            item
            for item in pending
            if item[1] is not chosen[4] and id(item[1]) not in redundant_ids
        ]

    required = tuple(facet.key for facet in analysis.required_facets if facet.critical)
    covered_required = tuple(key for key in required if key in covered)
    missing = tuple(key for key in required if key not in covered)
    consistent_count = sum(
        _project_consistent(analysis, chunk, trusted_file_names)
        for chunk in selected
    )
    stats = EvidenceSetStats(
        covered_facets=covered_required,
        missing_facets=missing,
        independent_source_count=len(selected_files),
        duplicate_filtered_count=duplicate_filtered_count,
        project_filtered_count=project_filtered_count,
        project_consistency=(
            consistent_count / len(selected) if selected else 1.0
        ),
        selected_count=len(selected),
        selector_latency_ms=round((perf_counter() - started) * 1000, 6),
    )
    return selected, stats
