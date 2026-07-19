import math
from collections.abc import Iterable


def recall_at_k(
    ranked_ids: list[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    if not relevant_ids:
        return 1.0
    if k <= 0:
        raise ValueError("k 必须大于 0")
    return len(set(ranked_ids[:k]) & relevant_ids) / len(relevant_ids)


def reciprocal_rank(ranked_ids: list[str], relevant_ids: set[str]) -> float:
    for index, source_id in enumerate(ranked_ids, start=1):
        if source_id in relevant_ids:
            return 1.0 / index
    return 0.0


def accuracy(values: Iterable[bool]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def percentile(values: Iterable[float], percentage: float) -> float:
    items = sorted(float(value) for value in values)
    if not items:
        return 0.0
    if not 0 <= percentage <= 100:
        raise ValueError("百分位必须在 0 到 100 之间")
    rank = max(1, math.ceil((percentage / 100) * len(items)))
    return round(items[rank - 1], 3)


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0

