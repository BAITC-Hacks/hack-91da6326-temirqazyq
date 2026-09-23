"""Offline regressions for a bounded correction of ungrounded explanations."""

import asyncio
import json

import pytest

from test_agent import (
    finish,
    generation,
    harness,
    intent_response,
    narrative_response,
    save_manual,
    text_response,
)


def invalid_narrative(kind):
    def respond(inputs, **kwargs):
        valid = narrative_response(inputs, **kwargs)
        draft = json.loads(valid["output"][0]["content"][0]["text"])
        if kind == "number":
            draft["summary"] = "Индекс сценария равен 999."
        else:
            draft["summary"] = "Показатель: [fact:A.unknown_indicator.value]."
            draft["evidence_refs"] = ["A.unknown_indicator.value"]
        return text_response(draft)

    return respond


def explain(manager, session, row, request_id="explain-repair"):
    return finish(
        manager,
        session,
        operation="explain",
        scenario_ids=[row["scenario_id"]],
        request_id=request_id,
    )


@pytest.mark.parametrize("kind", ["number", "reference"])
def test_one_correction_receives_rejected_draft_and_identical_server_facts(harness, kind):
    manager, session, provider = harness([invalid_narrative(kind), narrative_response])
    row = save_manual(manager, session)

    result = asyncio.run(explain(manager, session, row))

    assert result["status"] == "completed"
    assert result["error"] is None
    assert result["explanation"]["source"] == "openai"
    assert "999" not in result["explanation"]["summary"]
    assert "[fact:" not in result["explanation"]["summary"]
    assert not result["fallback_used"]
    assert result["repair_rounds"] == 0
    assert result["metadata"]["explanation_repair_rounds"] == 1
    assert result["metadata"]["api_calls"] == len(provider.calls) == 2
    assert result["metadata"]["input_tokens"] == 200
    assert result["metadata"]["output_tokens"] == 40
    assert result["metadata"]["estimated_cost_usd"] == pytest.approx(0.002)

    original_inputs, retry_inputs = [call["inputs"] for call in provider.calls]
    original = json.loads(original_inputs[-1]["content"])
    retry = json.loads(retry_inputs[-1]["content"])
    correction = retry.pop("correction")
    assert retry == original
    assert correction["validation_error"]
    rejected = correction["rejected_draft"]
    assert rejected["scenario_ids"] == original["scenario_ids"]
    assert rejected["summary"] == (
        "Индекс сценария равен 999."
        if kind == "number"
        else "Показатель: [fact:A.unknown_indicator.value]."
    )
    assert [item["role"] for item in retry_inputs] == ["system", "user"]
    assert retry_inputs[0] == original_inputs[0]


def test_second_invalid_explanation_fails_without_a_third_attempt_or_fallback(harness):
    manager, session, provider = harness([
        invalid_narrative("number"),
        invalid_narrative("reference"),
        narrative_response,
    ])
    row = save_manual(manager, session)

    async def exercise():
        failed = await explain(manager, session, row, "failed-explanation")
        assert len(provider.calls) == 2
        recovered = await explain(manager, session, row, "new-explanation")
        return failed, recovered

    failed, recovered = asyncio.run(exercise())
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "UNGROUNDED_EXPLANATION"
    assert failed["explanation"] is None
    assert not failed["fallback_used"]
    assert len(failed["scenarios"]) == 1
    assert failed["metadata"]["explanation_repair_rounds"] == 1
    assert failed["metadata"]["api_calls"] == 2
    assert recovered["status"] == "completed"
    assert not recovered["cache_hit"]
    assert recovered["metadata"]["api_calls"] == 1
    assert len(provider.calls) == 3


@pytest.mark.parametrize("limits", [
    {"ai_max_model_calls_per_run": 1},
    {"ai_max_repair_rounds": 0},
])
def test_correction_respects_remaining_model_budget_and_disabled_repairs(harness, limits):
    manager, session, provider = harness([invalid_narrative("number"), narrative_response], **limits)
    row = save_manual(manager, session)

    result = asyncio.run(explain(manager, session, row))

    assert result["status"] == "failed"
    assert result["error"]["code"] == "UNGROUNDED_EXPLANATION"
    assert result["explanation"] is None
    assert result["metadata"]["api_calls"] == len(provider.calls) == 1
    assert result["metadata"]["explanation_repair_rounds"] == 0
    assert len(provider.script) == 1


@pytest.mark.parametrize("response,code", [
    ({"status": "incomplete", "output": []}, "INCOMPLETE_RESPONSE"),
    ({"status": "completed", "output": [{"type": "message", "content": [
        {"type": "refusal", "refusal": "Cannot comply"},
    ]}]}, "MODEL_REFUSAL"),
])
def test_refused_or_incomplete_explanations_are_never_retried(harness, response, code):
    manager, session, provider = harness([response, narrative_response])
    row = save_manual(manager, session)

    result = asyncio.run(explain(manager, session, row))

    assert result["status"] == "failed"
    assert result["error"]["code"] == code
    assert result["explanation"] is None
    assert result["metadata"]["explanation_repair_rounds"] == 0
    assert len(provider.calls) == 1


def test_corrected_explanation_cache_keeps_both_original_calls_and_cost(harness):
    manager, session, provider = harness([invalid_narrative("number"), narrative_response])
    row = save_manual(manager, session)

    async def exercise():
        first = await explain(manager, session, row, "first-explanation")
        cached = await explain(manager, session, row, "cached-explanation")
        return first, cached

    first, cached = asyncio.run(exercise())

    assert first["status"] == cached["status"] == "completed"
    assert cached["cache_hit"]
    assert cached["explanation"] == first["explanation"]
    assert cached["metadata"]["api_calls"] == 0
    assert cached["metadata"]["estimated_cost_usd"] == 0
    assert cached["metadata"]["explanation_repair_rounds"] == 0
    original = cached["metadata"]["original_generation"]
    assert original["api_calls"] == 2
    assert original["input_tokens"] == 200
    assert original["output_tokens"] == 40
    assert original["estimated_cost_usd"] == pytest.approx(0.002)
    assert original["explanation_repair_rounds"] == 1
    assert len(provider.calls) == 2


def test_explanation_correction_does_not_resend_acknowledged_function_calls(harness):
    manager, session, provider = harness([
        intent_response(), generation(), invalid_narrative("number"), narrative_response,
    ])

    result = asyncio.run(finish(manager, session))

    assert result["status"] == "completed"
    assert result["metadata"]["api_calls"] == len(provider.calls) == 4
    first_inputs, retry_inputs = [call["inputs"] for call in provider.calls[-2:]]
    assert any(item.get("type") == "function_call" for item in first_inputs)
    assert any(item.get("type") == "function_call_output" for item in first_inputs)
    assert all(item.get("type") not in {"function_call", "function_call_output"} for item in retry_inputs)
    assert [item["role"] for item in retry_inputs] == ["system", "user"]
    assert result["repair_rounds"] == 0
    assert result["metadata"]["explanation_repair_rounds"] == 1
