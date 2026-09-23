"""Independent decimal calculation from JSON, without simulation helpers."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.simulation.engine import simulate


def test_dataset_math_and_exact_score_decomposition_independently():
    directory = Path(__file__).resolve().parents[2] / "data"

    def read(name):
        return json.loads((directory / f"{name}.json").read_text(encoding="utf-8"), parse_float=Decimal, parse_int=Decimal)

    config = read("config")
    districts = read("districts")
    measures = {row["id"]: row for row in read("measures")}
    decisions = [{"measure_id": identifier, "district": district} for identifier, district in [
        ("M7", "Нура"), ("M8", "Нура"), ("M10", "Нура"), ("M12", None), ("M5", "Сарыарка"),
    ]]
    before = {row["name"]: dict(row["indicators"]) for row in districts}
    after = {name: dict(values) for name, values in before.items()}
    selected = {row["measure_id"]: row["district"] for row in decisions}
    for decision in decisions:
        measure = measures[decision["measure_id"]]
        targets = list(after) if measure["type"] == "city" else [decision["district"]]
        multiplier = (config["horizon"] - measure["lag"]) / config["horizon"]
        for name in targets:
            for indicator, effect in measure["effects"].items():
                after[name][indicator] += multiplier * effect
    for synergy in read("synergies"):
        if all(identifier in selected for identifier in synergy["measure_ids"]):
            name = selected[synergy["district_measure_id"]]
            for indicator, effect in synergy["effects"].items():
                after[name][indicator] += effect
    for values in after.values():
        for key in values:
            values[key] = min(config["indicator_max"], max(config["indicator_min"], values[key]))

    def components(indicators):
        scores = {name: sum(config["weights"][key] * value for key, value in values.items()) for name, values in indicators.items()}
        average = sum(row["population_share"] * scores[row["name"]] for row in districts)
        weakest = min(scores.values())
        critical = sum(value < config["critical_threshold"] for values in indicators.values() for value in values.values())
        coefficients = config["score_coefficients"]
        total = coefficients["average"] * average + coefficients["weakest"] * weakest - coefficients["critical_penalty"] * critical
        return average, weakest, critical, total

    a, b = components(before), components(after)
    assert a[0] == Decimal("56.8624")
    assert a[3] == Decimal("52.55768")
    assert a[2] == 2
    assert b[3] == Decimal("56.54307")
    assert b[2] == 0
    result = simulate(decisions)
    decomposition = result["score_decomposition"]
    assert decomposition["average"] == pytest.approx(float(Decimal("0.7") * (b[0] - a[0])))
    assert decomposition["weakest"] == pytest.approx(float(Decimal("0.3") * (b[1] - a[1])))
    assert decomposition["critical"] == a[2] - b[2]
    assert sum(decomposition[key] for key in ["average", "weakest", "critical"]) == pytest.approx(decomposition["total"], abs=1e-12)
    assert decomposition["total"] == pytest.approx(float(b[3] - a[3]), abs=1e-12)
