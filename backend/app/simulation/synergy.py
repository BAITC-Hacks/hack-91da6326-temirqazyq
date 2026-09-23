"""Synergy bonuses are local and never scaled by lag."""

from typing import Any

from app.models import Decision
from app.repository import Repository


def apply_synergies(
    indicators: dict[str, dict[str, float]],
    decisions: list[Decision],
    repository: Repository,
) -> list[dict[str, Any]]:
    selected = {decision.measure_id: decision for decision in decisions}
    activated: list[dict[str, Any]] = []
    for synergy in repository.synergies:
        if all(measure_id in selected for measure_id in synergy["measure_ids"]):
            district = selected[synergy["district_measure_id"]].district
            for indicator, effect in synergy["effects"].items():
                indicators[district][indicator] += effect
            activated.append({
                "measure_ids": list(synergy["measure_ids"]),
                "district": district,
                "effects": dict(synergy["effects"]),
            })
    return activated
