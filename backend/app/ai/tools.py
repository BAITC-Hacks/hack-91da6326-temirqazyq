"""Whitelisted model tools. Model text never supplies authoritative numbers."""

import asyncio
import hashlib
import json
from typing import Any

from pydantic import ValidationError

from app.ai.constraints import candidate_diagnostics, effective_budget, validate_candidate_constraints, validate_constraints
from app.ai.contracts import Candidate, CompareArguments, Constraints, EmptyArguments, EvaluateArguments
from app.models import Decision
from app.optimizer.search import SearchRequest, search
from app.repository import load_repository
from app.simulation.engine import simulate
from app.simulation.validator import validate
from app.storage import Store


def canonical_decisions(decisions: list[Decision | dict[str, Any]]) -> str:
    normalized = [item.model_dump() if isinstance(item, Decision) else {"measure_id": item["measure_id"], "district": item.get("district")} for item in decisions]
    normalized.sort(key=lambda item: (item["measure_id"], item["district"] or ""))
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dataset_version() -> str:
    repository = load_repository()
    datasets = {
        "districts": [item.model_dump() for item in repository.districts],
        "measures": [item.model_dump() for item in repository.measures],
        "config": repository.config,
        "synergies": repository.synergies,
        "incompatibilities": repository.incompatibilities,
    }
    return hashlib.sha256(json.dumps(datasets, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def build_facts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    facts: dict[str, Any] = {}

    def visit(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(f"{prefix}.{key}", child)
        elif isinstance(value, list):
            facts[f"{prefix}.count"] = len(value)
            for index, child in enumerate(value):
                visit(f"{prefix}.{index}", child)
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            facts[prefix] = value

    for row in rows:
        visit(row["scenario_id"], row["result"])
    return facts


def _strict_schema(model: Any) -> dict[str, Any]:
    schema = model.model_json_schema()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                value["additionalProperties"] = False
                value["required"] = list(value.get("properties", {}))
            value.pop("default", None)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return schema


def tool_schemas(mode: str = "ai") -> list[dict[str, Any]]:
    definitions = [
        ("get_city_context", "Исходные данные, правила и текущие решения; никаких внешних источников.", EmptyArguments),
        ("evaluate_scenarios", "Проверить до трёх черновиков: только name и decisions, без score, cost или effects. Ошибки можно исправить в следующем раунде.", EvaluateArguments),
        ("compare_scenarios", "Сравнить 2–3 ранее проверенных сценария текущей сессии по серверным ID.", CompareArguments),
    ]
    result = [{"type": "function", "name": name, "description": description, "parameters": _strict_schema(model), "strict": True} for name, description, model in definitions]
    if mode == "algorithmic":
        constraints_schema = _strict_schema(Constraints)
        definitions = constraints_schema.pop("$defs", {})
        result.append({
            "type": "function", "name": "search_scenarios", "description": "Явный ограниченный алгоритмический поиск с текущими жёсткими ограничениями.", "strict": True,
            "parameters": {"type": "object", "$defs": definitions, "properties": {"constraints": constraints_schema}, "required": ["constraints"], "additionalProperties": False},
        })
    return result


def _error(code: str, message: str) -> dict[str, Any]:
    return {"valid": False, "errors": [{"code": code, "message": message}]}


class ToolDispatcher:
    def __init__(self, store: Store, session_id: str, run_id: str, constraints: Constraints | dict[str, Any], current_decisions: list[Decision | dict[str, Any]], mode: str = "ai", max_candidates: int = 3):
        self.store = store
        self.session_id = session_id
        self.run_id = run_id
        self.constraints = constraints if isinstance(constraints, Constraints) else Constraints.model_validate(constraints)
        self.current_decisions = [item.model_dump() if isinstance(item, Decision) else dict(item) for item in current_decisions]
        self.mode = mode
        self.max_candidates = min(max_candidates, 3)
        self.scenarios: list[dict[str, Any]] = []
        self.facts: dict[str, Any] = {}
        self.seen_candidates: dict[str, dict[str, Any]] = {}
        self.last_evaluation: dict[str, Any] | None = None
        self.repository = load_repository()
        self.version = dataset_version()

    @property
    def tools(self) -> list[dict[str, Any]]:
        return tool_schemas(self.mode)

    def schemas(self) -> list[dict[str, Any]]:
        return self.tools

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        names = {item["name"] for item in self.tools}
        if name not in names:
            result = _error("UNKNOWN_TOOL", "Инструмент не разрешён в выбранном режиме.")
        elif not isinstance(arguments, dict):
            result = _error("INVALID_TOOL_ARGUMENTS", "Аргументы инструмента должны быть JSON-объектом.")
        else:
            try:
                if name == "get_city_context":
                    EmptyArguments.model_validate(arguments)
                    result = self._context()
                elif name == "evaluate_scenarios":
                    result = self._evaluate(arguments)
                elif name == "compare_scenarios":
                    result = self._compare(CompareArguments.model_validate(arguments).scenario_ids)
                else:
                    result = await self._search(arguments)
            except (ValidationError, ValueError, TypeError, KeyError):
                result = _error("INVALID_TOOL_ARGUMENTS", "Неверная структура аргументов инструмента; используйте только поля схемы.")
        status = "ok" if result.get("valid", True) else "rejected"
        errors = list(result.get("errors", []))
        if name == "evaluate_scenarios":
            self.last_evaluation = result
            candidates = result.get("candidates", [])
            rejected = [item for item in candidates if not item.get("valid")]
            if rejected:
                status = "rejected" if len(rejected) == len(candidates) else "partial"
            errors.extend(error for item in candidates for error in item.get("errors", []))
        self.store.log_tool(self.session_id, self.run_id, name, status, {
            "verified_scenarios": len(self.scenarios),
            "error_codes": list(dict.fromkeys(item["code"] for item in errors)),
        })
        return result

    def _context(self) -> dict[str, Any]:
        return {
            "dataset_version": self.version,
            "synthetic": True,
            "districts": [item.model_dump() for item in self.repository.districts],
            "measures": [item.model_dump() for item in self.repository.measures],
            "rules": self.repository.config,
            "synergies": self.repository.synergies,
            "incompatibilities": self.repository.incompatibilities,
            "constraints": self.constraints.model_dump(),
            "effective_budget": effective_budget(self.constraints, self.repository),
            "current_decisions": self.current_decisions,
        }

    def _cache_key(self, canonical: str) -> str:
        value = {"decisions": canonical, "constraints": self.constraints.model_dump(), "version": self.version, "mode": self.mode}
        return "candidate:" + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _accept(self, row: dict[str, Any]) -> None:
        existing_index = next((index for index, existing in enumerate(self.scenarios) if existing["scenario_id"] == row["scenario_id"]), None)
        if existing_index is not None:
            self.scenarios[existing_index] = row
        elif len(self.scenarios) < 3:
            self.scenarios.append(row)
        self.facts.update(build_facts([row]))

    def _compact(self, row: dict[str, Any]) -> dict[str, Any]:
        result = row["result"]
        focus = self.constraints.focus_district or result["weakest_district"]["after"]["name"]
        district = result["districts"][focus]
        keys = self.constraints.analysis_indicators or list(self.repository.config["weights"])
        identifier = row["scenario_id"]
        return {
            "valid": True, "scenario_id": identifier, "name": row["name"],
            "score": result["score"], "budget": result["budget"],
            "critical_count": len(result["critical_after"]), "critical_after": result["critical_after"],
            "weakest": result["weakest_district"]["after"],
            "synergies": result["activated_synergies"], "score_decomposition": result["score_decomposition"],
            "category_deltas": result["category_deltas"],
            "district_focus": {"name": focus, "indicators": {
                key: {"before": district["indicators_before"][key], "after": district["indicators_after"][key], "delta": district["indicator_deltas"][key]}
                for key in keys
            }},
        }

    def _evaluate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        candidates = arguments.get("candidates")
        if set(arguments) != {"candidates"} or not isinstance(candidates, list) or not 1 <= len(candidates) <= self.max_candidates:
            return _error("INVALID_TOOL_ARGUMENTS", f"Передайте от одного до {self.max_candidates} кандидатов в поле candidates.")
        constraint_check = validate_constraints(self.constraints, self.repository)
        if not constraint_check["valid"]:
            return constraint_check
        outcomes = []
        for index, raw in enumerate(candidates):
            try:
                candidate = Candidate.model_validate(raw)
            except ValidationError as error:
                outcomes.append({"candidate_index": index, "valid": False, "errors": [{"code": "INVALID_CANDIDATE", "message": "; ".join(f"{'.'.join(map(str, issue['loc']))}: {issue['msg']}" for issue in error.errors())}]})
                continue
            decisions = [item.model_dump() for item in candidate.decisions]
            canonical = canonical_decisions(decisions)
            if canonical in self.seen_candidates:
                outcomes.append({**self.seen_candidates[canonical], "candidate_index": index, "duplicate": True})
                continue
            key = self._cache_key(canonical)
            cached = self.store.cache_get(self.session_id, key)
            if cached and cached.get("scenario_id"):
                row = self.store.get_scenario(self.session_id, cached["scenario_id"])
                if row and len(self.scenarios) < min(self.max_candidates, self.constraints.requested_scenario_count):
                    if row["dataset_version"] != self.version:
                        outcomes.append({**_error("DATASET_CHANGED", "Версия сохранённого сценария изменилась; требуется новый расчёт."), "candidate_index": index})
                        continue
                    if canonical_decisions(row["decisions"]) != canonical:
                        outcomes.append({**_error("CACHE_MISMATCH", "Сохранённые решения не соответствуют проверяемому кандидату."), "candidate_index": index})
                        continue
                    errors = validate(row["decisions"], repository=self.repository)["errors"] + validate_candidate_constraints(row["decisions"], self.constraints, self.repository)
                    if errors:
                        outcome = {"valid": False, "errors": errors, "diagnostics": candidate_diagnostics(decisions, self.constraints, self.repository)}
                        self.store.cache_set(self.session_id, key, outcome)
                        self.seen_candidates[canonical] = outcome
                        outcomes.append({**outcome, "candidate_index": index})
                        continue
                    recomputed = simulate(row["decisions"], repository=self.repository)
                    row = {**row, "result": recomputed}
                    self._accept(row)
                    outcome = self._compact(row)
                    self.seen_candidates[canonical] = outcome
                    outcomes.append({**outcome, "candidate_index": index, "cached": True})
                    continue
            # Invalid cached drafts are inexpensive to revalidate. In particular,
            # old cache entries lack the cost diagnostics needed for correction.
            if len(self.scenarios) >= min(self.max_candidates, self.constraints.requested_scenario_count):
                outcomes.append({**_error("CANDIDATE_LIMIT", "Уже получено запрошенное число различных проверенных вариантов."), "candidate_index": index})
                continue
            model_check = validate(decisions, repository=self.repository)
            errors = model_check["errors"] + validate_candidate_constraints(decisions, self.constraints, self.repository)
            if errors:
                outcome = {"valid": False, "errors": errors, "diagnostics": candidate_diagnostics(decisions, self.constraints, self.repository)}
                self.store.cache_set(self.session_id, key, outcome)
            else:
                result = simulate(decisions, repository=self.repository)
                row = self.store.save_scenario(
                    self.session_id, decisions=result["decisions"], result=result,
                    provenance="algorithmic" if self.mode == "algorithmic" else "llm_generated",
                    constraints=self.constraints.model_dump(), dataset_version=self.version, name=candidate.name,
                )
                self._accept(row)
                outcome = self._compact(row)
                self.store.cache_set(self.session_id, key, {"scenario_id": row["scenario_id"]})
            self.seen_candidates[canonical] = outcome
            outcomes.append({**outcome, "candidate_index": index})
        return {"valid": True, "candidates": outcomes, "verified_count": len(self.scenarios)}

    def _compare(self, scenario_ids: list[str]) -> dict[str, Any]:
        if len(set(scenario_ids)) != len(scenario_ids):
            return _error("DUPLICATE_SCENARIO", "Для сравнения нужны разные сценарии.")
        rows = [self.store.get_scenario(self.session_id, identifier) for identifier in scenario_ids]
        if any(row is None for row in rows):
            return _error("SCENARIO_NOT_FOUND", "Сценарий не найден в текущей сессии.")
        if any(row["dataset_version"] != self.version for row in rows):
            return _error("DATASET_CHANGED", "Версия данных изменилась; пересчитайте сохранённый сценарий перед сравнением.")
        if len({row["scenario_id"] for row in [*self.scenarios, *rows]}) > 3:
            return _error("SCENARIO_LIMIT", "В одном запуске можно анализировать не более трёх различных сценариев.")
        verified = []
        for row in rows:
            constraint_errors = validate_candidate_constraints(row["decisions"], self.constraints, self.repository)
            if constraint_errors:
                return {"valid": False, "errors": constraint_errors, "diagnostics": candidate_diagnostics(row["decisions"], self.constraints, self.repository)}
            recomputed = simulate(row["decisions"], repository=self.repository)
            if not recomputed["valid"]:
                return {"valid": False, "errors": recomputed["errors"]}
            verified.append({**row, "result": recomputed})
        rows = verified
        for row in rows:
            self._accept(row)
        first = rows[0]
        differences = []
        for row in rows[1:]:
            a, b = first["result"], row["result"]
            difference = {
                "scenario_a": first["scenario_id"], "scenario_b": row["scenario_id"],
                "score": b["score"]["after"] - a["score"]["after"],
                "spent": b["budget"]["spent"] - a["budget"]["spent"],
                "critical_count": len(b["critical_after"]) - len(a["critical_after"]),
                "category_deltas": {category: b["category_deltas"][category] - a["category_deltas"][category] for category in self.repository.config["categories"]},
            }
            differences.append(difference)
            prefix = f"comparison.{first['scenario_id']}.{row['scenario_id']}"
            for metric in ("score", "spent", "critical_count"):
                self.facts[f"{prefix}.{metric}"] = difference[metric]
        return {"valid": True, "scenarios": [self._compact(row) for row in rows], "differences_b_minus_a": differences}

    async def _search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if set(arguments) != {"constraints"}:
            return _error("INVALID_TOOL_ARGUMENTS", "Передайте нормализованные constraints.")
        supplied = Constraints.model_validate(arguments["constraints"])
        if supplied != self.constraints:
            return _error("CONSTRAINTS_CHANGED", "Поиск не может менять ограничения текущего запуска.")
        check = validate_constraints(self.constraints, self.repository)
        if not check["valid"]:
            return check
        priorities = self.constraints.preferred_categories or ["balanced"]
        request = SearchRequest(
            focus_district=self.constraints.focus_district,
            max_budget=self.constraints.max_budget, reserve_budget=self.constraints.reserve_budget,
            exclude_measures=self.constraints.excluded_measure_ids, priority=priorities[0], limit=5,
        )
        found = await asyncio.to_thread(search, request)
        eligible = [item for item in found["scenarios"] if not validate_candidate_constraints(item["decisions"], self.constraints, self.repository)]
        candidates = [{"name": item["name"], "decisions": [{"measure_id": decision["measure_id"], "district": decision.get("district")} for decision in item["decisions"]]} for item in eligible[:min(self.max_candidates, self.constraints.requested_scenario_count)]]
        result = self._evaluate({"candidates": candidates}) if candidates else {"valid": True, "candidates": [], "verified_count": 0}
        result["search"] = found["search"]
        result["limited_search"] = True
        result["note"] = "Проверена ограниченная выборка алгоритмического поиска. Закреплённые решения и разрешённые районы отфильтрованы без ослабления правил. Отсутствие результата не доказывает невозможность; глобальный оптимум не гарантирован."
        return result
