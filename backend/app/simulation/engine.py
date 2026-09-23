"""The only source of simulated indicators and scores. No AI dependencies."""

from typing import Any

from app.models import Decision
from app.repository import Repository, load_repository
from app.simulation.effects import apply_effects
from app.simulation.scoring import clip, score_state
from app.simulation.synergy import apply_synergies
from app.simulation.validator import normalize_decisions, validate


def evaluate(
    decisions: list[Decision | dict[str, Any]],
    repository: Repository | None = None,
) -> dict[str, Any]:
    """Fast internal evaluation; caller guarantees valid measures and assignments.

    The optimizer and leave-one-out analysis may evaluate fewer than five decisions.
    All additions happen in canonical order and clipping occurs exactly once.
    """
    repository = repository or load_repository()
    normalized = normalize_decisions(decisions)
    indicators = apply_effects(normalized, repository)
    activated = apply_synergies(indicators, normalized, repository)
    minimum = repository.config["indicator_min"]
    maximum = repository.config["indicator_max"]
    indicators = {
        name: {key: clip(value, minimum, maximum) for key, value in values.items()}
        for name, values in indicators.items()
    }
    result = score_state(indicators, repository)
    result["activated_synergies"] = activated
    return result


def calculate(
    decisions: list[Decision | dict[str, Any]],
    repository: Repository | None = None,
) -> dict[str, Any]:
    """Internal complete result without validation or contribution analysis."""
    repository = repository or load_repository()
    normalized = normalize_decisions(decisions)
    before = evaluate([], repository)
    after = evaluate(normalized, repository)
    budget = repository.config["budget"]
    spent = sum(repository.measure_by_id[decision.measure_id].cost for decision in normalized)
    coefficients = repository.config["score_coefficients"]
    decomposition = {
        "average": coefficients["average"] * (after["average_score"] - before["average_score"]),
        "weakest": coefficients["weakest"] * (after["weakest"] - before["weakest"]),
        "critical": coefficients["critical_penalty"] * (before["critical_count"] - after["critical_count"]),
        "total": after["score"] - before["score"],
    }
    return {
        "valid": True,
        "decisions": [decision.model_dump() for decision in normalized],
        "budget": {"total": budget, "spent": spent, "remaining": budget - spent},
        "score": {
            "before": before["score"], "after": after["score"],
            "delta": after["score"] - before["score"],
        },
        "districts": {
            district.name: {
                "score_before": before["district_scores"][district.name],
                "score_after": after["district_scores"][district.name],
                "indicators_before": before["indicators"][district.name],
                "indicators_after": after["indicators"][district.name],
                "indicator_deltas": {
                    key: after["indicators"][district.name][key] - before["indicators"][district.name][key]
                    for key in repository.config["weights"]
                },
                "population_share": district.population_share,
                "profile": district.profile,
            }
            for district in repository.districts
        },
        "critical_before": before["critical"],
        "critical_after": after["critical"],
        "activated_synergies": after["activated_synergies"],
        "measure_contributions": [],
        "city_indicators": {
            "before": before["city_indicators"],
            "after": after["city_indicators"],
            "delta": {
                key: after["city_indicators"][key] - before["city_indicators"][key]
                for key in repository.config["weights"]
            },
        },
        "category_deltas": after["category_deltas"],
        "weakest_district": {
            "before": before["weakest_district"], "after": after["weakest_district"],
        },
        "average_score": {"before": before["average_score"], "after": after["average_score"]},
        "score_decomposition": decomposition,
    }


def simulate(
    decisions: list[Decision | dict[str, Any]],
    *,
    preview: bool = False,
    contributions: bool = True,
    repository: Repository | None = None,
) -> dict[str, Any]:
    repository = repository or load_repository()
    validation = validate(decisions, preview=preview, repository=repository)
    if not validation["valid"]:
        return validation
    normalized = normalize_decisions(decisions)
    result = calculate(normalized, repository)
    if contributions:
        result["measure_contributions"] = [
            {
                "measure_id": decision.measure_id,
                "district": decision.district,
                "contribution": result["score"]["after"] - evaluate(
                    normalized[:index] + normalized[index + 1:], repository
                )["score"],
            }
            for index, decision in enumerate(normalized)
        ]
    return result
