"""Explicit lexicographic objectives used by both search and its API response."""

from typing import Literal, TypedDict


Priority = Literal[
    "balanced",
    "overall_score",
    "weakest_district",
    "transport",
    "ecology",
    "social",
    "safety",
    "services",
    "reduce_critical",
]

CATEGORIES = ("transport", "ecology", "social", "safety", "services")


class Metrics(TypedDict):
    score: float
    weakest: float
    critical: int
    category_deltas: dict[str, float]
    focus_delta: float


def objective_values(metrics: Metrics, priority: Priority) -> tuple[float, ...]:
    """Higher tuples are preferable, with focus used after required objectives.

    Balanced is an explicit policy preset, not a mathematically universal optimum.
    Its breadth term rewards up to one point of improvement in each direction.
    Category deltas are population-weighted city indicator improvements, averaged
    within a category. All calculations retain the engine's full precision.
    """
    score = metrics["score"]
    focus = metrics["focus_delta"]
    if priority == "overall_score":
        return (score, focus)
    if priority == "weakest_district":
        return (metrics["weakest"], score, focus)
    if priority == "reduce_critical":
        return (-float(metrics["critical"]), score, focus)
    if priority in CATEGORIES:
        return (metrics["category_deltas"][priority], score, focus)
    breadth = sum(min(max(value, 0.0), 1.0) for value in metrics["category_deltas"].values())
    balanced = score + 0.2 * metrics["weakest"] - 0.5 * metrics["critical"] + 0.1 * breadth
    return (balanced, score, focus)


def objective_description(priority: Priority, focused: bool = False) -> str:
    descriptions: dict[str, str] = {
        "balanced": (
            "score + 0.2 × weakest_district_score − 0.5 × critical_count "
            "+ 0.1 × sum(min(max(category_delta, 0), 1)); then score. "
            "Это детерминированный пресет, а не универсально лучший подход."
        ),
        "overall_score": "Максимальный итоговый Quality of Life Score.",
        "weakest_district": "Максимальный минимальный районный Score, затем итоговый Score.",
        "reduce_critical": "Минимум критических показателей, затем максимальный итоговый Score.",
    }
    description = descriptions.get(
        priority,
        "Максимальное среднее улучшение индикаторов категории "
        "с учётом долей населения, затем итоговый Score.",
    )
    if focused:
        description += " При равных основных критериях — большее улучшение выбранного района."
    return description
