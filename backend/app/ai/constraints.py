"""Merge conversational patches and enforce hard constraints without guessing IDs."""

from typing import Any

from app.ai.contracts import Constraints, Intent
from app.models import Decision
from app.repository import Repository, load_repository
from app.simulation.validator import validate


def merge_intent(existing: Constraints | dict[str, Any], intent: Intent | dict[str, Any]) -> Constraints:
    current = existing if isinstance(existing, Constraints) else Constraints.model_validate(existing)
    patch = intent if isinstance(intent, Intent) else Intent.model_validate(intent)
    state = current.model_dump()
    defaults = Constraints().model_dump()
    patch_values = patch.model_dump()
    for field in patch.clear_fields:
        if field not in defaults:
            raise ValueError(f"Неизвестное ограничение для отмены: {field}")
        state[field] = defaults[field]
    for field in defaults:
        value = patch_values[field]
        if value is not None:
            if field in {"excluded_measure_ids", "locked_decisions"} and field not in patch.clear_fields:
                # An omitted item or empty model list cannot silently revoke a
                # hard condition. Explicit removal requires clear_fields plus
                # the remaining full list in the same structured patch.
                state[field] = state[field] + [item for item in value if item not in state[field]]
            else:
                state[field] = value
    result = Constraints.model_validate(state)
    for field in ("excluded_measure_ids", "preferred_categories", "analysis_indicators"):
        setattr(result, field, sorted(set(getattr(result, field))))
    if result.allowed_districts is not None:
        result.allowed_districts = sorted(set(result.allowed_districts))
    return result


def effective_budget(constraints: Constraints, repository: Repository | None = None) -> float:
    total = (repository or load_repository()).config["budget"]
    return min(total, constraints.max_budget, total - constraints.reserve_budget)


def candidate_diagnostics(
    decisions: list[Decision | dict[str, Any]], constraints: Constraints,
    repository: Repository | None = None,
) -> dict[str, Any]:
    """Explain draft costs and counts without simulating an invalid scenario."""
    repository = repository or load_repository()
    category_counts = {category: 0 for category in repository.config["categories"]}
    breakdown = []
    known_spent = 0.0
    unknown = []
    for raw in decisions:
        decision = raw if isinstance(raw, Decision) else Decision.model_validate(raw)
        measure = repository.measure_by_id.get(decision.measure_id)
        breakdown.append({
            "measure_id": decision.measure_id, "district": decision.district,
            "category": measure.category if measure else None,
            "cost": measure.cost if measure else None,
        })
        if measure:
            # The validator counts every occurrence, including duplicate IDs.
            known_spent += measure.cost
            category_counts[measure.category] += 1
        else:
            unknown.append(decision.measure_id)
    limit = effective_budget(constraints, repository)
    budget = {
        "spent": None if unknown else known_spent,
        "limit": limit,
        "over_by": None if unknown else max(0.0, known_spent - limit),
    }
    if unknown:
        budget["known_spent"] = known_spent
    return {
        "budget": budget,
        "cost_complete": not unknown,
        "category_counts": category_counts,
        "max_per_category": repository.config["max_per_category"],
        "cost_breakdown": breakdown,
        **({"unknown_measure_ids": sorted(set(unknown))} if unknown else {}),
    }


def validate_constraints(
    constraints: Constraints | dict[str, Any], repository: Repository | None = None
) -> dict[str, Any]:
    repository = repository or load_repository()
    constraints = constraints if isinstance(constraints, Constraints) else Constraints.model_validate(constraints)
    errors: list[dict[str, str]] = []
    contradiction = False

    def error(code: str, message: str, *, proven: bool = False) -> None:
        nonlocal contradiction
        errors.append({"code": code, "message": message})
        contradiction |= proven

    for identifier in constraints.excluded_measure_ids:
        if identifier not in repository.measure_by_id:
            error("UNKNOWN_MEASURE", f"Неизвестное мероприятие {identifier}; уточните ID.")
    for name in ([constraints.focus_district] if constraints.focus_district is not None else []) + (constraints.allowed_districts or []):
        if name not in repository.district_by_name:
            error("UNKNOWN_DISTRICT", f"Неизвестный район {name}; уточните название.")
    for category in constraints.preferred_categories:
        if category not in repository.config["categories"]:
            error("UNKNOWN_CATEGORY", f"Неизвестное направление {category}.")
    for indicator in constraints.analysis_indicators:
        if indicator not in repository.config["weights"]:
            error("UNKNOWN_INDICATOR", f"Неизвестный показатель {indicator}.")
    locked = constraints.locked_decisions
    locked_validation = validate(locked, preview=True, repository=repository)
    for issue in locked_validation["errors"]:
        error(issue["code"], f"Зафиксированные решения: {issue['message']}", proven=issue["code"] not in {"UNKNOWN_MEASURE", "UNKNOWN_DISTRICT", "DISTRICT_REQUIRED"})
    for decision in locked:
        if decision.measure_id in constraints.excluded_measure_ids:
            error("LOCKED_EXCLUDED", f"{decision.measure_id} одновременно зафиксировано и исключено.", proven=True)
        measure = repository.measure_by_id.get(decision.measure_id)
        if measure and measure.type == "district" and constraints.allowed_districts is not None and decision.district not in constraints.allowed_districts:
            error("LOCKED_DISTRICT_FORBIDDEN", f"Район зафиксированной меры {decision.measure_id} не входит в разрешённые.", proven=True)
    limit = effective_budget(constraints, repository)
    locked_cost = sum(repository.measure_by_id[item.measure_id].cost for item in locked if item.measure_id in repository.measure_by_id)
    if locked_cost > limit:
        error("LOCKED_BUDGET_EXCEEDED", "Зафиксированные решения превышают эффективный бюджет.", proven=True)
    available = [
        measure for measure in repository.measures
        if measure.id not in constraints.excluded_measure_ids
        and (measure.type == "city" or constraints.allowed_districts != [])
    ]
    required = repository.config["required_decisions"]
    locked_ids = {item.measure_id for item in locked}
    remaining = sorted(measure.cost for measure in available if measure.id not in locked_ids)
    slots = max(0, required - len(locked_ids))
    if len(available) < required:
        error("INSUFFICIENT_MEASURES", "После исключений недостаточно уникальных мер для пяти решений.", proven=True)
    elif len(remaining) >= slots and locked_cost + sum(remaining[:slots]) > limit:
        error("BUDGET_CONTRADICTION", "Даже минимальная стоимость пяти допустимых по исключениям мер выше лимита.", proven=True)
    return {
        "valid": not errors,
        "errors": errors,
        "contradiction": contradiction,
        "clarification_required": bool(errors),
        "effective_budget": limit,
    }


def validate_candidate_constraints(
    decisions: list[Decision | dict[str, Any]], constraints: Constraints,
    repository: Repository | None = None,
) -> list[dict[str, str]]:
    repository = repository or load_repository()
    normalized = [item if isinstance(item, Decision) else Decision.model_validate(item) for item in decisions]
    errors = []
    chosen = {(item.measure_id, item.district) for item in normalized}
    for decision in normalized:
        if decision.measure_id in constraints.excluded_measure_ids:
            errors.append({"code": "EXCLUDED_MEASURE", "message": f"{decision.measure_id} исключено пользователем."})
        measure = repository.measure_by_id.get(decision.measure_id)
        if measure and measure.type == "district" and constraints.allowed_districts is not None and decision.district not in constraints.allowed_districts:
            errors.append({"code": "DISTRICT_NOT_ALLOWED", "message": f"Назначение {decision.measure_id} в {decision.district} запрещено ограничениями."})
    for locked in constraints.locked_decisions:
        if (locked.measure_id, locked.district) not in chosen:
            errors.append({"code": "LOCKED_DECISION_MISSING", "message": f"Нужно сохранить {locked.measure_id} в районе {locked.district or 'город'}."})
    spent = sum(repository.measure_by_id[item.measure_id].cost for item in normalized if item.measure_id in repository.measure_by_id)
    limit = effective_budget(constraints, repository)
    if spent > limit:
        subject = "Стоимость" if all(item.measure_id in repository.measure_by_id for item in normalized) else "Стоимость известных мероприятий"
        errors.append({"code": "USER_BUDGET_EXCEEDED", "message": f"{subject} {spent:g} превышает пользовательский бюджет с учётом резерва {limit:g} на {spent - limit:g}."})
    return errors
