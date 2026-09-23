from time import perf_counter

import pytest
from pydantic import ValidationError

from app.optimizer.objectives import Metrics, objective_values
from app.optimizer.search import MAX_CANDIDATE_STATES, SearchRequest, search
from app.repository import load_repository
from app.simulation.engine import evaluate, simulate


@pytest.fixture(scope="module")
def default_search():
    started = perf_counter()
    response = search(SearchRequest())
    return response, perf_counter() - started


def test_default_search_returns_valid_scenarios_with_bounded_work(default_search):
    response, elapsed = default_search
    assert len(response["scenarios"]) == 4
    assert 0 < response["search"]["evaluated"] <= MAX_CANDIDATE_STATES
    assert elapsed < 20, "The fixed dataset search should finish within the MVP's interactive time budget"
    assert response["search"]["truncated"] is True
    assert "оптимальность не доказана" in " ".join(response["search"]["notes"])
    signatures = set()
    for scenario in response["scenarios"]:
        decisions = scenario["decisions"]
        assert len(decisions) == 5
        assert len({decision["measure_id"] for decision in decisions}) == 5
        recomputed = simulate(decisions)
        assert recomputed["valid"] is True
        assert recomputed["budget"]["spent"] <= 100
        assert scenario["result"] == recomputed
        signatures.add(scenario["id"])
    assert len(signatures) == len(response["scenarios"])


def test_search_ranks_by_unrounded_objective(default_search):
    response, _ = default_search
    objectives = [tuple(scenario["objective_value"]) for scenario in response["scenarios"]]
    assert objectives == sorted(objectives, reverse=True)
    for scenario in response["scenarios"]:
        result = evaluate(scenario["decisions"])
        expected = objective_values(
            {
                "score": result["score"],
                "weakest": result["weakest_district"]["score"],
                "critical": len(result["critical"]),
                "category_deltas": result["category_deltas"],
                "focus_delta": 0.0,
            },
            "balanced",
        )
        assert tuple(scenario["objective_value"]) == expected


def test_repeat_requests_have_identical_results_except_timing(default_search):
    first, _ = default_search
    second = search(SearchRequest())
    assert first["scenarios"] == second["scenarios"]
    assert {k: v for k, v in first["search"].items() if k != "elapsed_ms"} == {
        k: v for k, v in second["search"].items() if k != "elapsed_ms"
    }


def test_search_respects_intersecting_budgets_exclusions_and_focus():
    request = SearchRequest(
        max_budget=90,
        reserve_budget=25,
        focus_district="Нура",
        exclude_measures=["M3", "M2"],
        priority="weakest_district",
        limit=3,
    )
    response = search(request)
    assert response["search"]["effective_budget"] == 75
    assert len(response["scenarios"]) == 3
    base = evaluate([])
    objectives = []
    for scenario in response["scenarios"]:
        assert scenario["result"]["valid"]
        assert scenario["result"]["budget"]["spent"] <= 75
        assert not {d["measure_id"] for d in scenario["decisions"]} & {"M3", "M2"}
        result = evaluate(scenario["decisions"])
        expected = (
            result["weakest_district"]["score"],
            result["score"],
            result["district_scores"]["Нура"] - base["district_scores"]["Нура"],
        )
        assert tuple(scenario["objective_value"]) == expected
        objectives.append(expected)
    assert objectives == sorted(objectives, reverse=True)


@pytest.mark.parametrize(
    "allowed",
    [
        {"M4", "M7", "M8", "M10", "M12"},
        {"M5", "M13", "M9", "M10", "M12"},
    ],
)
def test_assignment_search_obeys_same_district_conflicts(allowed):
    excluded = sorted(set(load_repository().measure_by_id) - allowed)
    response = search(SearchRequest(exclude_measures=excluded, limit=5))
    assert len(response["scenarios"]) == 5
    for scenario in response["scenarios"]:
        assert {decision["measure_id"] for decision in scenario["decisions"]} == allowed
        assert simulate(scenario["decisions"])["valid"] is True


@pytest.mark.parametrize(
    "constraint",
    [
        SearchRequest(max_budget=50),
        SearchRequest(reserve_budget=100),
        SearchRequest(exclude_measures=[f"M{i}" for i in range(1, 11)]),
        SearchRequest(exclude_measures=["M2", "M4", "M5", "M6", "M7", "M8", "M11", "M13", "M14"]),
    ],
)
def test_impossible_constraints_return_clear_empty_result(constraint):
    response = search(constraint)
    assert response["scenarios"] == []
    assert response["search"]["evaluated"] == 0
    assert response["search"]["truncated"] is False
    assert "невозможно" in " ".join(response["search"]["notes"])


@pytest.mark.parametrize(
    "values",
    [
        {"max_budget": -1},
        {"max_budget": 101},
        {"reserve_budget": -1},
        {"reserve_budget": 101},
        {"max_budget": float("nan")},
        {"max_budget": float("inf")},
        {"focus_district": "Unknown"},
        {"exclude_measures": ["M99"]},
        {"priority": "random"},
        {"limit": 2},
        {"limit": 6},
        {"unexpected": True},
    ],
)
def test_request_rejects_invalid_constraints(values):
    with pytest.raises(ValidationError):
        SearchRequest(**values)


def test_objective_semantics_and_focus_tiebreak():
    metrics: Metrics = {
        "score": 58.123456789,
        "weakest": 54.1,
        "critical": 1,
        "category_deltas": {"transport": 2.0, "ecology": 0.25, "social": 1.5, "safety": 0.5, "services": 0.0},
        "focus_delta": 3.125,
    }
    assert objective_values(metrics, "overall_score") == (58.123456789, 3.125)
    assert objective_values(metrics, "weakest_district") == (54.1, 58.123456789, 3.125)
    assert objective_values(metrics, "reduce_critical") == (-1.0, 58.123456789, 3.125)
    for category in metrics["category_deltas"]:
        assert objective_values(metrics, category) == (metrics["category_deltas"][category], 58.123456789, 3.125)
    assert objective_values(metrics, "balanced")[0] == pytest.approx(58.123456789 + 0.2 * 54.1 - 0.5 + 0.1 * 2.75)
    focused = {**metrics, "focus_delta": 4.0}
    assert objective_values(focused, "weakest_district") > objective_values(metrics, "weakest_district")
    fewer_critical = {**metrics, "score": 50.0, "critical": 0}
    assert objective_values(fewer_critical, "reduce_critical") > objective_values(metrics, "reduce_critical")
