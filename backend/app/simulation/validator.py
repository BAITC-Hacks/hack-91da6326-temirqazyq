"""Scenario constraints with stable, user-readable structured errors."""

from collections import Counter
from typing import Any, Iterable

from pydantic import ValidationError

from app.models import Decision
from app.repository import Repository, load_repository


def normalize_decisions(decisions: Iterable[Decision | dict[str, Any]]) -> list[Decision]:
    return sorted(
        [decision if isinstance(decision, Decision) else Decision.model_validate(decision)
         for decision in decisions],
        key=lambda decision: (decision.measure_id, decision.district or ""),
    )


def validate(
    decisions: list[Decision | dict[str, Any]],
    *,
    preview: bool = False,
    repository: Repository | None = None,
) -> dict[str, Any]:
    repository = repository or load_repository()
    errors: list[dict[str, str]] = []

    def error(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    if not isinstance(decisions, list):
        return {"valid": False, "errors": [{
            "code": "INVALID_DECISION", "message": "Поле decisions должно быть списком решений."
        }]}

    try:
        normalized = normalize_decisions(decisions)
    except (ValidationError, TypeError):
        return {"valid": False, "errors": [{
            "code": "INVALID_DECISION", "message": "Каждое решение должно содержать measure_id и допустимый district."
        }]}

    required = repository.config["required_decisions"]
    if (not preview and len(normalized) != required) or (preview and len(normalized) > required):
        error("DECISION_COUNT", f"Для финального сценария нужно ровно {required} решений; preview допускает от 0 до {required}.")

    counts = Counter(decision.measure_id for decision in normalized)
    for measure_id, count in counts.items():
        if count > 1:
            error("DUPLICATE_MEASURE", f"Мероприятие {measure_id} можно выбрать только один раз.")

    category_counts: Counter[str] = Counter()
    spent = 0.0
    selected: dict[str, Decision] = {}
    for decision in normalized:
        measure = repository.measure_by_id.get(decision.measure_id)
        if measure is None:
            error("UNKNOWN_MEASURE", f"Неизвестное мероприятие: {decision.measure_id}.")
            continue
        selected[measure.id] = decision
        spent += measure.cost
        category_counts[measure.category] += 1
        if measure.type == "district":
            if not decision.district:
                error("DISTRICT_REQUIRED", f"Для {measure.id} необходимо выбрать район.")
            elif decision.district not in repository.district_by_name:
                error("UNKNOWN_DISTRICT", f"Неизвестный район: {decision.district}.")
        elif decision.district is not None:
            error("CITY_DISTRICT_FORBIDDEN", f"Общегородское мероприятие {measure.id} не должно содержать район.")

    budget = repository.config["budget"]
    if spent > budget:
        error("BUDGET_EXCEEDED", f"Стоимость {spent:g} превышает бюджет {budget:g}.")
    maximum = repository.config["max_per_category"]
    for category, count in category_counts.items():
        if count > maximum:
            error("CATEGORY_LIMIT", f"В направлении {category} допускается максимум {maximum} мероприятия.")

    for conflict in repository.incompatibilities:
        measure_ids = conflict["measure_ids"]
        if not all(measure_id in selected for measure_id in measure_ids):
            continue
        same_district = len({selected[measure_id].district for measure_id in measure_ids}) == 1
        if conflict["scope"] == "global" or same_district:
            error("INCOMPATIBLE_MEASURES", conflict["message"])

    return {"valid": not errors, "errors": errors}
