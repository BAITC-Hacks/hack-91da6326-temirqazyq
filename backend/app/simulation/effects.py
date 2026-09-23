"""Lag-adjusted effects, accumulated before clipping."""

from app.models import Decision, Measure
from app.repository import Repository


def actual_effects(measure: Measure, horizon: int) -> dict[str, float]:
    factor = (horizon - measure.lag) / horizon
    return {indicator: effect * factor for indicator, effect in measure.effects.items()}


def apply_effects(
    decisions: list[Decision], repository: Repository
) -> dict[str, dict[str, float]]:
    indicators = {
        district.name: dict(district.indicators) for district in repository.districts
    }
    for decision in decisions:
        measure = repository.measure_by_id[decision.measure_id]
        targets = list(indicators) if measure.type == "city" else [decision.district]
        for name in targets:
            for indicator, effect in actual_effects(measure, repository.config["horizon"]).items():
                indicators[name][indicator] += effect
    return indicators
