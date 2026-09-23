import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from openai import APIStatusError, APITimeoutError
from pydantic import BaseModel, ValidationError
import pytest

from app.ai.provider import Provider, ProviderError, input_token_bound
from app.ai.settings import Settings


def response(**extra):
    return {"id": "response", "model": "gpt-4.1-mini-2025-04-14", "status": "completed", "output": [],
            "usage": {"input_tokens": 100, "output_tokens": 20, "input_tokens_details": {"cached_tokens": 10}}, **extra}


def provider(tmp_path, monkeypatch, effects=None, **settings):
    monkeypatch.setattr("app.ai.provider.input_token_bound", lambda payload: 900)
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=effects, return_value=response())), close=AsyncMock())
    configured = Settings(openai_api_key="unit-test-only", **settings)
    return Provider(configured, tmp_path / "provider.sqlite3", client=client), client


def api_error(status, code):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return APIStatusError("unsafe provider text must not escape", response=httpx.Response(status, request=request), body={"code": code})


def test_responses_parameters_and_strict_schema_are_correct(tmp_path, monkeypatch):
    class Output(BaseModel):
        summary: str
        detail: str | None = None

    instance, client = provider(tmp_path, monkeypatch)
    result = asyncio.run(instance.request("run", [{"role": "user", "content": "Запрос"}], text_schema=Output,
        tools=[{"type": "function", "name": "evaluate_scenarios", "strict": True, "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}]))
    payload = client.responses.create.await_args.kwargs
    assert payload["model"] == "gpt-4.1-mini"
    assert payload["store"] is False
    assert payload["parallel_tool_calls"] is False
    assert payload["max_output_tokens"] == 2500
    assert "reasoning" not in payload
    schema = payload["text"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["summary", "detail"]
    assert result["id"] == "response"
    assert instance.ledger.metadata("run")["api_calls"] == 1
    asyncio.run(instance.close())
    asyncio.run(instance.close())
    client.close.assert_awaited_once()


@pytest.mark.parametrize("status,code,expected", [
    (401, "invalid_api_key", "AUTHENTICATION_ERROR"),
    (403, "permission_denied", "MODEL_ACCESS_ERROR"),
    (404, "model_not_found", "MODEL_ACCESS_ERROR"),
    (429, "insufficient_quota", "QUOTA_EXCEEDED"),
    (400, "invalid_request", "INVALID_PROVIDER_REQUEST"),
])
def test_permanent_errors_are_sanitized_and_not_retried(tmp_path, monkeypatch, status, code, expected):
    instance, client = provider(tmp_path, monkeypatch, [api_error(status, code)])
    with pytest.raises(ProviderError) as error:
        asyncio.run(instance.request("run", []))
    assert error.value.code == expected
    assert "unsafe" not in str(error.value)
    assert "unit-test-only" not in str(error.value)
    assert client.responses.create.await_count == 1
    metadata = instance.ledger.metadata("run")
    assert metadata["used_llm"] is False
    assert metadata["api_calls"] == 1
    assert metadata["usage_unknown"] is True


@pytest.mark.parametrize("failure", [api_error(429, "rate_limit_exceeded"), api_error(503, "server_error"), APITimeoutError(httpx.Request("POST", "https://api.openai.com/v1/responses"))])
def test_transient_error_retries_once_and_counts_both_attempts(tmp_path, monkeypatch, failure):
    instance, client = provider(tmp_path, monkeypatch, [failure, response()])
    asyncio.run(instance.request("run", []))
    assert client.responses.create.await_count == 2
    metadata = instance.ledger.metadata("run")
    assert metadata["api_calls"] == 2
    assert metadata["used_llm"] is True
    assert metadata["input_tokens"] == 100
    assert metadata["estimated_cost_usd"] is None
    assert metadata["reserved_cost_usd"] == pytest.approx(0.0088)


def test_retry_cannot_bypass_call_cap(tmp_path, monkeypatch):
    instance, client = provider(tmp_path, monkeypatch, [api_error(503, "server_error"), response()], ai_max_model_calls_per_run=1)
    with pytest.raises(ProviderError) as error:
        asyncio.run(instance.request("run", []))
    assert error.value.code == "MODEL_CALL_LIMIT"
    assert client.responses.create.await_count == 1


def test_context_cap_blocks_network_without_usage_attempt(tmp_path, monkeypatch):
    instance, client = provider(tmp_path, monkeypatch)
    monkeypatch.setattr("app.ai.provider.input_token_bound", lambda payload: 12001)
    with pytest.raises(ProviderError) as error:
        asyncio.run(instance.request("run", []))
    assert error.value.code == "CONTEXT_LIMIT"
    client.responses.create.assert_not_awaited()
    assert instance.ledger.metadata("run")["api_calls"] == 0


def test_cancelled_request_retains_conservative_reservation(tmp_path, monkeypatch):
    instance, client = provider(tmp_path, monkeypatch)

    async def run():
        started = asyncio.Event()

        async def waiting(**kwargs):
            started.set()
            await asyncio.Event().wait()

        client.responses.create.side_effect = waiting
        task = asyncio.create_task(instance.request("run", []))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    metadata = instance.ledger.metadata("run")
    assert metadata["api_calls"] == 1
    assert metadata["used_llm"] is False
    assert metadata["estimated_cost_usd"] is None
    assert metadata["reserved_cost_usd"] == pytest.approx(0.0088)


def test_explicit_model_override_is_preserved_and_rejected_if_unverified(tmp_path, monkeypatch):
    instance, client = provider(tmp_path, monkeypatch, openai_model="owner-configured-model")
    with pytest.raises(ProviderError) as error:
        asyncio.run(instance.request("run", []))
    assert error.value.code == "MODEL_UNSUPPORTED"
    assert instance.settings.openai_model == "owner-configured-model"
    client.responses.create.assert_not_awaited()


def test_client_forces_official_base_url_and_disables_sdk_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://stale-provider.invalid/v1")
    instance = Provider(Settings(openai_api_key="unit-test-only"), tmp_path / "client.sqlite3")
    assert str(instance.client.base_url) == "https://api.openai.com/v1/"
    assert instance.client.max_retries == 0
    asyncio.run(instance.close())


def test_settings_do_not_expose_key_and_env_override_is_respected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-secret-marker")
    monkeypatch.setenv("OPENAI_MODEL", "owner-configured-model")
    settings = Settings.from_env(load_dotenv=False)
    assert settings.openai_model == "owner-configured-model"
    assert settings.public()["key_configured"] is True
    assert "unit-test-secret-marker" not in repr(settings)
    assert "unit-test-secret-marker" not in settings.model_dump_json()
    assert "unit-test-secret-marker" not in str(settings.public())


def test_token_count_includes_tools_and_schema_and_has_offline_fallback(monkeypatch):
    monkeypatch.setattr("app.ai.provider._encoder", lambda: None)
    plain = input_token_bound({"input": [{"role": "user", "content": "Привет"}]})
    bigger = input_token_bound({"input": [{"role": "user", "content": "Привет"}], "tools": [{"description": "schema" * 100}]})
    assert bigger > plain > 512


@pytest.mark.parametrize("values", [{"ai_max_input_tokens": 12001}, {"ai_max_output_tokens": 2501}, {"ai_max_model_calls_per_run": 7}, {"ai_daily_spend_limit_usd": float("nan")}])
def test_settings_enforce_hard_limits(values):
    with pytest.raises(ValidationError):
        Settings(**values)
