import json
from pathlib import Path

from pydantic import TypeAdapter

from evals.config import CASE_DIR, GROUPS
from evals.schemas import EvalCase


CASE_LIST_ADAPTER = TypeAdapter(list[EvalCase])


def load_cases(
    groups: set[str] | None = None,
    case_dir: Path = CASE_DIR,
) -> list[EvalCase]:
    selected = groups or set(GROUPS)
    unknown = selected - set(GROUPS)
    if unknown:
        raise ValueError(f"未知评估组：{', '.join(sorted(unknown))}")
    cases = []
    seen_ids = set()
    for path in sorted(case_dir.glob("*_cases.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for case in CASE_LIST_ADAPTER.validate_python(payload):
            if case.group not in GROUPS:
                raise ValueError(f"{case.id} 使用了未知评估组 {case.group}")
            if case.id in seen_ids:
                raise ValueError(f"评估 case ID 重复：{case.id}")
            seen_ids.add(case.id)
            if case.group in selected:
                cases.append(case)
    if not cases:
        raise ValueError("没有加载到评估 case")
    return cases
