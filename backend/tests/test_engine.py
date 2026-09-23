"""Numerical and constraint regression tests for the specified city model."""

from copy import deepcopy
from itertools import permutations

import pytest

from app.models import SimulationResult
from app.repository import load_repository
from app.simulation.effects import actual_effects
from app.simulation.engine import evaluate, simulate
from app.simulation.scoring import critical_indicators
from app.simulation.validator import validate


@pytest.fixture
def repository():
    return load_repository()


@pytest.fixture
def example():
    return [
        {"measure_id": "M7", "district": "Нура"},
        {"measure_id": "M8", "district": "Нура"},
        {"measure_id": "M10", "district": "Нура"},
        {"measure_id": "M12"},
        {"measure_id": "M5", "district": "Сарыарка"},
    ]


def codes(result):
    return {error["code"] for error in result["errors"]}


def preview(*decisions, repository=None):
    return simulate(list(decisions), preview=True, repository=repository)


def test_weights_sum_to_one(repository):
    assert sum(repository.config["weights"].values()) == pytest.approx(1)


def test_population_shares_sum_to_one(repository):
    assert sum(district.population_share for district in repository.districts) == pytest.approx(1)


def test_base_city_score():
    result = simulate([], preview=True)
    assert result["valid"]
    assert result["score"]["before"] == pytest.approx(52.56, abs=0.01)
    assert result["score"]["after"] == result["score"]["before"]
    assert result["districts"]["Нура"]["score_after"] == pytest.approx(49.18)
    assert result["budget"]["spent"] == 0


def test_nura_has_two_critical_indicators():
    result = simulate([], preview=True)
    assert result["critical_after"] == [
        {"district": "Нура", "indicator": "S1", "value": 38},
        {"district": "Нура", "indicator": "S2", "value": 35},
    ]


def test_lag_adjustment(repository):
    effects = actual_effects(repository.measure_by_id["M1"], repository.config["horizon"])
    assert effects == {"T1": 4.5, "T2": 6.75}


def test_city_measure_applies_to_all_districts():
    result = preview({"measure_id": "M12"})
    assert len(result["districts"]) == 5
    assert all(district["indicator_deltas"]["C2"] == 4.375 for district in result["districts"].values())


def test_district_measure_only_applies_to_target():
    result = preview({"measure_id": "M1", "district": "Нура"})
    for name, district in result["districts"].items():
        assert district["indicator_deltas"]["T1"] == (4.5 if name == "Нура" else 0)
        assert district["indicator_deltas"]["T2"] == (6.75 if name == "Нура" else 0)


@pytest.mark.parametrize(
    "district_measure,city_measure,indicator,expected_delta,other_delta",
    [("M1", "M2", "T1", 9.5, 3), ("M10", "M12", "B1", 12.5, 0), ("M5", "M6", "E2", 12.25, 1.5)],
)
def test_all_synergies_are_local_and_not_lag_scaled(district_measure, city_measure, indicator, expected_delta, other_delta):
    result = preview({"measure_id": district_measure, "district": "Нура"}, {"measure_id": city_measure})
    assert result["valid"]
    assert result["districts"]["Нура"]["indicator_deltas"][indicator] == expected_delta
    assert result["districts"]["Есиль"]["indicator_deltas"][indicator] == other_delta
    assert result["activated_synergies"] == [{
        "measure_ids": [district_measure, city_measure], "district": "Нура", "effects": {indicator: 2},
    }]


def test_m1_and_m3_incompatible_even_across_districts():
    result = preview({"measure_id": "M1", "district": "Нура"}, {"measure_id": "M3", "district": "Есиль"})
    assert "INCOMPATIBLE_MEASURES" in codes(result)
    assert "score" not in result


@pytest.mark.parametrize("ids", [("M4", "M7"), ("M5", "M13")])
def test_same_district_incompatibilities(ids):
    result = preview(*[{"measure_id": measure_id, "district": "Нура"} for measure_id in ids])
    assert "INCOMPATIBLE_MEASURES" in codes(result)


@pytest.mark.parametrize("ids", [("M4", "M7"), ("M5", "M13")])
def test_local_incompatibilities_allow_different_districts(ids):
    result = preview({"measure_id": ids[0], "district": "Нура"}, {"measure_id": ids[1], "district": "Есиль"})
    assert result["valid"]


def test_budget_over_100_invalid():
    decisions = [
        {"measure_id": "M3", "district": "Нура"}, {"measure_id": "M5", "district": "Есиль"},
        {"measure_id": "M7", "district": "Нура"}, {"measure_id": "M13", "district": "Алматы"},
        {"measure_id": "M10", "district": "Сарыарка"},
    ]
    result = simulate(decisions)
    assert "BUDGET_EXCEEDED" in codes(result)
    assert "score" not in result


def test_duplicate_measure_invalid_across_districts():
    result = preview({"measure_id": "M7", "district": "Нура"}, {"measure_id": "M7", "district": "Есиль"})
    assert "DUPLICATE_MEASURE" in codes(result)


def test_more_than_two_of_a_category_invalid():
    result = preview(*[{"measure_id": measure_id, "district": "Нура"} for measure_id in ["M7", "M8", "M9"]])
    assert "CATEGORY_LIMIT" in codes(result)


def test_final_requires_exactly_five_decisions(example):
    assert "DECISION_COUNT" in codes(simulate(example[:-1]))
    assert "DECISION_COUNT" in codes(simulate([]))
    assert simulate(example)["valid"]
    assert preview(*example[:-1])["valid"]
    assert "DECISION_COUNT" in codes(preview(*example, {"measure_id": "M14"}))


def test_clip_to_indicator_bounds(repository):
    custom = deepcopy(repository)
    custom.measure_by_id["M11"].effects = {"T1": -1000, "B2": 1000}
    result = preview({"measure_id": "M11", "district": "Нура"}, repository=custom)
    indicators = result["districts"]["Нура"]["indicators_after"]
    assert indicators["T1"] == 0
    assert indicators["B2"] == 100


def test_clipping_occurs_after_all_effects(repository):
    custom = deepcopy(repository)
    custom.measure_by_id["M1"].effects = {"T1": 160}
    custom.measure_by_id["M11"].effects = {"T1": -80}
    decisions = [{"measure_id": "M1", "district": "Нура"}, {"measure_id": "M11", "district": "Нура"}]
    result = preview(*decisions, repository=custom)
    # 55 + 120 - 70 = 105; clipping each addition would produce 30 instead.
    assert result["districts"]["Нура"]["indicators_after"]["T1"] == 100
    assert preview(*reversed(decisions), repository=custom) == result


def test_critical_threshold_is_strict():
    result = critical_indicators({"A": {"low": 39.999, "boundary": 40, "high": 40.001}}, threshold=40)
    assert result == [{"district": "A", "indicator": "low", "value": 39.999}]


def test_specified_valid_scenario(example):
    result = simulate(example)
    assert result["valid"]
    assert result["budget"] == {"total": 100, "spent": 95, "remaining": 5}
    assert result["score"]["after"] == pytest.approx(56.5, abs=0.05)
    assert result["score"]["after"] == pytest.approx(56.54307, abs=1e-9)
    assert result["score"]["delta"] > 0
    assert result["critical_after"] == []
    assert result["activated_synergies"][0]["measure_ids"] == ["M10", "M12"]
    assert result["districts"]["Нура"]["indicators_after"]["B1"] == 67.5
    SimulationResult.model_validate(result)


def test_decision_order_does_not_change_any_output(example):
    expected = simulate(example)
    for ordering in permutations(example):
        assert simulate(list(ordering)) == expected


def test_leave_one_out_contributions_include_lost_synergy(example):
    result = simulate(example)
    assert len(result["measure_contributions"]) == 5
    for contribution in result["measure_contributions"]:
        reduced = [decision for decision in example if decision["measure_id"] != contribution["measure_id"]]
        expected = result["score"]["after"] - evaluate(reduced)["score"]
        assert contribution["contribution"] == pytest.approx(expected, abs=1e-12)
    reduced = [decision for decision in example if decision["measure_id"] != "M12"]
    assert evaluate(reduced)["activated_synergies"] == []


@pytest.mark.parametrize(
    "decision,error_code",
    [
        ({"measure_id": "M1"}, "DISTRICT_REQUIRED"),
        ({"measure_id": "M1", "district": "Unknown"}, "UNKNOWN_DISTRICT"),
        ({"measure_id": "M12", "district": "Нура"}, "CITY_DISTRICT_FORBIDDEN"),
        ({"measure_id": "M99"}, "UNKNOWN_MEASURE"),
        ({"measure_id": "M12", "unrecognized": True}, "INVALID_DECISION"),
    ],
)
def test_invalid_assignments_return_errors_without_score(decision, error_code):
    result = preview(decision)
    assert result["valid"] is False
    assert error_code in codes(result)
    assert "score" not in result


@pytest.mark.parametrize("decisions", [{}, {"measure_id": "M12"}, (), "", "M12", None, 0, False])
@pytest.mark.parametrize("preview_mode", [False, True])
def test_invalid_decision_containers_return_errors_without_score(decisions, preview_mode):
    result = simulate(decisions, preview=preview_mode)
    assert result["valid"] is False
    assert codes(result) == {"INVALID_DECISION"}
    assert "score" not in result


def test_evaluate_matches_public_result_and_does_not_mutate_dataset(example, repository):
    original = deepcopy(repository)
    quick = evaluate(example, repository)
    result = simulate(example, repository=repository)
    assert quick["score"] == result["score"]["after"]
    assert quick["critical_count"] == len(result["critical_after"])
    assert quick["weakest_district"] == result["weakest_district"]["after"]
    assert quick["category_deltas"] == result["category_deltas"]
    assert repository == original


def test_category_delta_uses_population_weighted_mean():
    result = preview({"measure_id": "M1", "district": "Нура"})
    assert result["category_deltas"]["transport"] == pytest.approx(0.16 * (4.5 + 6.75) / 2)
    assert result["category_deltas"]["ecology"] == 0


def test_negative_side_effect_is_preserved():
    result = preview({"measure_id": "M11", "district": "Нура"})
    assert result["districts"]["Нура"]["indicator_deltas"]["T1"] == -1.75
    assert result["category_deltas"]["transport"] < 0


def test_budget_boundary_is_allowed(repository):
    custom = deepcopy(repository)
    custom.measure_by_id["M12"].cost = 100
    assert validate([{"measure_id": "M12"}], preview=True, repository=custom)["valid"]
