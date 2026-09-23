"""Server diagnostics remain inspectable without becoming user-facing errors."""

import asyncio
import copy
import logging

import pytest

from app.ai.agent import AgentError
from app.ai.presentation import FAILED_MESSAGE, public_history, public_run
from app.diagnostics import log_diagnostic, log_exception
from test_agent import finish, harness
from test_workspace_api import workspace


SCREENSHOT_ERROR = (
    "Объяснение содержит неизвестную ссылку на факт: "
    "A.activated_synergies[0].effects.B1; A.critical_after[0].value"
)


def failed_run(**updates):
    value = {
        "run_id": "private-failed-run",
        "status": "failed",
        "stage": "failed",
        "message": SCREENSHOT_ERROR,
        "error": {"code": "UNGROUNDED_EXPLANATION", "message": SCREENSHOT_ERROR},
        "events": [
            {"stage": "repairing", "message": "USER_BUDGET_EXCEEDED: backend details 80/70"},
            {"stage": "explaining", "message": "A.critical_after[0].value"},
            {"stage": "failed", "message": SCREENSHOT_ERROR},
        ],
        "scenarios": [], "explanation": None, "clarification": None,
    }
    value.update(updates)
    return value


def test_public_run_replaces_failure_and_repair_details_without_mutating_input():
    original = failed_run()
    snapshot = copy.deepcopy(original)
    visible = public_run(original)
    assert visible["message"] == FAILED_MESSAGE
    assert visible["error"] == {"code": "UNGROUNDED_EXPLANATION", "message": FAILED_MESSAGE}
    assert all("A.critical" not in event["message"] for event in visible["events"])
    assert all("USER_BUDGET_EXCEEDED" not in event["message"] for event in visible["events"])
    assert [event["stage"] for event in visible["events"]] == ["repairing", "explaining", "failed"]
    assert original == snapshot
    visible["error"]["message"] = "changed copy"
    visible["events"][0]["message"] = "changed copy"
    assert original == snapshot


def test_public_run_preserves_successful_explanation_and_handles_template_warning():
    explanation = {"summary": "Улучшены показатели S1 и S2 в Нуре.", "source": "openai"}
    completed = failed_run(status="completed", stage="completed", message="Результаты рассчитаны.", error=None, explanation=explanation)
    visible = public_run(completed)
    assert visible["message"] == completed["message"]
    assert visible["explanation"] == explanation
    fallback = public_run(failed_run(status="completed", stage="completed", explanation={"summary": "Шаблонное объяснение."}))
    assert "шаблону" in fallback["message"]
    assert fallback["error"]["message"] == FAILED_MESSAGE
    assert SCREENSHOT_ERROR not in fallback["message"]


@pytest.mark.parametrize("clarification", [
    SCREENSHOT_ERROR,
    "UNKNOWN_TOOL: get_city_context",
    "Результат [fact:A.score.after] недоступен",
    "Traceback TypeError in backend",
])
def test_public_clarification_never_echoes_internal_diagnostics(clarification):
    visible = public_run(failed_run(status="needs_clarification", error=None, clarification=clarification))
    assert visible["clarification"] == "Уточните желаемый результат и ограничения."


def test_user_facing_clarification_is_retained():
    question = "Уточните район, в котором нужно построить школу."
    assert public_run(failed_run(status="needs_clarification", error=None, clarification=question))["clarification"] == question


def test_current_and_legacy_history_hide_errors_but_preserve_user_and_successful_content():
    legacy_error = "Операция была отклонена старым провайдером без технического кода."
    original = [
        {"role": "user", "content": SCREENSHOT_ERROR},
        {"role": "assistant", "content": "Улучшены S1 и S2. Мера M7 сохранена."},
        {"role": "assistant", "kind": "error", "content": "Старая техническая ошибка без шаблона."},
        {"role": "assistant", "content": legacy_error},
        {"role": "assistant", "content": SCREENSHOT_ERROR},
        {"role": "assistant", "content": "NO_VERIFIED_CANDIDATES"},
    ]
    snapshot = copy.deepcopy(original)
    previous = failed_run(message=legacy_error, error={"code": "PROVIDER_ERROR", "message": legacy_error})
    visible = public_history(original, [previous])
    assert visible[:2] == original[:2]
    assert all(entry["content"] == FAILED_MESSAGE and entry["kind"] == "error" for entry in visible[2:])
    assert original == snapshot
    visible[0]["content"] = "changed copy"
    assert original == snapshot


def test_public_history_matches_truncated_legacy_diagnostic():
    long_error = "x" * 2100
    entry = {"role": "assistant", "content": long_error[:2000]}
    run = failed_run(message=long_error, error={"code": "OLD_FAILURE", "message": long_error})
    assert public_history([entry], [run])[0]["content"] == FAILED_MESSAGE


def test_get_run_and_session_history_keep_persisted_diagnostics_private(workspace):
    client, store, session, headers = workspace
    raw = failed_run()
    legacy_error = "Служебная ошибка старого запуска без распознаваемого шаблона."
    old = failed_run(run_id="old-run", message=legacy_error, error={"code": "OLD_FAILURE", "message": legacy_error})
    store.put_run(session, raw["run_id"], raw)
    store.put_run(session, old["run_id"], old)
    history = [
        {"role": "user", "content": "Покажи варианты для Нуры."},
        {"role": "assistant", "content": "Улучшены показатели Нуры."},
        {"role": "assistant", "content": SCREENSHOT_ERROR},
        {"role": "assistant", "content": legacy_error},
        {"role": "assistant", "kind": "error", "content": "Служебная ошибка с меткой."},
    ]
    store.update_session(session, history=history)

    response = client.get(f"/api/ai/runs/{raw['run_id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["error"] == {"code": "UNGROUNDED_EXPLANATION", "message": FAILED_MESSAGE}
    assert "activated_synergies" not in response.text
    assert "critical_after" not in response.text
    current = client.get("/api/sessions/current", headers=headers)
    assert current.status_code == 200
    body = current.json()
    assert "activated_synergies" not in current.text
    assert "critical_after" not in current.text
    assert body["history"][:2] == history[:2]
    assert all(entry["content"] == FAILED_MESSAGE for entry in body["history"][2:])
    assert all(run["error"]["message"] == FAILED_MESSAGE for run in body["runs"])
    assert store.get_run(session, raw["run_id"]) == raw
    assert store.get_run(session, old["run_id"]) == old
    assert store.get_session(session)["history"] == history


def test_session_sanitizes_legacy_history_from_runs_older_than_visible_list(workspace):
    client, store, session, headers = workspace
    legacy_error = "Служебное сообщение без стандартного технического обозначения."
    old = failed_run(run_id="old-private", message=legacy_error, error={"code": "OLD_FAILURE", "message": legacy_error})
    store.put_run(session, old["run_id"], old)
    for index in range(12):
        store.put_run(session, f"recent-{index}", {"run_id": f"recent-{index}", "status": "completed", "message": "Готово.", "events": [], "error": None})
    store.update_session(session, history=[{"role": "assistant", "content": legacy_error}])
    body = client.get("/api/sessions/current", headers=headers).json()
    assert len(body["runs"]) == 10
    assert all(run["run_id"] != old["run_id"] for run in body["runs"])
    assert body["history"][0]["content"] == FAILED_MESSAGE


def test_agent_failure_logs_real_reference_but_stores_public_history(harness, caplog):
    caplog.set_level(logging.WARNING, logger="uvicorn.error")
    manager, session, provider = harness([AgentError("UNGROUNDED_EXPLANATION", SCREENSHOT_ERROR)], ai_enabled=True, ai_allow_template_fallback=False)
    raw = asyncio.run(finish(manager, session))
    assert raw["status"] == "failed"
    assert raw["error"]["message"] == SCREENSHOT_ERROR
    records = [record.getMessage() for record in caplog.records if record.name == "uvicorn.error"]
    assert any("UNGROUNDED_EXPLANATION" in message and raw["run_id"] in message and "A.critical_after[0].value" in message for message in records)
    assert public_run(raw)["error"]["message"] == FAILED_MESSAGE
    history = manager.store.get_session(session)["history"]
    assert history[-1] == {"role": "assistant", "content": FAILED_MESSAGE, "kind": "error"}
    assert manager.store.get_run(session, raw["run_id"])["error"]["message"] == SCREENSHOT_ERROR
    assert len(provider.calls) == 1


def test_log_diagnostic_redacts_credentials_and_removes_line_control_injection(caplog):
    caplog.set_level(logging.WARNING, logger="uvicorn.error")
    configured_key = "configured-secret-without-prefix"
    message = f"{configured_key} sk-proj-OTHER_Secret123 Bearer another-token\r\nINJECT\t\x1b[31m\x00" + "x" * 3000
    log_diagnostic("FAILURE\r\nINJECT", message, run_id="run-123\nINJECT", secret=configured_key)
    record = caplog.records[-1]
    rendered = record.getMessage()
    assert configured_key not in rendered
    assert "sk-" not in rendered
    assert "another-token" not in rendered
    assert "Bearer [redacted]" in rendered
    assert all(character not in rendered for character in "\r\n\t\x1b\x00")
    assert len(rendered) < 2200
    assert record.exc_info is None


def test_unexpected_exception_logging_uses_type_and_frames_not_raw_message(caplog):
    caplog.set_level(logging.WARNING, logger="uvicorn.error")
    raw_message = "PRIVATE_PROVIDER_BODY configured-secret sk-proj-abc Bearer xyz\r\nINJECT"
    try:
        raise RuntimeError(raw_message)
    except RuntimeError as error:
        log_exception(error, run_id="unexpected-run")
    rendered = caplog.records[-1].getMessage()
    assert "RuntimeError" in rendered
    assert "unexpected-run" in rendered
    assert "test_public_errors.py" in rendered
    assert "PRIVATE_PROVIDER_BODY" not in rendered
    assert "configured-secret" not in rendered
    assert "sk-" not in rendered
    assert "Bearer" not in rendered
    assert "INJECT" not in rendered
    assert "\n" not in rendered and "\r" not in rendered
    assert caplog.records[-1].exc_info is None


def test_unexpected_agent_failure_never_logs_or_returns_raw_exception(harness, caplog):
    caplog.set_level(logging.WARNING, logger="uvicorn.error")
    secret = "configured-secret-test-only"
    error_text = f"PRIVATE_PROVIDER_BODY {secret} sk-proj-test Bearer leaked-token\nraw detail"
    manager, session, provider = harness([RuntimeError(error_text)], ai_enabled=True, ai_allow_template_fallback=False)
    manager.settings.openai_api_key = secret
    result = asyncio.run(finish(manager, session))
    assert result["error"]["code"] == "AGENT_ERROR"
    assert result["error"]["message"] != error_text
    assert public_run(result)["error"]["message"] == FAILED_MESSAGE
    records = [record.getMessage() for record in caplog.records if record.name == "uvicorn.error"]
    assert any("RuntimeError" in message and result["run_id"] in message for message in records)
    assert all("PRIVATE_PROVIDER_BODY" not in message and secret not in message and "leaked-token" not in message for message in records)
    assert len(provider.calls) == 1
