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
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("akim.llm")

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
        # Задан ли лимит вручную: если нет, для рассуждающих моделей поднимем его сами.
        self.max_tokens_explicit = bool(os.environ.get("LLM_MAX_TOKENS"))
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

# Сервер называет проблемный параметр по-разному в зависимости от формулировки.
_PARAM_RES = (
    re.compile(r"Unsupported parameter: '([a-zA-Z_]+)'"),
    re.compile(r"'([a-zA-Z_]+)' is not supported"),
    re.compile(r"Unsupported value: '([a-zA-Z_]+)'"),
    re.compile(r"'param': '([a-zA-Z_]+)'"),
)


def _unsupported_param(text: str) -> Optional[str]:
    """Достаёт имя параметра, на который пожаловался сервер, или None."""
    for rx in _PARAM_RES:
        m = rx.search(text)
        if m:
            return m.group(1)
    return None


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
        # Имя параметра лимита ответа различается: у большинства OpenAI-совместимых
        # серверов и у NVIDIA NIM это max_tokens, у новых моделей OpenAI (o-серия, gpt-5)
        # — max_completion_tokens. Подбираем на первом же запросе и запоминаем.
        self._token_param = "max_tokens"
        self._drop: set[str] = set()  # параметры, которые эта модель не принимает
        self._budget = self.cfg.max_tokens

    def available(self) -> bool:
        return self.cfg.enabled

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.cfg.api_key, base_url=self.cfg.base_url, timeout=self.cfg.timeout)
        return self._client

    def _common(self) -> Dict[str, Any]:
        """Параметры, которые одинаковы для обычного запроса и для агентного цикла."""
        kwargs: Dict[str, Any] = {"model": self.cfg.model, "max_tokens": self._budget}
        if self.cfg.extra_body:
            kwargs["extra_body"] = self.cfg.extra_body
        return kwargs

    def _create(self, **kwargs: Any):
        """Запрос к модели, подстраивающийся под её требования.

        Разные модели принимают разный набор параметров: у большинства
        OpenAI-совместимых серверов и у NVIDIA NIM это max_tokens, у новых моделей
        OpenAI (o-серия, gpt-5) — max_completion_tokens, и они же отвергают
        собственную temperature. Сервер в ответе прямо называет неподходящий
        параметр, поэтому мы его переименовываем или убираем и пробуем снова,
        запоминая решение на процесс.

        Без этого один неподдержанный параметр ронял запрос, агент молча уходил
        в шаблонный режим, и со стороны выглядело так, будто ключ не работает.
        """
        for _ in range(4):
            payload = {k: v for k, v in kwargs.items() if k not in self._drop}
            # Имя и ЗНАЧЕНИЕ лимита берём из текущего состояния, а не из того, что
            # передал вызывающий: иначе поднятый лимит не доезжает до повторной попытки.
            payload.pop("max_tokens", None)
            payload.pop("max_completion_tokens", None)
            if "max_tokens" not in self._drop and "max_completion_tokens" not in self._drop:
                payload[self._token_param] = self._budget
            try:
                return self.client.chat.completions.create(**payload)
            except Exception as exc:  # noqa: BLE001 — тип зависит от SDK, разбираем текст
                text = str(exc)
                name = _unsupported_param(text)
                if name is None:
                    raise
                if name == "max_tokens" and "max_completion_tokens" in text:
                    self._token_param = "max_completion_tokens"
                    # У рассуждающих моделей токены размышления списываются из того же
                    # лимита, поэтому 2048 уходит на рассуждение, а на ответ не остаётся.
                    if not self.cfg.max_tokens_explicit:
                        self._budget = max(self._budget, 8192)
                    log.info(
                        "Модель просит max_completion_tokens; лимит ответа — %s", self._budget
                    )
                    continue
                if name in self._drop:
                    raise
                self._drop.add(name)
                log.info("Модель не принимает параметр %s — убрали из запросов", name)
        raise RuntimeError("Модель отвергает параметры запроса даже после подстройки")

    # ------------------------------------------------------------------
    def chat_json(self, system: str, user: str, temperature: Optional[float] = None) -> Any:
        """Один запрос → JSON-объект. Сначала пробуем response_format, при ошибке — обычный текст."""
        kwargs = dict(
            **self._common(),
            temperature=self.cfg.temperature if temperature is None else temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        try:
            resp = self._create(response_format={"type": "json_object"}, **kwargs)
        except Exception:
            resp = self._create(**kwargs)
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise ValueError(
                "Модель вернула пустой ответ — вероятно, весь лимит ушёл на размышление. "
                "Увеличьте LLM_MAX_TOKENS."
            )
        return extract_json(content)

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
            resp = self._create(
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
        resp = self._create(**self._common(), temperature=self.cfg.temperature, messages=messages)
        return {"result": extract_json(resp.choices[0].message.content or "{}"), "tool_calls": log}


_llm: Optional[LLM] = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm
