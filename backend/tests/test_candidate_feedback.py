"""Draft feedback uses repository costs and retains every hard constraint."""

import asyncio
import json
import sqlite3

import pytest

from app.ai import tools as module
from app.ai.constraints import candidate_diagnostics, effective_budget
from app.ai.contracts import Constraints
from app.ai.tools import ToolDispatcher, canonical_decisions, dataset_version
from app.simulation.engine import simulate
from app.storage import Store


def decisions(*ids):
    return [{"measure_id": identifier, "district": None if identifier == "M12" else "Нура"} for identifier in ids]


BAD = decisions("M7", "M8", "M9", "M10", "M12")
BOUNDARY = decisions("M7", "M9", "M10", "M11", "M12")
VALID = decisions("M8", "M9", "M10", "M11", "M12")


@pytest.fixture
def dispatcher(tmp_path):
    store = Store(tmp_path / "feedback.sqlite3")
    constraints = Constraints(
        max_budget=90, reserve_budget=30, focus_district="Нура",
        analysis_indicators=["S1", "S2"], excluded_measure_ids=["M3"],
    )
    return ToolDispatcher(store, store.create_session(), "feedback-run", constraints, [])


def evaluate(dispatcher, *drafts):
    return asyncio.run(dispatcher.dispatch("evaluate_scenarios", {
        "candidates": [{"name": f"Вариант {index}", "decisions": draft} for index, draft in enumerate(drafts)],
    }))


def latest_log(dispatcher):
    with sqlite3.connect(dispatcher.store.path) as connection:
        status, summary = connection.execute(
            "SELECT status, summary_json FROM ai_tool_logs WHERE run_id = ? ORDER BY rowid DESC LIMIT 1",
            (dispatcher.run_id,),
        ).fetchone()
    return status, json.loads(summary)


def test_budget_and_category_failures_include_actual_costs_without_simulation(dispatcher, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid drafts must never be simulated or optimized")

    monkeypatch.setattr(module, "simulate", forbidden)
    monkeypatch.setattr(module, "search", forbidden)
    assert dispatcher.last_evaluation is None

    batch = evaluate(dispatcher, BAD)

    assert batch["valid"]  # The batch structure was accepted; the draft was not.
    assert batch["verified_count"] == 0
    assert dispatcher.last_evaluation == batch
    rejected = batch["candidates"][0]
    assert not rejected["valid"]
    assert "score" not in rejected
    assert dispatcher.scenarios == []
    errors = {item["code"]: item["message"] for item in rejected["errors"]}
    assert set(errors) == {"USER_BUDGET_EXCEEDED", "CATEGORY_LIMIT"}
    assert all(str(value) in errors["USER_BUDGET_EXCEEDED"] for value in (80, 70, 10))
    diagnosis = rejected["diagnostics"]
    assert diagnosis["cost_complete"]
    assert diagnosis["budget"] == {"spent": 80, "limit": 70, "over_by": 10}
    assert diagnosis["category_counts"] == {"transport": 0, "ecology": 0, "social": 3, "safety": 1, "services": 1}
    assert diagnosis["max_per_category"] == 2
    assert diagnosis["cost_breakdown"] == [
        {"measure_id": "M7", "district": "Нура", "category": "social", "cost": 24},
        {"measure_id": "M8", "district": "Нура", "category": "social", "cost": 20},
        {"measure_id": "M9", "district": "Нура", "category": "social", "cost": 10},
        {"measure_id": "M10", "district": "Нура", "category": "safety", "cost": 12},
        {"measure_id": "M12", "district": None, "category": "services", "cost": 14},
    ]
    status, summary = latest_log(dispatcher)
    assert status == "rejected"
    assert set(summary["error_codes"]) == set(errors)


def test_exact_effective_budget_boundary_is_accepted_and_conditions_are_preserved(dispatcher):
    previous = dispatcher.constraints.model_dump()
    result = evaluate(dispatcher, BOUNDARY)["candidates"][0]
    assert effective_budget(dispatcher.constraints) == 70
    assert result["valid"]
    assert result["budget"]["spent"] == 70
    assert result["budget"]["remaining"] == 30
    assert dispatcher.constraints.model_dump() == previous
    assert dispatcher.scenarios[0]["constraints"] == previous
    assert latest_log(dispatcher) == ("ok", {"verified_scenarios": 1, "error_codes": []})


def test_analysis_indicators_do_not_require_the_expensive_corresponding_measures(dispatcher):
    draft = decisions("M4", "M9", "M10", "M11", "M12")
    result = evaluate(dispatcher, draft)["candidates"][0]
    assert result["valid"]
    assert result["budget"]["spent"] == 61
    assert set(result["district_focus"]["indicators"]) == {"S1", "S2"}
    assert dispatcher.constraints.analysis_indicators == ["S1", "S2"]


def test_legacy_invalid_cache_is_revalidated_and_duplicate_keeps_correct_diagnostics(dispatcher):
    key = dispatcher._cache_key(canonical_decisions(BAD))
    dispatcher.store.cache_set(dispatcher.session_id, key, {
        "valid": False, "errors": [{"code": "USER_BUDGET_EXCEEDED", "message": "Old generic error"}],
    })

    first = evaluate(dispatcher, BAD)["candidates"][0]
    duplicate = evaluate(dispatcher, list(reversed(BAD)))["candidates"][0]

    assert set(error["code"] for error in first["errors"]) == {"CATEGORY_LIMIT", "USER_BUDGET_EXCEEDED"}
    assert first["diagnostics"]["budget"] == {"spent": 80, "limit": 70, "over_by": 10}
    assert dispatcher.store.cache_get(dispatcher.session_id, key)["diagnostics"] == first["diagnostics"]
    assert duplicate["duplicate"]
    assert duplicate["diagnostics"] == first["diagnostics"]
    assert "score" not in first and "score" not in duplicate


def test_unknown_measure_cost_is_not_presented_as_a_complete_total(dispatcher):
    draft = decisions("M99", "M8", "M9", "M10", "M12")
    result = evaluate(dispatcher, draft)["candidates"][0]
    diagnosis = result["diagnostics"]
    assert not result["valid"]
    assert "UNKNOWN_MEASURE" in {error["code"] for error in result["errors"]}
    assert not diagnosis["cost_complete"]
    assert diagnosis["budget"] == {"spent": None, "limit": 70, "over_by": None, "known_spent": 56}
    assert diagnosis["unknown_measure_ids"] == ["M99"]
    assert diagnosis["cost_breakdown"][0]["cost"] is None
    assert diagnosis["cost_breakdown"][0]["category"] is None
    assert "score" not in result


def test_duplicate_measure_costs_and_category_counts_match_validator(dispatcher):
    draft = decisions("M7", "M7", "M9", "M10", "M12")
    result = evaluate(dispatcher, draft)["candidates"][0]
    assert {error["code"] for error in result["errors"]} == {"DUPLICATE_MEASURE", "CATEGORY_LIMIT", "USER_BUDGET_EXCEEDED"}
    assert result["diagnostics"]["budget"] == {"spent": 84, "limit": 70, "over_by": 14}
    assert result["diagnostics"]["category_counts"]["social"] == 3
    assert len(result["diagnostics"]["cost_breakdown"]) == 5


def test_mixed_evaluation_log_records_rejected_candidate_errors(dispatcher):
    batch = evaluate(dispatcher, BAD, VALID)
    assert batch["valid"]
    assert batch["verified_count"] == 1
    assert [item["valid"] for item in batch["candidates"]] == [False, True]
    status, summary = latest_log(dispatcher)
    assert status == "partial"
    assert set(summary["error_codes"]) == {"CATEGORY_LIMIT", "USER_BUDGET_EXCEEDED"}


def test_malformed_evaluation_updates_last_evaluation_and_log(dispatcher):
    result = asyncio.run(dispatcher.dispatch("evaluate_scenarios", {"candidates": []}))
    assert not result["valid"]
    assert dispatcher.last_evaluation == result
    assert latest_log(dispatcher)[0] == "rejected"


@pytest.mark.parametrize("constraint_patch,error_code", [
    ({}, "USER_BUDGET_EXCEEDED"),
    ({"reserve_budget": 0, "excluded_measure_ids": ["M3", "M7"]}, "EXCLUDED_MEASURE"),
    ({"reserve_budget": 0, "locked_decisions": [{"measure_id": "M4", "district": "Нура"}]}, "LOCKED_DECISION_MISSING"),
])
def test_model_compare_tool_cannot_bypass_current_hard_constraints(dispatcher, constraint_patch, error_code):
    dispatcher.constraints = Constraints.model_validate({**dispatcher.constraints.model_dump(), **constraint_patch})
    ids = []
    for draft in [VALID, decisions("M7", "M8", "M10", "M11", "M12")]:
        result = simulate(draft)
        assert result["valid"]
        row = dispatcher.store.save_scenario(
            dispatcher.session_id, decisions=draft, result=result, provenance="manual",
            constraints=Constraints().model_dump(), dataset_version=dataset_version(),
        )
        ids.append(row["scenario_id"])
    # Even if an earlier item is valid, no item is accepted until all are checked.
    result = asyncio.run(dispatcher.dispatch("compare_scenarios", {"scenario_ids": ids}))
    assert not result["valid"]
    assert error_code in {error["code"] for error in result["errors"]}
    assert dispatcher.scenarios == []
    assert dispatcher.facts == {}
    assert "score" not in result


def test_diagnostics_never_recommend_or_generate_replacement_decisions(dispatcher):
    diagnosis = candidate_diagnostics(BAD, dispatcher.constraints)
    assert set(diagnosis) == {"budget", "cost_complete", "category_counts", "max_per_category", "cost_breakdown"}
    assert [item["measure_id"] for item in diagnosis["cost_breakdown"]] == [item["measure_id"] for item in BAD]
