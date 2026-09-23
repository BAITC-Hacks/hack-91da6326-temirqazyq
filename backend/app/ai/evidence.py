"""Bind narrative references to server facts; never use model numbers as metrics."""

import re
from typing import Any

from app.ai.contracts import Constraints, Narrative
from app.repository import load_repository

PROMPT_VERSION = "akim-agent-v2.6"
# A reference can contain list indexes; their closing brackets are not the
# closing delimiter of the enclosing [fact:...] placeholder.
PLACEHOLDER = re.compile(r"\[fact:((?:[^\[\]]|\[[0-9]+\])+)\]")
BRACKET_INDEX = re.compile(r"\[(0|[1-9][0-9]*)\]")


def _collection_scalar_facts(prefix: str, value: Any, facts: dict[str, Any]) -> None:
    """Expose actual collection leaves, with canonical dot-separated indexes."""
    if isinstance(value, dict):
        for key, child in value.items():
            _collection_scalar_facts(f"{prefix}.{key}", child, facts)
    elif isinstance(value, list):
        facts[f"{prefix}.count"] = len(value)
        for index, child in enumerate(value):
            _collection_scalar_facts(f"{prefix}.{index}", child, facts)
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        facts[prefix] = value


def facts_for(scenarios: list[dict[str, Any]], constraints: Constraints) -> dict[str, Any]:
    config = load_repository().config
    facts: dict[str, Any] = {"rules.critical_threshold": config["critical_threshold"], "rules.horizon": config["horizon"]}
    for index, row in enumerate(scenarios):
        identifier, result = chr(65 + index), row["result"]
        for section in ("score", "budget", "category_deltas", "score_decomposition"):
            for key, value in result.get(section, {}).items():
                facts[f"{identifier}.{section}.{key}"] = value
        for stage in ("before", "after"):
            # Qualitative claims can cite the actual collection, including an
            # empty one. Its numeric count is a separate fact, never an alias.
            facts[f"{identifier}.critical_{stage}"] = result[f"critical_{stage}"]
            _collection_scalar_facts(f"{identifier}.critical_{stage}", result[f"critical_{stage}"], facts)
            for critical in result[f"critical_{stage}"]:
                facts[f"{identifier}.districts.{critical['district']}.{stage}.{critical['indicator']}"] = critical["value"]
            for key, value in result["weakest_district"][stage].items():
                facts[f"{identifier}.weakest_district.{stage}.{key}"] = value
        facts[f"{identifier}.activated_synergies"] = result["activated_synergies"]
        _collection_scalar_facts(f"{identifier}.activated_synergies", result["activated_synergies"], facts)
        for name, district in result["districts"].items():
            for stage in ("before", "after"):
                facts[f"{identifier}.districts.{name}.score_{stage}"] = district[f"score_{stage}"]
            for indicator, delta in district["indicator_deltas"].items():
                if delta or (name == constraints.focus_district and (not constraints.analysis_indicators or indicator in constraints.analysis_indicators)):
                    for field, label in (("indicators_before", "before"), ("indicators_after", "after"), ("indicator_deltas", "delta")):
                        facts[f"{identifier}.districts.{name}.{label}.{indicator}"] = district[field][indicator]
    return facts


def ground_narrative(value: Narrative, facts: dict[str, Any], scenario_ids: list[str]) -> dict[str, Any]:
    if set(value.scenario_ids) != set(scenario_ids):
        raise ValueError("Объяснение ссылается на неподтверждённый или пропущенный сценарий.")
    aliases = {identifier: chr(65 + index) for index, identifier in enumerate(scenario_ids)}

    def normalize_reference(reference: str) -> str | None:
        if reference in facts:
            return reference
        # This is syntax normalization, never expression evaluation or inferred
        # traversal: the exact resulting key must already exist in server facts.
        normalized = BRACKET_INDEX.sub(r".\1", reference)
        prefix, separator, rest = normalized.partition(".")
        if separator and prefix in aliases:
            normalized = aliases[prefix] + "." + rest
        for old, new in (("indicators_before", "before"), ("indicators_after", "after"), ("indicator_deltas", "delta")):
            normalized = normalized.replace(f".{old}.", f".{new}.")
        return normalized if normalized in facts else None

    def unknown_reference_message(references: list[str]) -> str:
        examples = "; ".join(reference[:120] for reference in list(dict.fromkeys(references))[:3])
        return f"Объяснение содержит неизвестную ссылку на факт: {examples}"

    unknown = [reference for reference in value.evidence_refs if normalize_reference(reference) is None]
    if unknown:
        raise ValueError(unknown_reference_message(unknown))
    references = list(dict.fromkeys(normalize_reference(reference) for reference in value.evidence_refs))
    used: set[str] = set()
    repository = load_repository()
    identifiers = set(repository.measure_by_id) | set(repository.config["weights"])
    known_identifier = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(identifier) for identifier in sorted(identifiers, key=len, reverse=True)) + r")(?!\w)")

    def render(text: str) -> str:
        raw_text = PLACEHOLDER.sub("", text)
        if "[fact:" in raw_text:
            raise ValueError("Объяснение содержит незавершённую ссылку на факт.")
        raw_text = known_identifier.sub("", raw_text)
        if any(character.isdigit() for character in raw_text):
            raise ValueError("Числа в пояснениях должны быть ссылками на рассчитанные факты.")

        def substitute(match: re.Match[str]) -> str:
            key = normalize_reference(match.group(1))
            if key is None:
                raise ValueError(unknown_reference_message([match.group(1)]))
            if key not in references:
                raise ValueError("Числовое утверждение не связано с проверенным фактом.")
            used.add(key)
            item = facts[key]
            if isinstance(item, (list, dict)):
                raise ValueError(f"Ссылка {key} содержит список или объект. Для количества используйте {key}.count; в текст подставляйте только отдельное значение.")
            return f"{item:.2f}" if isinstance(item, float) else str(item)

        return PLACEHOLDER.sub(substitute, text)

    result = value.model_dump()
    result["evidence_refs"] = references
    result["summary"] = render(value.summary)
    for field in ("observations", "remaining_issues", "tradeoffs", "limitations"):
        result[field] = [render(text) for text in result[field]]
    result["source"] = "openai"
    result["evidence"] = {key: facts[key] for key in sorted(set(references) | used)}
    return result


def template_narrative(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    from app.ai.fallback import explain_comparison, explain_simulation

    if not scenarios:
        return {"summary": "Шаблон не генерирует варианты. Используйте явный алгоритмический поиск.", "observations": [], "remaining_issues": [], "tradeoffs": [], "limitations": ["Шаблонное объяснение, без вызова модели."], "evidence_refs": [], "scenario_ids": [], "source": "template"}
    result = explain_comparison(scenarios[0]["result"], scenarios[1]["result"]) if len(scenarios) > 1 else explain_simulation(scenarios[0]["result"])
    return {
        "summary": result.summary, "observations": result.strengths,
        "remaining_issues": result.risks, "tradeoffs": result.tradeoffs,
        "limitations": ["Шаблонное объяснение, без вызова модели.", "Синтетическая модель; результат не является прогнозом реального города."],
        "evidence_refs": [], "scenario_ids": [row["scenario_id"] for row in scenarios], "source": "template",
    }

