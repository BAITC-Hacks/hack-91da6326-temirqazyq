"""Narrative links are verified and display values come only from engine facts."""

import pytest

from app.ai.contracts import Constraints, Narrative
from app.ai.evidence import facts_for, ground_narrative
from app.simulation.engine import simulate


def narrative(**updates):
    values = {
        "summary": "Индекс [fact:alpha.score.after].",
        "observations": [], "remaining_issues": [], "tradeoffs": [], "limitations": [],
        "evidence_refs": ["alpha.score.after"], "scenario_ids": ["alpha"],
    }
    values.update(updates)
    return Narrative(**values)


FACTS = {"alpha.score.after": 56.54307, "alpha.budget.spent": 95, "alpha.district": "Нура", "alpha.delta": -1.75}


def test_placeholder_substitution_preserves_engine_values_and_formats_only_display():
    value = narrative(
        summary="Индекс [fact:alpha.score.after]; район [fact:alpha.district].",
        observations=["Расход [fact:alpha.budget.spent]."],
        tradeoffs=["Изменение [fact:alpha.delta]."],
        evidence_refs=list(FACTS),
    )
    result = ground_narrative(value, FACTS, ["alpha"])
    assert result["summary"] == "Индекс 56.54; район Нура."
    assert result["observations"] == ["Расход 95."]
    assert result["tradeoffs"] == ["Изменение -1.75."]
    assert result["evidence"]["alpha.score.after"] == 56.54307
    assert result["source"] == "openai"
    assert value.summary.startswith("Индекс [fact:")


@pytest.mark.parametrize("identifiers", [[], ["unknown"], ["alpha", "foreign-session-id"]])
def test_unknown_or_missing_scenario_ids_are_rejected(identifiers):
    with pytest.raises(ValueError, match="сценарий"):
        ground_narrative(narrative(scenario_ids=identifiers), FACTS, ["alpha"])


def test_unknown_evidence_reference_is_rejected_even_when_not_used_in_text():
    with pytest.raises(ValueError, match="ссылку"):
        ground_narrative(narrative(evidence_refs=["alpha.score.after", "invented.probability"]), FACTS, ["alpha"])


def test_placeholder_must_be_listed_in_evidence_refs():
    with pytest.raises(ValueError, match="фактом"):
        ground_narrative(narrative(summary="Бюджет [fact:alpha.budget.spent]."), FACTS, ["alpha"])


def test_unknown_placeholder_is_rejected():
    with pytest.raises(ValueError, match="ссылку на факт"):
        ground_narrative(narrative(summary="Индекс [fact:invented.score]."), FACTS, ["alpha"])


@pytest.mark.parametrize("field", ["summary", "observations", "remaining_issues", "tradeoffs", "limitations"])
@pytest.mark.parametrize("text", ["Индекс 999999.91.", "Рост +3,14.", "Падение -4.5.", "Вероятность 20%."])
def test_bare_numeric_claims_in_every_narrative_field_are_rejected(field, text):
    changes = {field: text if field == "summary" else [text]}
    with pytest.raises(ValueError, match="Числа"):
        ground_narrative(narrative(**changes), FACTS, ["alpha"])


def test_correct_but_bare_engine_number_still_requires_reference():
    with pytest.raises(ValueError, match="Числа"):
        ground_narrative(narrative(summary="Индекс 56.54."), FACTS, ["alpha"])


def test_facts_include_requested_unchanged_focus_indicators_and_exact_decomposition():
    result = simulate([{"measure_id": "M12"}], preview=True)
    facts = facts_for([{"scenario_id": "alpha", "result": result}], Constraints(focus_district="Нура", analysis_indicators=["S1", "S2"]))
    assert facts["A.districts.Нура.before.S1"] == 38
    assert facts["A.districts.Нура.after.S1"] == 38
    assert facts["A.districts.Нура.delta.S1"] == 0
    assert facts["A.districts.Нура.after.S2"] == 35
    assert facts["A.districts.Есиль.delta.C2"] == 4.375
    assert facts["A.score_decomposition.total"] == result["score"]["delta"]
    assert facts["A.critical_after.count"] == 2
    assert facts["rules.critical_threshold"] == 40


def test_fact_aliases_are_short_stable_and_separate_from_server_ids():
    result = simulate([], preview=True)
    scenarios = [{"scenario_id": "a" * 32, "result": result}, {"scenario_id": "b" * 32, "result": result}, {"scenario_id": "c" * 32, "result": result}]
    facts = facts_for(scenarios, Constraints())
    assert facts["A.score.after"] == facts["B.score.after"] == facts["C.score.after"]
    assert all(not reference.startswith(tuple(row["scenario_id"] for row in scenarios)) for reference in facts)


def test_unchanged_critical_values_outside_focus_have_references():
    result = simulate([{"measure_id": "M12"}], preview=True)
    facts = facts_for([{"scenario_id": "alpha", "result": result}], Constraints(focus_district="Есиль", analysis_indicators=["C2"]))
    assert facts["A.districts.Нура.before.S1"] == facts["A.districts.Нура.after.S1"] == 38
    assert facts["A.districts.Нура.before.S2"] == facts["A.districts.Нура.after.S2"] == 35


@pytest.mark.parametrize("text", ["Индекс999999", "Index999999", "Рост²", "M9999", "S99", "M10.5", "Вероятность２０％"])
def test_glued_numbers_unknown_identifiers_and_unicode_digits_are_rejected(text):
    with pytest.raises(ValueError, match="Числа"):
        ground_narrative(narrative(summary=text), FACTS, ["alpha"])


def test_only_known_measure_and_indicator_ids_may_contain_bare_digits():
    result = ground_narrative(narrative(summary="Рассмотрены M10, M12 и показатели S1, S2, B1."), FACTS, ["alpha"])
    assert "M10" in result["summary"]
    assert "S1" in result["summary"]


@pytest.mark.parametrize("text", ["Индекс [fact:alpha.score.after", "[fact:", "Текст [fact:unknown"])
def test_malformed_fact_placeholders_are_rejected(text):
    with pytest.raises(ValueError, match="незавершённую"):
        ground_narrative(narrative(summary=text), FACTS, ["alpha"])


def test_known_uuid_and_original_field_paths_normalize_without_guessing():
    identifier = "abc0123456789defabc0123456789def0"
    facts = {"A.score.after": 56.54307, "A.districts.Нура.after.S1": 48, "A.districts.Нура.before.S1": 38, "A.districts.Нура.delta.S1": 10}
    old_reference = f"{identifier}.districts.Нура.indicators_after.S1"
    value = narrative(
        summary=f"Индекс [fact:{identifier}.score.after]; школы [fact:{old_reference}].",
        observations=["Изменение [fact:A.districts.Нура.indicator_deltas.S1]."],
        evidence_refs=[f"{identifier}.score.after", old_reference, "A.districts.Нура.indicator_deltas.S1"],
        scenario_ids=[identifier],
    )
    result = ground_narrative(value, facts, [identifier])
    assert result["summary"] == "Индекс 56.54; школы 48."
    assert result["observations"] == ["Изменение 10."]
    assert result["evidence_refs"] == ["A.score.after", "A.districts.Нура.after.S1", "A.districts.Нура.delta.S1"]
    assert result["evidence"] == {key: facts[key] for key in result["evidence_refs"]}


@pytest.mark.parametrize("reference", ["foreignuuid.score.after", "A.districts.Нура.indicators_after.S999", "A.districts.Nura.indicators_after.S1", "A.districts.Нура.S1.after", "A.score.result"])
def test_reference_normalization_never_guesses_unknown_ids_names_or_path_orders(reference):
    with pytest.raises(ValueError, match="неизвестную ссылку"):
        ground_narrative(narrative(summary=f"Факт [fact:{reference}].", evidence_refs=[reference]), {"A.score.after": 56.54, "A.districts.Нура.after.S1": 48}, ["alpha"])


def test_unknown_reference_diagnostics_are_bounded():
    references = [f"unknown{index}." + "x" * 1000 for index in range(5)]
    with pytest.raises(ValueError) as error:
        ground_narrative(narrative(evidence_refs=references), FACTS, ["alpha"])
    message = str(error.value)
    assert "unknown0." in message and "unknown2." in message
    assert "unknown3." not in message
    assert len(message) < 450
