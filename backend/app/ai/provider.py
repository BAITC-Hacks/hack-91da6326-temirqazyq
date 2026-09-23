"""Managed asynchronous Responses API client with explicit, metered retries."""

import asyncio
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel

from .settings import COMPATIBLE_MODELS, Settings
from .usage import UsageLedger, UsageLimitError


class ProviderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code, self.message, self.retryable = code, message, retryable
        super().__init__(message)


@lru_cache(maxsize=1)
def _encoder() -> Any:
    try:
        import tiktoken

        return tiktoken.encoding_for_model("gpt-4.1-mini")
    except Exception:
        return None


def input_token_bound(payload: dict[str, Any]) -> int:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    encoder = _encoder()
    content_tokens = len(encoder.encode(text, disallowed_special=())) if encoder is not None else len(text.encode("utf-8"))
    return content_tokens + 512 + 32 * len(payload.get("input", []))


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    schema = dict(schema)
    schema.pop("default", None)
    if schema.get("type") == "object" or "properties" in schema:
        schema["additionalProperties"] = False
        schema["required"] = list(schema.get("properties", {}))
    return {key: _strict_schema(value) if isinstance(value, dict) else [
        _strict_schema(item) if isinstance(item, dict) else item for item in value
    ] if isinstance(value, list) else value for key, value in schema.items()}


def _sanitized_error(error: Exception) -> ProviderError:
    if isinstance(error, ProviderError):
        return error
    if isinstance(error, APITimeoutError):
        return ProviderError("TIMEOUT", "OpenAI не ответил вовремя. Расход уже отправленного запроса может сохраниться.", True)
    if isinstance(error, APIConnectionError):
        return ProviderError("CONNECTION_ERROR", "Нет соединения с OpenAI.", True)
    if isinstance(error, APIStatusError):
        status, code = error.status_code, getattr(error, "code", None)
        if status == 401:
            return ProviderError("AUTHENTICATION_ERROR", "OpenAI отклонил ключ. Проверьте настройки backend.")
        if status in (403, 404):
            return ProviderError("MODEL_ACCESS_ERROR", "Модель недоступна для этого ключа или не существует.")
        if status == 429 and code in {"insufficient_quota", "billing_hard_limit_reached", "billing_not_active"}:
            return ProviderError("QUOTA_EXCEEDED", "OpenAI сообщил об исчерпании квоты или недоступном биллинге.")
        if status == 429:
            return ProviderError("RATE_LIMIT", "OpenAI временно ограничил частоту запросов.", True)
        if status >= 500:
            return ProviderError("PROVIDER_SERVER_ERROR", "Временная ошибка сервера OpenAI.", True)
        return ProviderError("INVALID_PROVIDER_REQUEST", "OpenAI отклонил параметры запроса.")
    return ProviderError("PROVIDER_ERROR", "Не удалось получить ответ OpenAI.")


class Provider:
    def __init__(self, settings: Settings, db_path: str | Path, *, client: Any = None):
        self.settings = settings
        self.ledger = UsageLedger(db_path, settings)
        self.client = client
        if client is None and settings.public()["provider_available"]:
            self.client = AsyncOpenAI(
                api_key=settings.openai_api_key, base_url="https://api.openai.com/v1",
                timeout=min(60.0, settings.ai_run_timeout_seconds), max_retries=0,
            )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
            self.client = None

    async def request(
        self, run_id: str, input: list[dict[str, Any]], *,
        text_schema: type[BaseModel] | None = None, tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = "auto",
    ) -> dict[str, Any]:
        settings = self.settings
        if not settings.ai_enabled:
            raise ProviderError("AI_DISABLED", "AI отключён в настройках приложения.")
        if settings.ai_provider != "openai":
            raise ProviderError("PROVIDER_UNSUPPORTED", "Настроенный AI-провайдер не поддерживается.")
        if settings.openai_model not in COMPATIBLE_MODELS:
            raise ProviderError("MODEL_UNSUPPORTED", "Совместимость выбранной модели не подтверждена. Настройка модели сохранена без замены.")
        if not settings.openai_api_key.strip() or self.client is None:
            raise ProviderError("API_KEY_MISSING", "Ключ OpenAI не настроен на backend.")
        payload: dict[str, Any] = {
            "model": settings.openai_model, "input": input,
            "max_output_tokens": settings.ai_max_output_tokens, "store": False,
        }
        if text_schema is not None:
            payload["text"] = {"format": {"type": "json_schema", "name": text_schema.__name__,
                "schema": _strict_schema(text_schema.model_json_schema()), "strict": True}}
        if tools:
            payload.update(tools=tools, tool_choice=tool_choice, parallel_tool_calls=False)
        # Initial tokenizer loading may read a public vocabulary asset. Keep
        # loading and encoding off the event loop, including on a cold install.
        bound = await asyncio.to_thread(input_token_bound, payload)
        if bound > settings.ai_max_input_tokens:
            raise ProviderError("CONTEXT_LIMIT", "Контекст превышает лимит приложения. Сократите запрос или историю.")
        for attempt in range(2):
            try:
                # Reserve the entire permitted context/output envelope, not only
                # the tokenizer estimate, so in-flight calls cannot overspend.
                attempt_id = self.ledger.reserve(run_id, settings.ai_max_input_tokens, settings.ai_max_output_tokens)
            except UsageLimitError as error:
                raise ProviderError(error.code, error.message) from None
            try:
                response = await self.client.responses.create(**payload)
                result = response if isinstance(response, dict) else response.model_dump(mode="json")
                output_text = getattr(response, "output_text", None)
                if isinstance(output_text, str):
                    result.setdefault("output_text", output_text)
                self.ledger.finish(attempt_id, result)
                return result
            except asyncio.CancelledError:
                self.ledger.fail(attempt_id, "CANCELLED")
                raise
            except Exception as error:
                sanitized = _sanitized_error(error)
                self.ledger.fail(attempt_id, sanitized.code)
                if sanitized.retryable and attempt == 0:
                    await asyncio.sleep(0.25)
                    continue
                raise sanitized from None
        raise ProviderError("PROVIDER_ERROR", "Не удалось завершить обращение к модели.")
