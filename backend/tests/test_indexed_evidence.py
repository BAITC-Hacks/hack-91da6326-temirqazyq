"""Indexed references resolve only to scalar fields from actual engine lists."""

import asyncio
import json

import pytest

from app.ai.contracts import Constraints, Narrative
from app.ai.evidence import facts_for, ground_narrative
from app.simulation.engine import simulate
from test_agent import finish, generation, harness, intent_response, text_response


DECISIONS = [
    {"measure_id": "M4", "district": "Нура"},
    {"measure_id": "M9", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M11", "district": "Нура"},
    {"measure_id": "M12", "district": None},
]
IDENTIFIER = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def engine_facts():
    result = simulate(DECISIONS)
    assert result["valid"] and result["critical_after"] and result["activated_synergies"]
    rows = [{"scenario_id": IDENTIFIER, "result": result}]
    return facts_for(rows, Constraints()), result


def narrative(**updates):
    values = {
        "summary": "Сопоставлены синергия и оставшийся критический показатель.",
        "observations": [], "remaining_issues": [], "tradeoffs": [], "limitations": [],
        "evidence_refs": ["A.activated_synergies[0].effects.B1", "A.critical_after[0].value"],
        "scenario_ids": [IDENTIFIER],
    }
    values.update(updates)
    return Narrative(**values)


def display(value):
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def test_indexed_facts_are_exact_engine_fields_including_nested_measure_ids(engine_facts):
    facts, result = engine_facts
    for collection in ("critical_before", "critical_after"):
        for index, item in enumerate(result[collection]):
            for field, value in item.items():
                assert facts[f"A.{collection}.{index}.{field}"] == value
    for index, synergy in enumerate(result["activated_synergies"]):
        assert facts[f"A.activated_synergies.{index}.district"] == synergy["district"]
        assert facts[f"A.activated_synergies.{index}.measure_ids.count"] == len(synergy["measure_ids"])
        for offset, measure_id in enumerate(synergy["measure_ids"]):
            assert facts[f"A.activated_synergies.{index}.measure_ids.{offset}"] == measure_id
        for indicator, value in synergy["effects"].items():
            assert facts[f"A.activated_synergies.{index}.effects.{indicator}"] == value


def test_screenshot_bracket_references_are_normalized_to_known_facts(engine_facts):
    facts, result = engine_facts
    grounded = ground_narrative(narrative(), facts, [IDENTIFIER])
    assert grounded["evidence_refs"] == ["A.activated_synergies.0.effects.B1", "A.critical_after.0.value"]
    assert grounded["evidence"] == {
        "A.activated_synergies.0.effects.B1": result["activated_synergies"][0]["effects"]["B1"],
        "A.critical_after.0.value": result["critical_after"][0]["value"],
    }


@pytest.mark.parametrize("bracket_refs", [False, True])
def test_bracket_placeholders_render_complete_scalar_values(engine_facts, bracket_refs):
    facts, result = engine_facts
    references = ["A.activated_synergies.0.effects.B1", "A.critical_after.0.value"]
    if bracket_refs:
        references = ["A.activated_synergies[0].effects.B1", "A.critical_after[0].value"]
    value = narrative(
        summary="Синергия: [fact:A.activated_synergies[0].effects.B1]; показатель: [fact:A.critical_after[0].value].",
        evidence_refs=references,
    )
    grounded = ground_narrative(value, facts, [IDENTIFIER])
    assert grounded["summary"] == (
        f"Синергия: {display(result['activated_synergies'][0]['effects']['B1'])}; "
        f"показатель: {display(result['critical_after'][0]['value'])}."
    )
    assert "[fact:" not in grounded["summary"]


def test_known_uuid_and_nested_brackets_resolve_without_changing_identity(engine_facts):
    facts, result = engine_facts
    reference = f"{IDENTIFIER}.activated_synergies[0].measure_ids[1]"
    value = narrative(summary=f"Мера: [fact:{reference}].", evidence_refs=[reference])
    grounded = ground_narrative(value, facts, [IDENTIFIER])
    assert grounded["summary"] == f"Мера: {result['activated_synergies'][0]['measure_ids'][1]}."
    assert grounded["evidence_refs"] == ["A.activated_synergies.0.measure_ids.1"]
    assert grounded["scenario_ids"] == [IDENTIFIER]


def test_dot_and_bracket_references_are_deduplicated_after_normalization(engine_facts):
    facts, _ = engine_facts
    references = ["A.critical_after[0].value", "A.critical_after.0.value", f"{IDENTIFIER}.critical_after[0].value"]
    grounded = ground_narrative(narrative(evidence_refs=references), facts, [IDENTIFIER])
    assert grounded["evidence_refs"] == ["A.critical_after.0.value"]


@pytest.mark.parametrize("reference", [
    "A.critical_after[999].value",
    "A.critical_after[-1].value",
    "A.critical_after[00].value",
    "A.critical_after[+0].value",
    "A.critical_after[0.0].value",
    "A.critical_after[0:1].value",
    "A.critical_after[*].value",
    "A.critical_after[].value",
    "A.critical_after[0+0].value",
    "A.critical_after['0'].value",
    "A.critical_after[0].unknown",
    "A.critical_after[0].__class__",
    "A.critical_after[0].constructor",
    "A.critical_after[0]..value",
    "A.critical_after[0][0].value",
    "A.activated_synergies[0].effects.S999",
    "A.activated_synergies[0].effects.__proto__",
    "A.activated_synergies[0].measure_ids[99]",
    "A.critical_after[__import__('os')].value",
    "foreign-scenario.critical_after[0].value",
    "D.critical_after[0].value",
])
def test_unknown_indexes_fields_and_expression_syntax_are_never_guessed(engine_facts, reference):
    facts, _ = engine_facts
    with pytest.raises(ValueError, match="неизвестную ссылку"):
        ground_narrative(narrative(evidence_refs=[reference]), facts, [IDENTIFIER])
    with pytest.raises(ValueError):
        ground_narrative(narrative(summary=f"Значение: [fact:{reference}]."), facts, [IDENTIFIER])


def test_indexed_placeholder_still_requires_its_own_evidence_reference(engine_facts):
    facts, _ = engine_facts
    value = narrative(summary="Значение: [fact:A.critical_after[0].value].", evidence_refs=["A.critical_after"])
    with pytest.raises(ValueError, match="фактом"):
        ground_narrative(value, facts, [IDENTIFIER])


def test_valid_indexed_reference_does_not_authorize_a_fabricated_number(engine_facts):
    facts, _ = engine_facts
    with pytest.raises(ValueError, match="Числа"):
        ground_narrative(narrative(summary="Показатель вырос до 999."), facts, [IDENTIFIER])


def test_empty_collection_never_creates_a_phantom_element():
    result = simulate([], preview=True)
    facts = facts_for([{"scenario_id": IDENTIFIER, "result": result}], Constraints())
    assert facts["A.activated_synergies"] == []
    assert "A.activated_synergies.0.effects.B1" not in facts
    with pytest.raises(ValueError, match="неизвестную ссылку"):
        ground_narrative(narrative(evidence_refs=["A.activated_synergies[0].effects.B1"]), facts, [IDENTIFIER])


def test_agent_accepts_screenshot_references_and_placeholders_without_a_repair_call(harness):
    def explanation(inputs, **kwargs):
        context = json.loads(inputs[-1]["content"])
        value = narrative(
            summary="Синергия: [fact:A.activated_synergies[0].effects.B1]; показатель: [fact:A.critical_after[0].value].",
            scenario_ids=context["scenario_ids"],
        )
        return text_response(value.model_dump())

    manager, session, provider = harness([
        intent_response(), generation(DECISIONS), explanation,
    ], ai_enabled=True, ai_allow_template_fallback=False)
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "completed", result.get("error")
    assert result["explanation"]["source"] == "openai"
    assert not result["fallback_used"]
    assert result["explanation_repair_rounds"] == 0
    assert len(provider.calls) == 3
    assert result["explanation"]["evidence_refs"] == ["A.activated_synergies.0.effects.B1", "A.critical_after.0.value"]
