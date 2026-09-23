import asyncio
import json
import sqlite3

import pytest

from app.ai import tools as module
from app.ai.contracts import Constraints
from app.ai.tools import ToolDispatcher, build_facts, canonical_decisions, dataset_version, tool_schemas
from app.simulation.engine import simulate
from app.storage import Store


@pytest.fixture
def demo():
    return [
        {"measure_id": "M7", "district": "Нура"}, {"measure_id": "M8", "district": "Нура"},
        {"measure_id": "M10", "district": "Нура"}, {"measure_id": "M12", "district": None},
        {"measure_id": "M5", "district": "Сарыарка"},
    ]


@pytest.fixture
def dispatcher(tmp_path):
    store = Store(tmp_path / "app.sqlite3")
    return ToolDispatcher(store, store.create_session(), "run", Constraints(), [])


def call(dispatcher, name, arguments):
    return asyncio.run(dispatcher.dispatch(name, arguments))


def evaluate(dispatcher, decisions, name="Draft"):
    return call(dispatcher, "evaluate_scenarios", {"candidates": [{"name": name, "decisions": decisions}]})


def test_verified_scenario_is_calculated_persisted_and_has_evidence(dispatcher, demo):
    dispatcher.constraints.focus_district = "Нура"
    dispatcher.constraints.analysis_indicators = ["S1", "S2"]
    result = evaluate(dispatcher, demo)["candidates"][0]
    assert result["valid"]
    assert result["score"]["after"] == pytest.approx(56.54307)
    assert result["budget"]["spent"] == 95
    assert result["district_focus"]["indicators"]["S1"]["after"] == 48
    assert result["district_focus"]["indicators"]["S2"]["after"] == 43.75
    row = dispatcher.scenarios[0]
    assert row["provenance"] == "llm_generated"
    assert dispatcher.store.get_scenario(dispatcher.session_id, row["scenario_id"]) == row
    assert dispatcher.facts[f"{result['scenario_id']}.score.after"] == result["score"]["after"]
    assert dispatcher.facts[f"{row['scenario_id']}.districts.Нура.indicators_after.S2"] == 43.75
    assert "districts" not in result
    assert len(json.dumps(result)) < len(json.dumps(row["result"]))


def test_duplicate_drafts_ignore_names_order_and_repeated_calls(dispatcher, demo, monkeypatch):
    actual_simulate = module.simulate
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return actual_simulate(*args, **kwargs)

    monkeypatch.setattr(module, "simulate", counted)
    first = evaluate(dispatcher, demo)["candidates"][0]
    second = evaluate(dispatcher, list(reversed(demo)), name="Different label")["candidates"][0]
    assert second["duplicate"]
    assert first["scenario_id"] == second["scenario_id"]
    assert len(dispatcher.scenarios) == 1
    assert len(calls) == 1
    restarted = ToolDispatcher(dispatcher.store, dispatcher.session_id, "another-run", Constraints(), [])
    cached = evaluate(restarted, demo)["candidates"][0]
    assert cached["cached"]
    assert cached["scenario_id"] == first["scenario_id"]
    # A new run revalidates persisted metrics, but same-run duplicates do not repeat work.
    assert len(calls) == 2


@pytest.mark.parametrize("field,value", [("score", 99), ("cost", 1), ("effects", {"S1": 100})])
def test_model_supplied_numbers_are_rejected(dispatcher, demo, field, value):
    candidate = {"name": "Fabricated", "decisions": demo, field: value}
    output = call(dispatcher, "evaluate_scenarios", {"candidates": [candidate]})["candidates"][0]
    assert not output["valid"]
    assert "score" not in output
    assert dispatcher.scenarios == []


def test_invalid_candidate_errors_can_be_repaired_without_invalid_score(dispatcher, demo):
    wrong = [dict(item) for item in demo]
    wrong[0]["district"] = None
    bad = evaluate(dispatcher, wrong)["candidates"][0]
    assert not bad["valid"]
    assert "score" not in bad
    assert "DISTRICT_REQUIRED" in {error["code"] for error in bad["errors"]}
    assert evaluate(dispatcher, demo)["candidates"][0]["valid"]
    assert len(dispatcher.scenarios) == 1


@pytest.mark.parametrize("constraints,code", [
    (Constraints(max_budget=90), "USER_BUDGET_EXCEEDED"),
    (Constraints(reserve_budget=20), "USER_BUDGET_EXCEEDED"),
    (Constraints(excluded_measure_ids=["M5"]), "EXCLUDED_MEASURE"),
    (Constraints(allowed_districts=["Нура"]), "DISTRICT_NOT_ALLOWED"),
    (Constraints(locked_decisions=[{"measure_id": "M4", "district": "Есиль"}]), "LOCKED_DECISION_MISSING"),
])
def test_candidate_enforces_user_hard_constraints(dispatcher, demo, constraints, code):
    dispatcher.constraints = constraints
    result = evaluate(dispatcher, demo)["candidates"][0]
    assert not result["valid"]
    assert code in {error["code"] for error in result["errors"]}
    assert "score" not in result


def test_unknown_tool_and_search_in_ai_mode_never_execute_search(dispatcher, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("AI mode must not execute optimizer")

    monkeypatch.setattr(module, "search", forbidden)
    for name in ["search_scenarios", "exec", "shell", "fetch_url"]:
        result = call(dispatcher, name, {})
        assert not result["valid"]
        assert result["errors"][0]["code"] == "UNKNOWN_TOOL"


def test_batch_bounds_and_whitelist_arguments_are_enforced(dispatcher, demo):
    for values in [[], [{"name": "draft", "decisions": demo}] * 4]:
        assert not call(dispatcher, "evaluate_scenarios", {"candidates": values})["valid"]
    assert not call(dispatcher, "get_city_context", {"url": "https://example.com"})["valid"]
    context = call(dispatcher, "get_city_context", {})
    assert len(context["districts"]) == 5
    assert len(context["measures"]) == 14
    assert context["dataset_version"] == dataset_version()


def test_mixed_batch_preserves_valid_candidates(dispatcher, demo):
    result = call(dispatcher, "evaluate_scenarios", {"candidates": [
        {"name": "Bad extra field", "decisions": demo, "cost": 0},
        {"name": "Good", "decisions": demo},
    ]})
    assert not result["candidates"][0]["valid"]
    assert result["candidates"][1]["valid"]
    assert len(dispatcher.scenarios) == 1


def test_compare_loads_only_current_session_and_computes_differences(dispatcher, demo):
    first = evaluate(dispatcher, demo)["candidates"][0]
    other = [dict(item) for item in demo]
    other[-1] = {"measure_id": "M11", "district": "Алматы"}
    second = evaluate(dispatcher, other)["candidates"][0]
    result = call(dispatcher, "compare_scenarios", {"scenario_ids": [first["scenario_id"], second["scenario_id"]]})
    assert result["valid"]
    difference = result["differences_b_minus_a"][0]
    assert difference["score"] == pytest.approx(second["score"]["after"] - first["score"]["after"])
    assert difference["spent"] == -15
    assert difference["critical_count"] == 1
    other_session = ToolDispatcher(dispatcher.store, dispatcher.store.create_session(), "run", Constraints(), [])
    inaccessible = call(other_session, "compare_scenarios", {"scenario_ids": [first["scenario_id"], second["scenario_id"]]})
    assert not inaccessible["valid"]
    assert inaccessible["errors"][0]["code"] == "SCENARIO_NOT_FOUND"


def test_algorithmic_search_filters_locked_and_allowed_without_weakening(dispatcher, demo, monkeypatch):
    dispatcher.mode = "algorithmic"
    dispatcher.constraints = Constraints(allowed_districts=["Нура"])
    valid = [dict(item) for item in demo]
    valid[-1]["district"] = "Нура"
    seen = []

    def fake_search(request):
        seen.append(request)
        return {"scenarios": [{"name": "Disallowed", "decisions": demo}, {"name": "Allowed", "decisions": valid}], "search": {"truncated": True}}

    monkeypatch.setattr(module, "search", fake_search)
    result = call(dispatcher, "search_scenarios", {"constraints": dispatcher.constraints.model_dump()})
    assert len(seen) == 1
    assert result["limited_search"]
    assert len(dispatcher.scenarios) == 1
    assert dispatcher.scenarios[0]["provenance"] == "algorithmic"
    assert all(item["district"] in {None, "Нура"} for item in dispatcher.scenarios[0]["decisions"])
    assert "не доказывает невозможность" in result["note"]
    weakened = call(dispatcher, "search_scenarios", {"constraints": Constraints().model_dump()})
    assert not weakened["valid"]
    assert len(seen) == 1


def test_canonical_decisions_and_facts_are_order_invariant(demo):
    assert canonical_decisions(demo) == canonical_decisions(list(reversed(demo)))
    omitted_null = [dict(item) for item in demo]
    omitted_null[3].pop("district")
    assert canonical_decisions(demo) == canonical_decisions(omitted_null)
    facts = build_facts([{"scenario_id": "abc", "result": simulate(demo)}])
    assert facts["abc.critical_after.count"] == 0
    assert facts["abc.budget.spent"] == 95


def test_all_tool_schema_objects_are_strict_and_all_properties_required():
    def inspect(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value.get("properties", {}))
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    for definition in tool_schemas("algorithmic"):
        assert definition["strict"] is True
        inspect(definition["parameters"])


def test_cached_candidate_and_compare_recompute_persisted_metrics(dispatcher, demo):
    first = evaluate(dispatcher, demo)["candidates"][0]
    other = [dict(item) for item in demo]
    other[-1] = {"measure_id": "M11", "district": "Алматы"}
    second = evaluate(dispatcher, other)["candidates"][0]
    row = dispatcher.scenarios[0]
    row["result"]["score"]["after"] = 999999
    with sqlite3.connect(dispatcher.store.path) as connection:
        connection.execute("UPDATE scenarios SET result_json = ? WHERE scenario_id = ?", (json.dumps(row["result"]), row["scenario_id"]))
    restarted = ToolDispatcher(dispatcher.store, dispatcher.session_id, "new-run", Constraints(), [])
    cached = evaluate(restarted, demo)["candidates"][0]
    assert cached["score"]["after"] == pytest.approx(56.54307)
    comparison = call(restarted, "compare_scenarios", {"scenario_ids": [first["scenario_id"], second["scenario_id"]]})
    assert comparison["valid"]
    assert comparison["scenarios"][0]["score"]["after"] == pytest.approx(56.54307)
    assert restarted.facts[f"{first['scenario_id']}.score.after"] == pytest.approx(56.54307)


def test_compare_rejects_persisted_invalid_decisions(dispatcher, demo):
    first = evaluate(dispatcher, demo)["candidates"][0]
    other = [dict(item) for item in demo]
    other[-1] = {"measure_id": "M11", "district": "Алматы"}
    second = evaluate(dispatcher, other)["candidates"][0]
    with sqlite3.connect(dispatcher.store.path) as connection:
        connection.execute("UPDATE scenarios SET decisions_json = ? WHERE scenario_id = ?", (json.dumps(demo[:4]), first["scenario_id"]))
    result = call(dispatcher, "compare_scenarios", {"scenario_ids": [first["scenario_id"], second["scenario_id"]]})
    assert not result["valid"]
    assert "score" not in result
