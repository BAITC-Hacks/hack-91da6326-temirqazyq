"""Offline orchestration tests with real tools/storage and scripted model responses."""

import asyncio
import copy
import json
import sqlite3

import pytest

from app.ai.agent import AgentError, AgentManager, RunRequest
from app.ai.contracts import Constraints
from app.ai.settings import Settings
from app.ai.tools import dataset_version
from app.simulation.engine import simulate
from app.storage import Store


DECISIONS = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12", "district": None},
    {"measure_id": "M11", "district": "Нура"},
]


def text_response(value):
    content = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return {"status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": content}]}]}


def intent_response(**changes):
    value = {name: None for name in Constraints.model_fields}
    value.update(operation="generate", clear_fields=[], clarification=None, unsupported_conditions=[], requested_scenario_count=1)
    value.update(changes)
    return text_response(value)


def tool_call(name, arguments, call_id="call-evaluate"):
    return {"type": "function_call", "name": name, "arguments": json.dumps(arguments, ensure_ascii=False) if not isinstance(arguments, str) else arguments, "call_id": call_id}


def generation(decisions=None, call_id="call-evaluate", name="Проверяемый вариант"):
    return {"status": "completed", "output": [tool_call("evaluate_scenarios", {"candidates": [{"name": name, "decisions": decisions or DECISIONS}]}, call_id)]}


def narrative_response(inputs, **kwargs):
    context = json.loads(inputs[-1]["content"])
    identifier = context["scenario_ids"][0]
    alias = next(alias for alias, scenario_id in context["scenario_refs"].items() if scenario_id == identifier)
    reference = f"{alias}.score.after"
    assert reference in context["facts"]
    return text_response({
        "summary": f"Индекс сценария: [fact:{reference}].",
        "observations": ["Социальные показатели улучшились."],
        "remaining_issues": [], "tradeoffs": ["Распределение ресурсов зависит от приоритетов."],
        "limitations": ["Синтетическая модель, не прогноз реальной Астаны."],
        "evidence_refs": [reference], "scenario_ids": context["scenario_ids"],
    })


class FakeLedger:
    def __init__(self):
        self.calls = {}

    def metadata(self, run_id):
        attempts = self.calls.get(run_id, 0)
        return {"api_calls": attempts, "model_calls": attempts, "attempts": attempts, "input_tokens": attempts * 100, "output_tokens": attempts * 20, "estimated_cost_usd": attempts * 0.001, "returned_model": "fake-gpt-4.1-mini" if attempts else None}

    def summary(self):
        return {"attempts": sum(self.calls.values())}


class FakeProvider:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.ledger = FakeLedger()
        self.closed = False

    async def request(self, run_id, inputs, **kwargs):
        self.calls.append({"run_id": run_id, "inputs": copy.deepcopy(inputs), "kwargs": kwargs})
        self.ledger.calls[run_id] = self.ledger.calls.get(run_id, 0) + 1
        if not self.script:
            raise AssertionError("Unexpected model request; scripted responses exhausted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            value = step(inputs, **kwargs)
            return await value if hasattr(value, "__await__") else value
        return copy.deepcopy(step)

    async def close(self):
        self.closed = True


@pytest.fixture
def harness(tmp_path):
    counter = 0

    def create(script, **settings):
        nonlocal counter
        counter += 1
        store = Store(tmp_path / f"agent-{counter}.sqlite3")
        config = Settings(openai_api_key="offline-unit-test-key", db_path=store.path, **settings)
        provider = FakeProvider(script)
        manager = AgentManager(config, store, provider)
        return manager, store.create_session(), provider

    return create


async def finish(manager, session, **kwargs):
    kwargs.setdefault("request_id", "request-0001")
    kwargs.setdefault("message", "Покажи допустимый вариант")
    run = manager.start(session, RunRequest(**kwargs))
    task = manager.tasks.get(run["run_id"])
    if task:
        await task
        await asyncio.sleep(0)
    return manager.store.get_run(session, run["run_id"])


def save_manual(manager, session):
    result = simulate(DECISIONS)
    return manager.store.save_scenario(session, decisions=result["decisions"], result=result, provenance="manual", constraints=Constraints().model_dump(), dataset_version=dataset_version())


def test_real_tool_call_ids_and_all_outputs_are_handed_to_explanation(harness):
    batch = generation()
    batch["output"].insert(0, tool_call("get_city_context", {}, "call-context"))
    batch["output"].insert(1, tool_call("unknown_tool", {}, "call-unknown"))
    manager, session, provider = harness([intent_response(), batch, narrative_response])
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "completed"
    assert result["explanation"]["source"] == "openai"
    assert len(result["scenarios"]) == 1
    assert result["scenarios"][0]["result"]["budget"]["spent"] == 80
    assert result["tool_calls"] == 3
    final_inputs = provider.calls[-1]["inputs"]
    outputs = {item["call_id"]: json.loads(item["output"]) for item in final_inputs if item.get("type") == "function_call_output"}
    assert set(outputs) == {"call-context", "call-unknown", "call-evaluate"}
    assert outputs["call-unknown"]["errors"][0]["code"] == "UNKNOWN_TOOL"
    assert outputs["call-evaluate"]["candidates"][0]["valid"]
    assert {item["call_id"] for item in final_inputs if item.get("type") == "function_call"} == set(outputs)
    assert "validating" in [event["stage"] for event in result["events"]]


def test_invalid_candidate_is_repaired_from_real_tool_errors(harness):
    invalid = copy.deepcopy(DECISIONS)
    invalid[0]["district"] = None
    manager, session, provider = harness([intent_response(), generation(invalid, "bad-draft"), generation(call_id="repaired-draft"), narrative_response])
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "completed"
    assert result["repair_rounds"] == 1
    repair_input = provider.calls[2]["inputs"]
    bad_output = next(json.loads(item["output"]) for item in repair_input if item.get("call_id") == "bad-draft" and item["type"] == "function_call_output")
    candidate = bad_output["candidates"][0]
    assert not candidate["valid"]
    assert "score" not in candidate
    assert "DISTRICT_REQUIRED" in {error["code"] for error in candidate["errors"]}
    assert len(manager.store.list_scenarios(session)) == 1


def test_malformed_arguments_are_returned_with_call_id_then_generation_continues(harness):
    malformed = {"status": "completed", "output": [tool_call("evaluate_scenarios", "{not json", "malformed")]}
    manager, session, provider = harness([intent_response(), malformed, generation(call_id="valid"), narrative_response])
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "completed"
    outputs = [item for item in provider.calls[2]["inputs"] if item.get("type") == "function_call_output"]
    assert outputs[0]["call_id"] == "malformed"
    assert json.loads(outputs[0]["output"])["errors"][0]["code"] == "INVALID_TOOL_ARGUMENTS"


@pytest.mark.parametrize("bad_response,code", [
    ({"status": "incomplete", "output": []}, "INCOMPLETE_RESPONSE"),
    ({"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "Cannot comply"}]}]}, "MODEL_REFUSAL"),
])
def test_refusal_and_incomplete_are_explicit_failures(harness, bad_response, code):
    manager, session, provider = harness([bad_response])
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "failed"
    assert result["error"]["code"] == code
    assert result["scenarios"] == []
    assert result["explanation"] is None
    assert len(provider.calls) == 1


def test_russian_followup_preserves_exclusions_locked_decisions_and_analysis(harness):
    manager, session, provider = harness([
        intent_response(max_budget=90, excluded_measure_ids=["M3"], locked_decisions=[{"measure_id": "M7", "district": "Нура"}], focus_district="Нура", analysis_indicators=["S1", "S2"]),
        generation(), narrative_response,
        intent_response(reserve_budget=20), generation(call_id="followup"), narrative_response,
    ])

    async def exercise():
        first = await finish(manager, session, request_id="russian-first", message="Бюджет не больше 90, без ЛРТ. Не меняй M7 в Нуре. Покажи школы и поликлиники Нуры.")
        second = await finish(manager, session, request_id="russian-followup", message="Теперь оставь минимум 20 единиц бюджета. Остальные ограничения сохрани.")
        return first, second

    first, second = asyncio.run(exercise())
    assert first["status"] == second["status"] == "completed"
    state = manager.store.get_session(session)["constraints"]
    assert state["max_budget"] == 90
    assert state["reserve_budget"] == 20
    assert state["excluded_measure_ids"] == ["M3"]
    assert state["locked_decisions"] == [{"measure_id": "M7", "district": "Нура"}]
    assert state["analysis_indicators"] == ["S1", "S2"]
    followup_input = json.loads(provider.calls[3]["inputs"][-1]["content"])
    assert followup_input["previous_constraints"]["excluded_measure_ids"] == ["M3"]
    assert followup_input["history"]
    assert second["scenarios"][0]["result"]["budget"]["remaining"] >= 20


def test_ai_generation_never_silently_uses_optimizer(harness, monkeypatch):
    from app.ai import tools

    def prohibited(*args, **kwargs):
        raise AssertionError("Optimizer was invoked in AI mode")

    monkeypatch.setattr(tools, "search", prohibited)
    response = generation()
    response["output"].insert(0, tool_call("search_scenarios", {"constraints": {}}, "forbidden-search"))
    manager, session, provider = harness([intent_response(), response, narrative_response])
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "completed"
    supplied_names = {item["name"] for item in provider.calls[1]["kwargs"]["tools"]}
    assert "search_scenarios" not in supplied_names
    output = next(json.loads(item["output"]) for item in provider.calls[-1]["inputs"] if item.get("call_id") == "forbidden-search" and item["type"] == "function_call_output")
    assert output["errors"][0]["code"] == "UNKNOWN_TOOL"


def test_session_isolation_rejects_foreign_scenario_without_provider(harness):
    manager, session, provider = harness([])
    row = save_manual(manager, session)
    second_session = manager.store.create_session()
    result = asyncio.run(finish(manager, second_session, operation="explain", scenario_ids=[row["scenario_id"]]))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "SCENARIO_NOT_FOUND"
    assert provider.calls == []
    assert manager.store.get_run(session, result["run_id"]) is None


def test_repeated_explanation_uses_explicit_cache_without_new_model_calls(harness):
    manager, session, provider = harness([narrative_response])
    row = save_manual(manager, session)

    async def exercise():
        first = await finish(manager, session, operation="explain", request_id="explain-first", scenario_ids=[row["scenario_id"]])
        second = await finish(manager, session, operation="explain", request_id="explain-second", scenario_ids=[row["scenario_id"]])
        return first, second

    first, second = asyncio.run(exercise())
    assert first["status"] == second["status"] == "completed"
    assert first["explanation"] == second["explanation"]
    assert not first["cache_hit"]
    assert second["cache_hit"]
    assert second["metadata"]["model_calls"] == 0
    assert second["metadata"]["original_generation"]["model_calls"] == 1
    assert "кеша" in second["message"]
    assert len(provider.calls) == 1


def test_idempotency_prevents_double_execution_and_rejects_changed_payload(harness):
    manager, session, provider = harness([intent_response(), generation(), narrative_response])

    async def exercise():
        request = RunRequest(request_id="stable-request", message="Вариант")
        first = manager.start(session, request)
        repeated = manager.start(session, request)
        assert first["run_id"] == repeated["run_id"]
        with pytest.raises(AgentError) as error:
            manager.start(session, request.model_copy(update={"message": "Другой запрос"}))
        assert error.value.code == "IDEMPOTENCY_CONFLICT"
        await manager.tasks[first["run_id"]]
        await asyncio.sleep(0)
        final = manager.start(session, request)
        assert final["status"] == "completed"

    asyncio.run(exercise())
    assert len(provider.calls) == 3


def test_cancellation_stops_later_calls_and_busy_run_is_rejected(harness):
    async def exercise():
        started, blocked = asyncio.Event(), asyncio.Event()

        async def wait_forever(inputs, **kwargs):
            started.set()
            await blocked.wait()
            raise AssertionError("Cancelled provider should not continue")

        manager, session, provider = harness([wait_forever])
        run = manager.start(session, RunRequest(request_id="cancel-request", message="Запрос"))
        await started.wait()
        with pytest.raises(AgentError) as error:
            manager.start(session, RunRequest(request_id="second-request", message="Ещё запрос"))
        assert error.value.code == "AI_BUSY"
        cancelled = await manager.cancel(session, run["run_id"])
        assert cancelled["status"] == "cancelled"
        assert cancelled["metadata"]["model_calls"] == 1
        assert "расход" in cancelled["message"]
        assert len(provider.calls) == 1
        assert await manager.cancel(manager.store.create_session(), run["run_id"]) is None
        await manager.close()
        assert provider.closed

    asyncio.run(exercise())


def test_run_timeout_does_not_start_further_iterations(harness):
    async def wait_forever(inputs, **kwargs):
        await asyncio.Event().wait()

    manager, session, provider = harness([wait_forever], ai_run_timeout_seconds=0.02)
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "RUN_TIMEOUT"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("patch", [
    {"operation": "clarify", "clarification": "Какой район вы имеете в виду?"},
    {"unsupported_conditions": ["прогноз аварий в процентах"]},
    {"excluded_measure_ids": ["M99"]},
    {"max_budget": 5},
])
def test_unsupported_unknown_or_contradictory_conditions_do_not_generate(harness, patch):
    manager, session, provider = harness([intent_response(**patch)])
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "needs_clarification"
    assert result["scenarios"] == []
    assert result["clarification"]
    assert len(provider.calls) == 1


def test_plain_model_text_is_clarification_not_a_fake_verified_scenario(harness):
    manager, session, provider = harness([intent_response(), text_response("Уточните, нужно ли сохранить текущее решение?")])
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "needs_clarification"
    assert not result["scenarios"]
    assert len(provider.calls) == 2


def test_repair_limit_returns_no_fabricated_scenarios(harness):
    invalid = copy.deepcopy(DECISIONS)
    invalid[0]["district"] = None
    manager, session, provider = harness([
        intent_response(),
        generation(invalid, "round-one", "Первый"),
        generation(invalid, "round-two", "Второй"),
        generation(invalid, "round-three", "Третий"),
    ])
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "NO_VERIFIED_CANDIDATES"
    assert result["repair_rounds"] == 2
    assert result["scenarios"] == []
    assert len(provider.calls) == 4


def test_unknown_evidence_fails_without_silent_template(harness):
    def ungrounded(inputs, **kwargs):
        response = narrative_response(inputs, **kwargs)
        value = json.loads(response["output"][0]["content"][0]["text"])
        value["evidence_refs"].append("invented.score")
        return text_response(value)

    manager, session, provider = harness([intent_response(), generation(), ungrounded, ungrounded])
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "UNGROUNDED_EXPLANATION"
    assert not result["fallback_used"]
    assert len(result["scenarios"]) == 1
    assert result["explanation"] is None


def test_repeated_identical_tool_call_is_rejected_and_prior_result_returned(harness):
    first = generation(call_id="first-call")
    repeated = generation(call_id="repeat-call")
    alternate = copy.deepcopy(DECISIONS)
    alternate[-1]["district"] = "Алматы"
    manager, session, provider = harness([
        intent_response(requested_scenario_count=2), first, repeated,
        generation(alternate, "different-call"), narrative_response,
    ])
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "completed"
    assert len(result["scenarios"]) == 2
    repeated_output = next(json.loads(item["output"]) for item in provider.calls[3]["inputs"] if item.get("call_id") == "repeat-call" and item["type"] == "function_call_output")
    assert repeated_output["errors"][0]["code"] == "REPEATED_TOOL_CALL"
    assert repeated_output["previous_result"]["verified_count"] == 1
    assert len(manager.store.list_scenarios(session)) == 2


def test_template_fallback_requires_explicit_setting_and_is_labeled(harness):
    def unsupported_number(inputs, **kwargs):
        response = narrative_response(inputs, **kwargs)
        value = json.loads(response["output"][0]["content"][0]["text"])
        value["summary"] = "Прогноз 999999."
        return text_response(value)

    manager, session, provider = harness([intent_response(), generation(), unsupported_number, unsupported_number], ai_allow_template_fallback=True)
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "completed"
    assert result["error"]["code"] == "UNGROUNDED_EXPLANATION"
    assert result["fallback_used"]
    assert result["explanation"]["source"] == "template"
    assert "Шаблонное" in result["message"]


def test_explain_rejects_stale_dataset_before_model_request(harness):
    manager, session, provider = harness([])
    row = save_manual(manager, session)
    with sqlite3.connect(manager.store.path) as connection:
        connection.execute("UPDATE scenarios SET dataset_version = ? WHERE scenario_id = ?", ("old-version", row["scenario_id"]))
    result = asyncio.run(finish(manager, session, operation="explain", scenario_ids=[row["scenario_id"]]))
    assert result["status"] == "failed"
    assert result["error"] is not None
    assert provider.calls == []


def test_explain_recomputes_saved_metrics_before_building_evidence(harness):
    manager, session, provider = harness([narrative_response])
    row = save_manual(manager, session)
    real_score = row["result"]["score"]["after"]
    row["result"]["score"]["after"] = 999999
    with sqlite3.connect(manager.store.path) as connection:
        connection.execute("UPDATE scenarios SET result_json = ? WHERE scenario_id = ?", (json.dumps(row["result"]), row["scenario_id"]))
    result = asyncio.run(finish(manager, session, operation="explain", scenario_ids=[row["scenario_id"]]))
    assert result["status"] == "completed"
    assert result["scenarios"][0]["result"]["score"]["after"] == pytest.approx(real_score)
    assert "999999" not in result["explanation"]["summary"]


def test_partial_verified_result_reserves_last_model_call_for_explanation(harness):
    manager, session, provider = harness(
        [intent_response(requested_scenario_count=3), generation(), narrative_response],
        ai_max_model_calls_per_run=3,
    )
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "completed"
    assert len(result["scenarios"]) == 1
    assert result["explanation"]["source"] == "openai"
    assert result["metadata"]["api_calls"] == 3
    assert len(provider.calls) == 3
    assert provider.calls[-1]["kwargs"]["text_schema"].__name__ == "Narrative"
    assert "Дополнительные варианты не получены" in result["message"]
    outputs = [item for item in provider.calls[-1]["inputs"] if item.get("type") == "function_call_output"]
    assert outputs[0]["call_id"] == "call-evaluate"


def test_explanation_reservation_counts_actual_retry_attempts_from_ledger(harness):
    manager, session, provider = harness([], ai_max_model_calls_per_run=4)

    def retried_generation(inputs, **kwargs):
        run_id = provider.calls[-1]["run_id"]
        provider.ledger.calls[run_id] += 1
        return generation()

    provider.script = [intent_response(requested_scenario_count=3), retried_generation, narrative_response]
    result = asyncio.run(finish(manager, session))
    assert result["status"] == "completed"
    assert len(result["scenarios"]) == 1
    assert result["metadata"]["api_calls"] == 4
    assert len(provider.calls) == 3
    assert provider.calls[-1]["kwargs"]["text_schema"].__name__ == "Narrative"
