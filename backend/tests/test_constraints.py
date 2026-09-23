import pytest
from pydantic import ValidationError

from app.ai.constraints import effective_budget, merge_intent, validate_candidate_constraints, validate_constraints
from app.ai.contracts import Constraints, Intent


def intent(**updates):
    values = {field: None for field in Constraints.model_fields}
    values.update(operation="generate", clear_fields=[], clarification=None, unsupported_conditions=[])
    values.update(updates)
    return Intent.model_validate(values)


def test_followup_preserves_prior_exclusions_focus_and_budget():
    first = merge_intent(Constraints(), intent(max_budget=90, excluded_measure_ids=["M3"], focus_district="Нура", analysis_indicators=["S1", "S2"]))
    second = merge_intent(first, intent(reserve_budget=20))
    assert second.max_budget == 90
    assert second.excluded_measure_ids == ["M3"]
    assert second.focus_district == "Нура"
    assert second.analysis_indicators == ["S1", "S2"]
    assert effective_budget(second) == 80
    assert second.allowed_districts is None


def test_intent_locked_decisions_are_converted_to_normalized_decisions():
    result = merge_intent(Constraints(), intent(locked_decisions=[{"measure_id": "M7", "district": "Нура"}]))
    assert result.locked_decisions[0].measure_id == "M7"
    assert result.locked_decisions[0].district == "Нура"
    assert validate_constraints(result)["valid"]


def test_explicit_clear_only_resets_named_fields():
    constraints = Constraints(max_budget=90, reserve_budget=20, excluded_measure_ids=["M3"], focus_district="Нура")
    result = merge_intent(constraints, intent(clear_fields=["focus_district", "excluded_measure_ids"]))
    assert result.focus_district is None
    assert result.excluded_measure_ids == []
    assert result.max_budget == 90
    assert result.reserve_budget == 20
    with pytest.raises(ValueError):
        merge_intent(result, intent(clear_fields=["nonexistent"]))


def test_incomplete_model_lists_cannot_silently_remove_hard_conditions():
    initial = Constraints(excluded_measure_ids=["M3"], locked_decisions=[{"measure_id": "M7", "district": "Нура"}])
    unchanged = merge_intent(initial, intent(excluded_measure_ids=[], locked_decisions=[]))
    assert unchanged == initial
    extended = merge_intent(initial, intent(excluded_measure_ids=["M1"]))
    assert extended.excluded_measure_ids == ["M1", "M3"]
    removed = merge_intent(extended, intent(clear_fields=["excluded_measure_ids"], excluded_measure_ids=["M1"]))
    assert removed.excluded_measure_ids == ["M1"]
    assert removed.locked_decisions == initial.locked_decisions


@pytest.mark.parametrize("values", [{"max_budget": -1}, {"reserve_budget": -1}, {"max_budget": 101}, {"reserve_budget": 101}, {"max_budget": float("nan")}, {"requested_scenario_count": 4}])
def test_invalid_constraint_ranges_are_rejected(values):
    with pytest.raises(ValidationError):
        Constraints(**values)


@pytest.mark.parametrize("values,code", [
    ({"excluded_measure_ids": ["M99"]}, "UNKNOWN_MEASURE"),
    ({"focus_district": "Nura?"}, "UNKNOWN_DISTRICT"),
    ({"allowed_districts": ["other"]}, "UNKNOWN_DISTRICT"),
    ({"preferred_categories": ["tourism"]}, "UNKNOWN_CATEGORY"),
    ({"analysis_indicators": ["S9"]}, "UNKNOWN_INDICATOR"),
])
def test_unknown_identifiers_require_clarification_without_guessing(values, code):
    check = validate_constraints(Constraints(**values))
    assert not check["valid"]
    assert check["clarification_required"]
    assert not check["contradiction"]
    assert code in {item["code"] for item in check["errors"]}


@pytest.mark.parametrize("constraints,code", [
    (Constraints(excluded_measure_ids=["M7"], locked_decisions=[{"measure_id": "M7", "district": "Нура"}]), "LOCKED_EXCLUDED"),
    (Constraints(max_budget=10), "BUDGET_CONTRADICTION"),
    (Constraints(allowed_districts=[]), "INSUFFICIENT_MEASURES"),
    (Constraints(allowed_districts=["Есиль"], locked_decisions=[{"measure_id": "M7", "district": "Нура"}]), "LOCKED_DISTRICT_FORBIDDEN"),
    (Constraints(max_budget=20, locked_decisions=[{"measure_id": "M7", "district": "Нура"}]), "LOCKED_BUDGET_EXCEEDED"),
])
def test_proven_constraint_contradictions_are_distinguished(constraints, code):
    check = validate_constraints(constraints)
    assert check["contradiction"]
    assert code in {item["code"] for item in check["errors"]}


def test_focus_and_preferences_do_not_become_hard_assignment_constraints():
    constraints = Constraints(focus_district="Нура", preferred_categories=["social"])
    assert validate_candidate_constraints([{"measure_id": "M4", "district": "Есиль"}], constraints) == []
    constraints.allowed_districts = ["Нура"]
    assert validate_candidate_constraints([{"measure_id": "M4", "district": "Есиль"}], constraints)[0]["code"] == "DISTRICT_NOT_ALLOWED"


def test_locked_decision_includes_exact_district_assignment():
    constraints = Constraints(locked_decisions=[{"measure_id": "M7", "district": "Нура"}])
    errors = validate_candidate_constraints([{"measure_id": "M7", "district": "Есиль"}], constraints)
    assert any(item["code"] == "LOCKED_DECISION_MISSING" for item in errors)


def test_intent_requires_all_structured_fields_and_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        Intent(operation="generate")
    with pytest.raises(ValidationError):
        intent(score=90)
