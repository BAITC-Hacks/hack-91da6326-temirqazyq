"""Тонкая обёртка над OpenAI-совместимым API (OpenAI, NVIDIA NIM, любой vLLM/Ollama).

Настройка через переменные окружения (см. .env.example):
    LLM_PROVIDER = openai | nvidia | custom | none
    LLM_API_KEY  = ключ
    LLM_MODEL    = имя модели
    LLM_BASE_URL = переопределение base_url (для custom)
    LLM_MAX_TOKENS = лимит ответа (по умолчанию 2048)
    LLM_EXTRA_BODY = JSON, добавляемый в тело каждого запроса — например
                     {"chat_template_kwargs": {"enable_thinking": false}}
                     чтобы отключить reasoning у Nemotron через vLLM

Если ключа нет — ``available()`` возвращает False и агенты используют
детерминированный fallback (см. ai/fallback.py), чтобы демо не зависело от сети.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

PRESETS = {
    "openai": {"base_url": None, "model": "gpt-4o-mini"},
    "nvidia": {"base_url": "https://integrate.api.nvidia.com/v1", "model": "meta/llama-3.1-70b-instruct"},
    "custom": {"base_url": None, "model": None},
}


class LLMConfig:
    def __init__(self) -> None:
        self.provider = os.environ.get("LLM_PROVIDER", "none").lower()
        preset = PRESETS.get(self.provider, {})
        self.api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("NVIDIA_API_KEY")
        self.base_url = os.environ.get("LLM_BASE_URL") or preset.get("base_url")
        self.model = os.environ.get("LLM_MODEL") or preset.get("model")
        self.temperature = float(os.environ.get("LLM_TEMPERATURE", "0.3"))
        self.timeout = float(os.environ.get("LLM_TIMEOUT", "60"))
        self.max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "2048"))
        self.extra_body = self._parse_extra_body(os.environ.get("LLM_EXTRA_BODY"))

    @staticmethod
    def _parse_extra_body(raw: Optional[str]) -> Dict[str, Any]:
        """Битый JSON в переменной окружения не должен ронять приложение."""
        if not raw or not raw.strip():
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @property
    def enabled(self) -> bool:
        return self.provider != "none" and bool(self.api_key) and bool(self.model)

    def describe(self) -> Dict[str, Any]:
        return {"provider": self.provider, "model": self.model if self.enabled else None, "enabled": self.enabled}


_JSON_RE = re.compile(r"\{.*\}", re.S)


def extract_json(text: str) -> Any:
    """Достаёт JSON из ответа модели, даже если он обёрнут в ```json ...```."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if not m:
            raise
        return json.loads(m.group(0))


class LLM:
    def __init__(self, cfg: Optional[LLMConfig] = None) -> None:
        self.cfg = cfg or LLMConfig()
        self._client = None

    def available(self) -> bool:
        return self.cfg.enabled

    def _common(self) -> Dict[str, Any]:
        """Параметры, которые одинаковы для обычного запроса и для агентного цикла."""
        kwargs: Dict[str, Any] = {"model": self.cfg.model, "max_tokens": self.cfg.max_tokens}
        if self.cfg.extra_body:
            kwargs["extra_body"] = self.cfg.extra_body
        return kwargs

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.cfg.api_key, base_url=self.cfg.base_url, timeout=self.cfg.timeout)
        return self._client

    # ------------------------------------------------------------------
    def chat_json(self, system: str, user: str, temperature: Optional[float] = None) -> Any:
        """Один запрос → JSON-объект. Сначала пробуем response_format, при ошибке — обычный текст."""
        kwargs = dict(
            **self._common(),
            temperature=self.cfg.temperature if temperature is None else temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        try:
            resp = self.client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
        except Exception:
            resp = self.client.chat.completions.create(**kwargs)
        return extract_json(resp.choices[0].message.content or "{}")

    def chat_tools(
        self,
        system: str,
        user: str,
        tools: List[Dict[str, Any]],
        handlers: Dict[str, Callable[..., Any]],
        max_steps: int = 6,
    ) -> Dict[str, Any]:
        """Агентный цикл: модель вызывает инструменты движка, пока не выдаст финальный JSON.

        Возвращает {"result": <json>, "tool_calls": [{name, arguments, result}]}.
        """
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        log: List[Dict[str, Any]] = []
        for _ in range(max_steps):
            resp = self.client.chat.completions.create(
                **self._common(), temperature=self.cfg.temperature, messages=messages, tools=tools, tool_choice="auto"
            )
            msg = resp.choices[0].message
            if msg.tool_calls:
                messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        result = handlers[name](**args)
                    except Exception as exc:  # noqa: BLE001 — модель должна увидеть ошибку и исправиться
                        result = {"error": str(exc)}
                    log.append({"name": name, "arguments": args, "result": result})
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, ensure_ascii=False)})
                continue
            return {"result": extract_json(msg.content or "{}"), "tool_calls": log}
        # исчерпали шаги — просим финальный ответ без инструментов
        messages.append({"role": "user", "content": "Заверши работу и верни финальный JSON без вызова инструментов."})
        resp = self.client.chat.completions.create(**self._common(), temperature=self.cfg.temperature, messages=messages)
        return {"result": extract_json(resp.choices[0].message.content or "{}"), "tool_calls": log}


_llm: Optional[LLM] = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm
