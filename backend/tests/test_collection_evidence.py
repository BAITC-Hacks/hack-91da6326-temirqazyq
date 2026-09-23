"""Collection evidence remains verified data, never an inferred numeric value."""

import asyncio
import json

import pytest

from app.ai.agent import AgentManager
from app.ai.contracts import Constraints, Narrative
from app.ai.evidence import facts_for, ground_narrative
from app.ai.settings import Settings
from app.simulation.engine import simulate
from app.storage import Store
from test_agent import DECISIONS, FakeProvider, finish, intent_response, text_response, tool_call


COLLECTIONS = ("critical_before", "critical_after", "activated_synergies")


@pytest.fixture
def scenario_rows():
    # Actual engine outputs include both empty and non-empty collections.
    results = [
        simulate([], preview=True),
        simulate(DECISIONS),
        simulate([{"measure_id": "M12"}], preview=True),
    ]
    assert all(result["valid"] for result in results)
    return [
        {"scenario_id": f"scenario-{index}", "result": result}
        for index, result in enumerate(results)
    ]


def collection_narrative(rows, **updates):
    value = {
        "summary": "Сопоставлены оставшиеся критические показатели вариантов.",
        "observations": [],
        "remaining_issues": [],
        "tradeoffs": [],
        "limitations": [],
        "evidence_refs": ["A.critical_after", "B.critical_after", "C.critical_after"],
        "scenario_ids": [row["scenario_id"] for row in rows],
    }
    value.update(updates)
    return Narrative(**value)


def test_facts_register_exact_engine_collections_and_separate_counts(scenario_rows):
    facts = facts_for(scenario_rows, Constraints())
    for alias, row in zip("ABC", scenario_rows):
        for field in COLLECTIONS:
            reference = f"{alias}.{field}"
            assert facts[reference] == row["result"][field]
            assert isinstance(facts[reference], list)
            assert facts[f"{reference}.count"] == len(row["result"][field])
    assert facts["B.critical_after"] == []
    assert facts["A.activated_synergies"] == []
    assert facts["B.activated_synergies"]


def test_reported_three_critical_after_references_ground_without_fallback(scenario_rows):
    facts = facts_for(scenario_rows, Constraints())
    narrative = collection_narrative(scenario_rows)
    rendered = ground_narrative(narrative, facts, narrative.scenario_ids)
    assert rendered["source"] == "openai"
    assert rendered["summary"] == narrative.summary
    assert rendered["evidence_refs"] == ["A.critical_after", "B.critical_after", "C.critical_after"]
    assert rendered["evidence"] == {
        f"{alias}.critical_after": row["result"]["critical_after"]
        for alias, row in zip("ABC", scenario_rows)
    }
    assert rendered["evidence"]["B.critical_after"] == []


@pytest.mark.parametrize("field", COLLECTIONS)
def test_collection_evidence_accepts_qualitative_statements(scenario_rows, field):
    references = [f"{alias}.{field}" for alias in "ABC"]
    value = collection_narrative(
        scenario_rows,
        summary="Сопоставлены рассчитанные данные по всем вариантам.",
        evidence_refs=references,
    )
    facts = facts_for(scenario_rows, Constraints())
    rendered = ground_narrative(value, facts, value.scenario_ids)
    assert rendered["evidence"] == {reference: facts[reference] for reference in references}


@pytest.mark.parametrize("field", COLLECTIONS)
def test_collection_count_placeholders_use_exact_scalar_counts(scenario_rows, field):
    references = [f"{alias}.{field}.count" for alias in "ABC"]
    summary = "; ".join(f"{alias}: [fact:{reference}]" for alias, reference in zip("ABC", references))
    value = collection_narrative(scenario_rows, summary=summary, evidence_refs=references)
    rendered = ground_narrative(value, facts_for(scenario_rows, Constraints()), value.scenario_ids)
    expected = "; ".join(f"{alias}: {len(row['result'][field])}" for alias, row in zip("ABC", scenario_rows))
    assert rendered["summary"] == expected
    assert all(isinstance(number, int) for number in rendered["evidence"].values())


@pytest.mark.parametrize("reference", [
    "A.critical_after.total",
    "A.critical_aftre",
    "A.activated_synergies.counted",
    "D.critical_after",
    "unknown-scenario.critical_after",
])
def test_collection_registration_never_guesses_unknown_paths_or_aliases(scenario_rows, reference):
    value = collection_narrative(scenario_rows, evidence_refs=[reference])
    with pytest.raises(ValueError, match="неизвестную ссылку"):
        ground_narrative(value, facts_for(scenario_rows, Constraints()), value.scenario_ids)


@pytest.mark.parametrize("reference", [
    f"{alias}.{field}" for alias in "ABC" for field in COLLECTIONS
])
def test_collection_placeholder_is_rejected_instead_of_coerced_to_count_or_text(scenario_rows, reference):
    value = collection_narrative(scenario_rows, summary=f"Значение: [fact:{reference}].", evidence_refs=[reference])
    with pytest.raises(ValueError):
        ground_narrative(value, facts_for(scenario_rows, Constraints()), value.scenario_ids)


@pytest.mark.parametrize("claim", ["Всего 42 критических показателя.", "Эффективность выросла на 25%."])
def test_valid_collection_reference_does_not_authorize_fabricated_numbers(scenario_rows, claim):
    value = collection_narrative(scenario_rows, summary=claim)
    with pytest.raises(ValueError, match="Числа"):
        ground_narrative(value, facts_for(scenario_rows, Constraints()), value.scenario_ids)


def test_agent_completes_three_verified_candidates_with_collection_evidence(tmp_path):
    candidates = [
        {
            "name": f"Вариант {district}",
            "decisions": [
                {"measure_id": decision["measure_id"], "district": district if decision["district"] else None}
                for decision in DECISIONS
            ],
        }
        for district in ("Нура", "Есиль", "Алматы")
    ]
    assert all(simulate(candidate["decisions"])["valid"] for candidate in candidates)

    def explanation(inputs, **kwargs):
        context = json.loads(inputs[-1]["content"])
        references = [f"{alias}.critical_after" for alias in "ABC"]
        return text_response({
            "summary": "Сопоставлены оставшиеся критические показатели вариантов.",
            "observations": [], "remaining_issues": [], "tradeoffs": [], "limitations": [],
            "evidence_refs": references, "scenario_ids": context["scenario_ids"],
        })

    provider = FakeProvider([
        intent_response(requested_scenario_count=3),
        {"status": "completed", "output": [tool_call("evaluate_scenarios", {"candidates": candidates})]},
        explanation,
    ])
    store = Store(tmp_path / "collection-evidence.sqlite3")
    settings = Settings(
        openai_api_key="offline-unit-test-key", db_path=store.path,
        ai_enabled=True, ai_allow_template_fallback=False,
    )
    manager = AgentManager(settings, store, provider)
    session = store.create_session()
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "completed", result.get("error")
    assert len(result["scenarios"]) == 3
    assert len(provider.calls) == 3
    assert result["explanation"]["source"] == "openai"
    assert result["explanation"]["evidence_refs"] == ["A.critical_after", "B.critical_after", "C.critical_after"]
    assert not result["fallback_used"]
    context = json.loads(provider.calls[-1]["inputs"][-1]["content"])
    for alias, row in zip("ABC", result["scenarios"]):
        reference = f"{alias}.critical_after"
        assert context["facts"][reference] == row["result"]["critical_after"]
        assert result["explanation"]["evidence"][reference] == row["result"]["critical_after"]
