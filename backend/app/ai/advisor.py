import json
import logging
import os
import re
from typing import Any

from .fallback import explain_comparison, explain_simulation
from .prompts import SYSTEM_PROMPT
from .schemas import Explanation, ExplanationText

logger = logging.getLogger(__name__)
NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?")


def _display_facts(value: Any) -> Any:
    """Provide the exact rounded strings the model is allowed to quote."""
    if isinstance(value, dict):
        return {key: _display_facts(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_display_facts(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return value


def _numeric_tokens(text: str) -> set[float]:
    return {float(item.replace(",", ".")) for item in NUMBER.findall(text)}


def explain(result: dict[str, Any], comparison: dict[str, Any] | None = None) -> Explanation:
    fallback = explain_comparison(result, comparison) if comparison else explain_simulation(result)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return fallback
    payload = {"scenario_a": result, "scenario_b": comparison} if comparison else result
    facts = _display_facts(payload)
    # Template contains deterministic counts and display values as well as raw engine facts.
    supplied = json.dumps({"display_facts": facts, "deterministic_explanation": fallback.model_dump(exclude={"source"})}, ensure_ascii=False)
    try:
        from openai import OpenAI

        with OpenAI(api_key=api_key, timeout=12.0, max_retries=0) as client:
            response = client.responses.parse(
                model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                input=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": supplied}],
                text_format=ExplanationText,
                max_output_tokens=1400,
                store=False,
            )
        parsed = response.output_parsed
        if parsed is None:
            return fallback
        if not _numeric_tokens(parsed.model_dump_json()).issubset(_numeric_tokens(supplied)):
            logger.warning("Advisor returned unsupported numeric values; using deterministic explanation")
            return fallback
        return Explanation(**parsed.model_dump(), source="openai")
    except Exception as error:
        # No provider response, key, or user payload is written to logs.
        logger.warning("Advisor unavailable (%s); using deterministic explanation", type(error).__name__)
        return fallback
