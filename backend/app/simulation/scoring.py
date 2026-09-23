"""Pure score calculation: no display rounding or external services."""

from math import fsum
from typing import Any

from app.repository import Repository


def clip(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def critical_indicators(
    indicators: dict[str, dict[str, float]], threshold: float
) -> list[dict[str, Any]]:
    return [
        {"district": district, "indicator": indicator, "value": value}
        for district, values in indicators.items()
        for indicator, value in values.items()
        if value < threshold
    ]


def score_state(
    indicators: dict[str, dict[str, float]], repository: Repository
) -> dict[str, Any]:
    weights = repository.config["weights"]
    district_scores = {
        name: fsum(weights[key] * value for key, value in values.items())
        for name, values in indicators.items()
    }
    average = fsum(
        district.population_share * district_scores[district.name]
        for district in repository.districts
    )
    weakest_name = min(district_scores, key=district_scores.__getitem__)
    weakest = district_scores[weakest_name]
    critical = critical_indicators(indicators, repository.config["critical_threshold"])
    coefficients = repository.config["score_coefficients"]
    score = (
        coefficients["average"] * average
        + coefficients["weakest"] * weakest
        - coefficients["critical_penalty"] * len(critical)
    )
    city_indicators = {
        key: fsum(
            district.population_share * indicators[district.name][key]
            for district in repository.districts
        )
        for key in weights
    }
    category_deltas = {
        category: fsum(
            district.population_share
            * (indicators[district.name][key] - district.indicators[key])
            for district in repository.districts
            for key in keys
        ) / len(keys)
        for category, keys in repository.config["categories"].items()
    }
    return {
        "score": score,
        "district_scores": district_scores,
        "indicators": indicators,
        "critical": critical,
        "critical_count": len(critical),
        "average_score": average,
        "weakest": weakest,
        "weakest_district": {"name": weakest_name, "score": weakest},
        "city_indicators": city_indicators,
        "category_deltas": category_deltas,
    }
