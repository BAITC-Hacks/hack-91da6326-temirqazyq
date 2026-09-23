"""Regression for a reserve follow-up that leaves only seventy budget units."""

import asyncio
import json

import pytest

from app.ai.contracts import Constraints
from test_agent import (
    DECISIONS,
    finish,
    generation,
    harness,
    intent_response,
    narrative_response,
    tool_call,
)


def decisions(*measure_ids):
    return [
        {"measure_id": measure_id, "district": None if measure_id == "M12" else "Нура"}
        for measure_id in measure_ids
    ]


def previous_constraints():
    return Constraints(
        max_budget=90,
        excluded_measure_ids=["M3"],
        focus_district="Нура",
        analysis_indicators=["S1", "S2"],
        requested_scenario_count=3,
    )


def reject_optimizer(*args, **kwargs):
    raise AssertionError("AI candidate repair must not call the optimizer")


def function_output(inputs, call_id):
    return next(
        json.loads(item["output"])
        for item in inputs
        if item.get("type") == "function_call_output" and item["call_id"] == call_id
    )


def assert_preserved_constraints(value):
    expected = previous_constraints().model_dump()
    expected["reserve_budget"] = 30
    assert value == expected


def test_reserve_followup_repairs_cost_eighty_to_three_verified_affordable_candidates(harness, monkeypatch):
    monkeypatch.setattr("app.ai.tools.search", reject_optimizer)
    affordable = [
        decisions("M7", "M9", "M10", "M11", "M12"),
        decisions("M8", "M9", "M10", "M11", "M12"),
        decisions("M4", "M9", "M10", "M11", "M12"),
    ]

    def repair(inputs, **kwargs):
        rejected = function_output(inputs, "over-budget")["candidates"][0]
        assert not rejected["valid"]
        assert "score" not in rejected
        assert "USER_BUDGET_EXCEEDED" in {item["code"] for item in rejected["errors"]}
        budget = rejected["diagnostics"]["budget"]
        assert budget["spent"] == 80
        assert budget["limit"] == 70
        assert budget["over_by"] == 10
        return {
            "status": "completed",
            "output": [tool_call("evaluate_scenarios", {
                "candidates": [
                    {"name": f"Вариант {alias}", "decisions": candidate}
                    for alias, candidate in zip("ABC", affordable)
                ],
            }, "affordable-repair")],
        }

    manager, session, provider = harness([
        intent_response(reserve_budget=30, requested_scenario_count=None),
        generation(DECISIONS, "over-budget"),
        repair,
        narrative_response,
    ], ai_enabled=True, ai_allow_template_fallback=False)
    manager.store.update_session(session, constraints=previous_constraints().model_dump())
    result = asyncio.run(finish(manager, session, message="Нужно сохранить 30 единиц бюджета. Остальные условия сохрани."))

    assert result["status"] == "completed", result.get("error")
    assert len(provider.calls) == result["metadata"]["api_calls"] == 4
    assert result["repair_rounds"] == 1
    assert len(result["scenarios"]) == 3
    assert [row["result"]["budget"]["spent"] for row in result["scenarios"]] == [70, 66, 61]
    assert all(row["result"]["budget"]["remaining"] >= 30 for row in result["scenarios"])
    assert all(row["provenance"] == "llm_generated" for row in result["scenarios"])
    assert result["explanation"]["source"] == "openai"
    assert not result["fallback_used"]
    assert_preserved_constraints(result["constraints"])
    assert_preserved_constraints(manager.store.get_session(session)["constraints"])
    context = json.loads(provider.calls[1]["inputs"][-1]["content"])
    assert context["city_context"]["effective_budget"] == 70
    assert_preserved_constraints(context["constraints"])


@pytest.mark.parametrize("also_social_overflow", [False, True])
def test_exhausted_budget_repairs_explain_actual_cost_without_relaxing_constraints(harness, monkeypatch, also_social_overflow):
    monkeypatch.setattr("app.ai.tools.search", reject_optimizer)

    def invalid_round(round_index):
        candidates = [{"name": f"Черновик {round_index}", "decisions": DECISIONS}]
        if also_social_overflow:
            candidates.append({
                "name": f"Социальный черновик {round_index}",
                "decisions": decisions("M7", "M8", "M9", "M11", "M12"),
            })
        return {"status": "completed", "output": [tool_call(
            "evaluate_scenarios", {"candidates": candidates}, f"bad-round-{round_index}",
        )]}

    manager, session, provider = harness([
        intent_response(reserve_budget=30, requested_scenario_count=None),
        invalid_round(1), invalid_round(2), invalid_round(3),
    ], ai_enabled=True, ai_allow_template_fallback=False)
    manager.store.update_session(session, constraints=previous_constraints().model_dump())
    result = asyncio.run(finish(manager, session, message="Нужно сохранить 30 единиц бюджета."))

    assert result["status"] == "failed"
    assert result["error"]["code"] == "NO_VERIFIED_CANDIDATES"
    assert "70" in result["error"]["message"]
    assert "80" in result["error"]["message"]
    assert result["repair_rounds"] == 2
    assert len(provider.calls) == result["metadata"]["api_calls"] == 4
    assert result["scenarios"] == []
    assert manager.store.list_scenarios(session) == []
    assert result["explanation"] is None
    assert not result["fallback_used"]
    assert_preserved_constraints(result["constraints"])
    assert_preserved_constraints(manager.store.get_session(session)["constraints"])
    feedback = function_output(provider.calls[3]["inputs"], "bad-round-2")
    assert feedback["verified_count"] == 0
    codes = {error["code"] for candidate in feedback["candidates"] for error in candidate["errors"]}
    assert "USER_BUDGET_EXCEEDED" in codes
    if also_social_overflow:
        assert "CATEGORY_LIMIT" in codes
