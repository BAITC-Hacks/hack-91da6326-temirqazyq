"""Budget-pruned measure backtracking followed by bounded assignment beams.

Every feasible measure combination receives an assignment search allowance. The
bound therefore does not cut the search off at an arbitrary measure-ID prefix.
The cap is deterministic (rather than wall-clock driven), so repeated requests
produce the same decisions and objective values on the same dataset.
"""

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.repository import load_repository
from app.simulation.engine import evaluate, simulate

from .objectives import Metrics, Priority, objective_description, objective_values


MAX_CANDIDATE_STATES = 60_000
MAX_BEAM_WIDTH = 12
DECISION_COUNT = 5


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focus_district: str | None = None
    max_budget: float = Field(default=100.0, ge=0, le=100)
    reserve_budget: float = Field(default=0.0, ge=0, le=100)
    exclude_measures: list[str] = Field(default_factory=list, max_length=14)
    priority: Priority = "balanced"
    limit: int = Field(default=4, ge=3, le=5)

    @field_validator("focus_district")
    @classmethod
    def known_district(cls, value: str | None) -> str | None:
        if value is not None and value not in load_repository().district_by_name:
            raise ValueError("Неизвестный район")
        return value

    @field_validator("exclude_measures")
    @classmethod
    def known_measures(cls, values: list[str]) -> list[str]:
        unknown = set(values) - set(load_repository().measure_by_id)
        if unknown:
            raise ValueError("Неизвестные мероприятия: " + ", ".join(sorted(unknown)))
        return sorted(set(values))


@dataclass(frozen=True)
class Candidate:
    # Internal district is an empty string for city measures; API omits the key.
    decisions: tuple[tuple[str, str], ...]
    objective: tuple[float, ...]


def _decisions(items: tuple[tuple[str, str], ...]) -> list[dict[str, str]]:
    return [
        {"measure_id": measure_id, **({"district": district} if district else {})}
        for measure_id, district in items
    ]


def _ordered(candidates: list[Candidate]) -> list[Candidate]:
    # A canonical signature resolves exact objective ties without randomization.
    return sorted(candidates, key=lambda item: (tuple(-v for v in item.objective), item.decisions))


def _measure_combinations(repository: Any, excluded: set[str], budget: float) -> list[tuple[str, ...]]:
    measures = sorted(
        (measure for measure in repository.measures if measure.id not in excluded),
        key=lambda measure: int(measure.id.removeprefix("M")),
    )
    forbidden = [
        set(rule["measure_ids"])
        for rule in repository.incompatibilities
        if rule["scope"] == "global"
    ]
    combinations: list[tuple[str, ...]] = []

    def visit(start: int, chosen: tuple[str, ...], cost: float, categories: Counter[str]) -> None:
        needed = DECISION_COUNT - len(chosen)
        if needed == 0:
            combinations.append(chosen)
            return
        if len(measures) - start < needed:
            return
        # An optimistic lower cost bound safely prunes whole subtrees.
        cheapest = sorted(measure.cost for measure in measures[start:])[:needed]
        if cost + sum(cheapest) > budget:
            return
        for index in range(start, len(measures) - needed + 1):
            measure = measures[index]
            if cost + measure.cost > budget or categories[measure.category] >= 2:
                continue
            selected = chosen + (measure.id,)
            if any(pair.issubset(selected) for pair in forbidden):
                continue
            categories[measure.category] += 1
            visit(index + 1, selected, cost + measure.cost, categories)
            categories[measure.category] -= 1

    visit(0, (), 0.0, Counter())
    return combinations


def search(request: SearchRequest) -> dict[str, Any]:
    """Return good feasible scenarios, without claiming a global optimum.

    The reserve applies to the original 100-unit envelope: the effective spending
    limit is min(max_budget, 100 - reserve_budget), not max_budget - reserve_budget.
    A focus district resolves ties after the objective's required score criteria.
    """
    started = perf_counter()
    repository = load_repository()
    effective_budget = min(request.max_budget, 100.0 - request.reserve_budget)
    combinations = _measure_combinations(repository, set(request.exclude_measures), effective_budget)
    metadata: dict[str, Any] = {
        "evaluated": 0,
        "truncated": False,
        "elapsed_ms": 0.0,
        "effective_budget": effective_budget,
        "objective": request.priority,
        "notes": [
            "Лимит расходов = min(max_budget, 100 − reserve_budget).",
            objective_description(request.priority, bool(request.focus_district)),
        ],
    }
    if not combinations:
        metadata["notes"].append(
            "При этих ограничениях невозможно выбрать пять уникальных совместимых мероприятий. "
            "Увеличьте бюджет или уменьшите список исключений."
        )
        metadata["elapsed_ms"] = (perf_counter() - started) * 1000
        return {"scenarios": [], "search": metadata}

    baseline = evaluate([], repository=repository)
    district_names = tuple(district.name for district in repository.districts)
    district_count = len(district_names)
    if not district_count:
        metadata["notes"].append("В наборе данных отсутствуют районы.")
        metadata["elapsed_ms"] = (perf_counter() - started) * 1000
        return {"scenarios": [], "search": metadata}
    local_conflicts = [
        tuple(rule["measure_ids"])
        for rule in repository.incompatibilities
        if rule["scope"] == "same_district"
    ]
    cache: dict[tuple[tuple[str, str], ...], tuple[float, ...]] = {}

    def score(items: tuple[tuple[str, str], ...]) -> Candidate:
        canonical = tuple(sorted(items))
        objective = cache.get(canonical)
        if objective is None:
            result = evaluate(_decisions(canonical), repository=repository)
            focus_delta = (
                result["district_scores"][request.focus_district]
                - baseline["district_scores"][request.focus_district]
                if request.focus_district
                else 0.0
            )
            metrics: Metrics = {
                "score": result["score"],
                "weakest": result["weakest_district"]["score"],
                "critical": len(result["critical"]),
                "category_deltas": result["category_deltas"],
                "focus_delta": focus_delta,
            }
            objective = objective_values(metrics, request.priority)
            cache[canonical] = objective
        return Candidate(canonical, objective)

    # Distribute the fixed state allowance over every valid measure set. Even
    # when pruning assignments, no measure set loses out because of ID order.
    allowance = MAX_CANDIDATE_STATES // len(combinations)
    finalists: list[Candidate] = []
    for combination in combinations:
        city = tuple(
            (identifier, "")
            for identifier in combination
            if repository.measure_by_id[identifier].type == "city"
        )
        local = tuple(
            identifier
            for identifier in combination
            if repository.measure_by_id[identifier].type == "district"
        )
        if not local:
            finalists.append(score(city))
            continue
        # At most D + (K-1)*D*width scored states for K district decisions.
        beam_width = (
            min(MAX_BEAM_WIDTH, max(1, (allowance - district_count) // (district_count * (len(local) - 1))))
            if len(local) > 1
            else district_count
        )
        beam = [Candidate(tuple(sorted(city)), ())]
        for identifier in local:
            expanded: list[Candidate] = []
            for candidate in beam:
                assigned = dict(candidate.decisions)
                for district in district_names:
                    assignment = {**assigned, identifier: district}
                    if any(
                        all(measure_id in assignment for measure_id in pair)
                        and len({assignment[measure_id] for measure_id in pair}) == 1
                        for pair in local_conflicts
                    ):
                        continue
                    expanded.append(score(candidate.decisions + ((identifier, district),)))
            ordered = _ordered(expanded)
            if len(ordered) > beam_width:
                metadata["truncated"] = True
            beam = ordered[:beam_width]
        finalists.extend(beam)

    selected = _ordered(finalists)[: request.limit]
    names = {
        "balanced": "Сбалансированный подход",
        "overall_score": "Качество жизни",
        "weakest_district": "Поддержка слабого района",
        "transport": "Транспорт",
        "ecology": "Экология",
        "social": "Социальная инфраструктура",
        "safety": "Безопасность",
        "services": "Городские сервисы",
        "reduce_critical": "Снижение критических показателей",
    }
    scenarios = []
    for index, candidate in enumerate(selected):
        decisions = _decisions(candidate.decisions)
        signature = "|".join(f"{measure_id}:{district}" for measure_id, district in candidate.decisions)
        scenarios.append(
            {
                "id": sha256(signature.encode("utf-8")).hexdigest()[:12],
                "name": f"{names[request.priority]} · {index + 1}",
                "decisions": decisions,
                "result": simulate(decisions, repository=repository),
                "objective_value": list(candidate.objective),
            }
        )
    metadata["evaluated"] = len(cache)
    if metadata["truncated"]:
        metadata["notes"].append(
            "Поиск ограничен детерминированным beam search: проверяются все допустимые наборы мер, "
            "но только часть назначений по районам. Возвращены сильные найденные альтернативы; "
            "глобальная оптимальность не доказана. Лимит — 60 000 состояний кандидатов."
        )
    else:
        metadata["notes"].append("Проверены все допустимые назначения для выбранных ограничений.")
    metadata["notes"].append("evaluated учитывает уникальные частичные и полные состояния кандидатов.")
    metadata["elapsed_ms"] = (perf_counter() - started) * 1000
    return {"scenarios": scenarios, "search": metadata}
