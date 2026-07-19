import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from app.services.retrieval_ranking import normalize_text


MAX_QUERY_VARIANTS = 2
MAX_SEMANTIC_QUERIES = 1 + MAX_QUERY_VARIANTS
MAX_REQUIRED_FACETS = 3

_SPACE_PATTERN = re.compile(r"\s+")
_ASCII_TERM_PATTERN = re.compile(r"[a-z0-9]+(?:[.+#_-][a-z0-9]+)*", re.IGNORECASE)
_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?%?")
_CLAUSE_PATTERN = re.compile(
    r"(?:，|,|；|;|以及|并且|同时|分别|而且|又|然后|随后|与.+?相比|相比于|相比)"
)

_QUESTION_WORDS = {
    "什么",
    "哪些",
    "哪种",
    "哪个",
    "怎样",
    "怎么",
    "如何",
    "是否",
    "有没有",
    "为什么",
    "多少",
    "资料",
    "项目",
    "系统",
    "平台",
    "用户",
    "当前",
    "本人",
    "实际",
}

_TECHNICAL_ALIASES = {
    "api_framework": ("web framework", "api framework", "framework", "框架", "后端框架", "接口框架", "fastapi"),
    "rest_api": ("rest", "rest api", "http api", "接口"),
    "embedding": ("embedding", "encoder", "文本编码", "向量化", "bge"),
    "vector_store": ("vector store", "vector database", "向量库", "向量索引", "chroma"),
    "rag": ("rag", "retrieval augmented generation", "检索增强", "知识库问答"),
    "ocr": ("ocr", "文字识别", "字段抽取", "得到字段", "读取编号", "invoice image", "发票", "票据", "单据", "easyocr", "tesseract", "paddleocr"),
    "jwt": ("jwt", "json web token", "身份认证"),
    "postgresql": ("postgresql", "postgres", "关系数据库"),
    "kubernetes": ("kubernetes", "k8s", "容器编排"),
    "docker": ("docker", "容器部署", "container"),
    "redis": ("redis", "cache", "缓存"),
    "message_queue": ("消息队列", "消息中间件", "rabbitmq", "kafka", "nats", "pulsar"),
    "data_analysis": ("数据分析", "统计", "聚合", "报表", "pandas", "polars", "duckdb"),
}

_ATTRIBUTE_ALIASES = {
    "isolation": ("隔离", "tenant", "multi-tenant", "user_id", "owner", "所有权", "归属", "阻止别人", "只属于", "登录用户", "当前用户"),
    "upload_parse": ("上传", "导入", "解析", "提取正文", "扩展名"),
    "chunk_embedding": ("分块", "切块", "切片", "分段", "chunk", "窗口", "embedding", "向量化"),
    "storage_index": ("写入", "存储", "索引", "向量库", "chroma", "metadata"),
    "stored_identity": ("身份", "身份字段", "身份标识", "用户和文件编号", "用户和文件标识", "metadata"),
    "evidence": ("evidence", "证据", "来源", "事实", "证明", "支持"),
    "job_requirement": ("jd", "岗位", "招聘", "要求"),
    "completeness": ("完整", "充分", "全部关键", "每个必要", "所有条件", "只覆盖部分"),
    "vector_filter": ("向量过滤", "向量范围", "vector filter", "owner user_id", "tenant user_id"),
    "trusted_source": ("数据库来源", "来源校验", "可信文件", "文件所有权", "关系数据库", "filerecord"),
    "failure_recovery": ("失败", "异常", "恢复", "回滚", "补偿", "撤回"),
    "retry": ("重试", "重跑", "再次执行", "幂等"),
    "billing": ("扣费", "额度", "计费", "次数", "预留", "budget", "quota", "limit"),
    "deletion": ("删除", "清除", "注销", "销毁", "移除"),
    "retention": ("保留", "留下", "继续保留", "公共", "全局"),
    "admin": ("管理员", "管理端", "管理后台", "审核", "冻结", "停用", "邀请码"),
    "accuracy": ("准确率", "accuracy", "精度", "正确率"),
    "latency": ("延迟", "耗时", "响应时间", "latency", "p95", "response time"),
    "user_count": ("用户量", "用户数", "客户规模", "付费用户", "付费客户", "订阅用户"),
    "deployment": ("部署", "运行在", "云平台", "云厂商", "公有云"),
    "performance": ("性能提升", "吞吐", "qps", "处理速度"),
}

_PROCESS_CUES = ("如何", "怎样", "怎么", "经过哪些步骤", "流程", "路线", "进入", "以后", "之后", "后")
_MULTI_PART_CUES = ("以及", "并且", "同时", "分别", "又", "而且", "和", "与")
_COMPARISON_CUES = ("相比", "对比", "区别", "不同")
_EVIDENCE_CHECK_CUES = ("是否有资料", "有证据", "资料证明", "材料证明", "只根据", "只看", "实际实现")
_EXISTENCE_CUES = ("是否", "有没有", "有无", "采用", "使用", "包含", "接入")
_NEGATIVE_CUES = ("没有", "未使用", "未采用", "未部署", "不使用", "不包含", "排除", "不考虑")
_NUMERIC_CUES = ("多少", "准确率", "延迟", "耗时", "p95", "qps", "性能提升", "额度", "次数", "低于", "超过")

_PROJECT_SUFFIXES = (
    "知识助理",
    "档案问答",
    "票据平台",
    "运营后台",
    "运营中心",
    "清单工具",
    "缺陷台",
    "备忘录",
    "资料舱",
    "报销台",
    "审计台",
    "日程本",
    "平台",
    "系统",
    "项目",
    "工具",
)


@dataclass(frozen=True)
class QueryFacet:
    key: str
    text: str
    terms: tuple[str, ...]
    critical: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class QueryAnalysis:
    normalized_query: str
    intent: str
    intents: tuple[str, ...]
    project_constraints: tuple[str, ...]
    entity_terms: tuple[str, ...]
    technical_terms: tuple[str, ...]
    attribute_terms: tuple[str, ...]
    numeric_requirements: tuple[str, ...]
    negation_mode: str
    required_facets: tuple[QueryFacet, ...]
    query_variants: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def _normalize_query(query: str) -> str:
    return _SPACE_PATTERN.sub(
        " ",
        unicodedata.normalize("NFKC", query).strip(),
    )


def infer_document_group(filename: str) -> str:
    stem = Path(filename).stem.strip()
    first_part = re.split(r"[-_—–：:（(]", stem, maxsplit=1)[0].strip()
    for suffix in _PROJECT_SUFFIXES:
        if first_part.endswith(suffix) and len(first_part) > len(suffix):
            return first_part[: -len(suffix)].strip()
    return first_part


def _project_constraints(
    query: str,
    trusted_file_names: dict[str, str],
) -> tuple[str, ...]:
    normalized_query = normalize_text(query)
    groups = {
        infer_document_group(filename)
        for filename in trusted_file_names.values()
        if filename
    }
    matched = {
        group
        for group in groups
        if len(normalize_text(group)) >= 2
        and normalize_text(group) in normalized_query
    }
    return tuple(sorted(matched, key=lambda value: (query.find(value), value)))


def _matched_aliases(query: str, aliases: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    folded = query.casefold()
    matched = []
    for canonical, values in aliases.items():
        if any(value.casefold() in folded for value in values):
            matched.append(canonical)
    return tuple(matched)


def _canonical_terms(canonical: str) -> tuple[str, ...]:
    values = _TECHNICAL_ALIASES.get(canonical) or _ATTRIBUTE_ALIASES.get(canonical) or ()
    return tuple(dict.fromkeys((canonical, *values)))


def _facet_from_concepts(index: int, concepts: list[str]) -> QueryFacet:
    terms = []
    for concept in concepts:
        terms.extend(_canonical_terms(concept))
    unique_terms = tuple(dict.fromkeys(term for term in terms if term))
    return QueryFacet(
        key=f"facet_{index}",
        text=" ".join(concepts),
        terms=unique_terms,
    )


def _concepts_in_clause(clause: str) -> list[str]:
    concepts = list(_matched_aliases(clause, _TECHNICAL_ALIASES))
    concepts.extend(_matched_aliases(clause, _ATTRIBUTE_ALIASES))
    return list(dict.fromkeys(concepts))


def _build_facets(query: str, technical: tuple[str, ...], attributes: tuple[str, ...]) -> tuple[QueryFacet, ...]:
    concepts = list(dict.fromkeys((*technical, *attributes)))
    folded = query.casefold()
    if "vector_store" in concepts and "storage_index" in concepts:
        concepts.remove("storage_index")
    if "embedding" in concepts and "chunk_embedding" in concepts:
        concepts.remove("chunk_embedding")
    if "job_requirement" in concepts and (
        "只看" in folded or "不考虑" in folded or "排除" in folded
    ):
        concepts.remove("job_requirement")
    process_query = any(cue in query.casefold() for cue in _PROCESS_CUES)
    facets: list[QueryFacet] = []

    if process_query and "upload_parse" in concepts:
        final_process_group = (
            ["isolation"]
            if "isolation" in concepts
            else [name for name in ("storage_index", "vector_store") if name in concepts]
        )
        process_groups = [
            ["upload_parse"],
            [name for name in ("chunk_embedding", "embedding") if name in concepts],
            final_process_group,
        ]
        for group in process_groups:
            if group:
                facets.append(_facet_from_concepts(len(facets) + 1, group))

    if not facets:
        clauses = [part.strip(" ?？") for part in _CLAUSE_PATTERN.split(query) if part.strip(" ?？")]
        for clause in clauses:
            clause_concepts = [
                concept
                for concept in _concepts_in_clause(clause)
                if concept in concepts
            ]
            for concept in clause_concepts:
                facets.append(_facet_from_concepts(len(facets) + 1, [concept]))
                if len(facets) >= MAX_REQUIRED_FACETS:
                    break
            if len(facets) >= MAX_REQUIRED_FACETS:
                break

    covered = {term for facet in facets for term in facet.text.split()}
    for concept in concepts:
        if concept not in covered and len(facets) < MAX_REQUIRED_FACETS:
            facets.append(_facet_from_concepts(len(facets) + 1, [concept]))

    if not facets:
        ascii_terms = [
            term.casefold()
            for term in _ASCII_TERM_PATTERN.findall(query)
            if len(term) >= 2 and term.casefold() not in _QUESTION_WORDS
        ]
        text = " ".join(ascii_terms[:4]) or query
        facets.append(
            QueryFacet(
                key="facet_1",
                text=text,
                terms=tuple(dict.fromkeys(ascii_terms)) or (query,),
                critical=False,
            )
        )
    return tuple(facets[:MAX_REQUIRED_FACETS])


def _intent_labels(query: str, facet_count: int) -> tuple[str, ...]:
    folded = query.casefold()
    labels = []
    if any(cue in folded for cue in _COMPARISON_CUES):
        labels.append("comparison")
    if any(cue in folded for cue in _EVIDENCE_CHECK_CUES):
        labels.append("evidence_check")
    if any(cue in folded for cue in _NUMERIC_CUES) or _NUMBER_PATTERN.search(query):
        labels.append("numeric")
    if any(cue in folded for cue in _NEGATIVE_CUES):
        labels.append("negative")
    if any(cue in folded for cue in _EXISTENCE_CUES):
        labels.append("existence")
    strong_process = any(
        cue in folded
        for cue in ("经过哪些步骤", "流程", "路线", "进入", "以后", "之后", "上传后", "失败后")
    )
    if strong_process and facet_count >= 2:
        labels.append("multi_hop")
    elif any(cue in folded for cue in (*_MULTI_PART_CUES, " and ")):
        labels.append("multi_part")
    if not labels:
        labels.append("fact")
    return tuple(dict.fromkeys(labels))


def _primary_intent(labels: tuple[str, ...]) -> str:
    for name in (
        "comparison",
        "multi_hop",
        "multi_part",
        "evidence_check",
        "numeric",
        "negative",
        "existence",
        "fact",
    ):
        if name in labels:
            return name
    return "fact"


def _build_variants(
    query: str,
    projects: tuple[str, ...],
    facets: tuple[QueryFacet, ...],
) -> tuple[str, ...]:
    variants = []
    project_prefix = " ".join(projects[:2])
    if len(projects) >= 2:
        return tuple(
            f"{project} 项目 技术 能力"
            for project in projects[:MAX_QUERY_VARIANTS]
        )
    for facet in facets:
        meaningful = [
            term
            for term in facet.terms
            if len(normalize_text(term)) >= 2
            and term.casefold() not in _QUESTION_WORDS
        ]
        value = " ".join(dict.fromkeys((*projects[:2], *meaningful[:6]))).strip()
        if not value or normalize_text(value) == normalize_text(query):
            continue
        if len(value.split()) == 1 and not project_prefix:
            continue
        if normalize_text(value) in {normalize_text(item) for item in variants}:
            continue
        variants.append(value)
        if len(variants) >= MAX_QUERY_VARIANTS:
            break
    return tuple(variants)


def analyze_query(
    query: str,
    *,
    trusted_file_names: dict[str, str] | None = None,
) -> QueryAnalysis:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        raise ValueError("query 不能为空")
    trusted_file_names = trusted_file_names or {}
    projects = _project_constraints(normalized_query, trusted_file_names)
    technical = _matched_aliases(normalized_query, _TECHNICAL_ALIASES)
    attributes = _matched_aliases(normalized_query, _ATTRIBUTE_ALIASES)
    facets = _build_facets(normalized_query, technical, attributes)
    intents = _intent_labels(normalized_query, len(facets))
    numeric_requirements = tuple(_NUMBER_PATTERN.findall(normalized_query))
    if any(cue in normalized_query.casefold() for cue in _NEGATIVE_CUES):
        negation_mode = "explicit_negative"
    elif any(cue in normalized_query.casefold() for cue in _EXISTENCE_CUES):
        negation_mode = "existence_check"
    else:
        negation_mode = "none"
    ascii_entities = tuple(
        dict.fromkeys(
            term.casefold()
            for term in _ASCII_TERM_PATTERN.findall(normalized_query)
            if len(term) >= 2
        )
    )
    return QueryAnalysis(
        normalized_query=normalized_query,
        intent=_primary_intent(intents),
        intents=intents,
        project_constraints=projects,
        entity_terms=tuple(dict.fromkeys((*projects, *ascii_entities))),
        technical_terms=technical,
        attribute_terms=attributes,
        numeric_requirements=numeric_requirements,
        negation_mode=negation_mode,
        required_facets=facets,
        query_variants=_build_variants(normalized_query, projects, facets),
    )
