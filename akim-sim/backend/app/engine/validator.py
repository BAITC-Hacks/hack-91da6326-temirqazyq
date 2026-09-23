"""Валидатор набора решений по правилам раздела 4 датасета.

Возвращает список нарушений с человекочитаемой причиной; Score для невалидного
набора не считается (правило 7).
"""
from __future__ import annotations

from collections import Counter
from typing import List, Optional

from .data import Dataset, load_dataset
from .models import Decision, ValidationIssue, ValidationResult, WorldState


def default_world(ds: Optional[Dataset] = None) -> WorldState:
    ds = ds or load_dataset()
    return WorldState(event_id=None, budget=ds.budget, blocked_measures=[], baseline=ds.baseline())


def validate(decisions: List[Decision], world: Optional[WorldState] = None, ds: Optional[Dataset] = None) -> ValidationResult:
    ds = ds or load_dataset()
    world = world or default_world(ds)
    issues: List[ValidationIssue] = []
    mm = ds.measure_map
    dm = ds.district_map

    # Правило: неизвестные меры / районы
    known = [d for d in decisions if d.measure_id in mm]
    for d in decisions:
        if d.measure_id not in mm:
            issues.append(ValidationIssue(rule="unknown_measure", message=f"Неизвестное мероприятие {d.measure_id}"))
        elif d.district_id is not None and d.district_id not in dm:
            issues.append(ValidationIssue(rule="unknown_district", message=f"Неизвестный район {d.district_id} для {d.measure_id}"))

    # Правило 2: ровно N решений
    if len(decisions) != ds.decisions_required:
        issues.append(ValidationIssue(rule="count", message=f"Нужно ровно {ds.decisions_required} решений, выбрано {len(decisions)}"))

    # Правило 3: без повторов
    ids = [d.measure_id for d in known]
    for mid, n in Counter(ids).items():
        if n > 1:
            issues.append(ValidationIssue(rule="duplicate", message=f"Мероприятие {mid} выбрано {n} раза — повторы запрещены"))

    # Правило 4: район обязателен для «Район», запрещён для «Город»
    for d in known:
        m = mm[d.measure_id]
        if m.is_district and not d.district_id:
            issues.append(ValidationIssue(rule="district_required", message=f"{m.id} «{m.name}» — нужно указать район"))
        if not m.is_district and d.district_id:
            issues.append(ValidationIssue(rule="district_forbidden", message=f"{m.id} «{m.name}» — городская мера, район не указывается"))

    # Правило 5: не более K мер из одного направления
    per_dir = Counter(mm[i].direction for i in ids)
    for direction, n in per_dir.items():
        if n > ds.max_per_direction:
            issues.append(ValidationIssue(rule="max_per_direction", message=f"Направление «{ds.directions[direction]}»: {n} мер, допустимо не более {ds.max_per_direction}"))

    # Правило 6: несовместимости
    chosen = {d.measure_id: d.district_id for d in known}
    for inc in ds.incompatibilities:
        if inc.a in chosen and inc.b in chosen:
            if inc.scope == "any" or (chosen[inc.a] is not None and chosen[inc.a] == chosen[inc.b]):
                issues.append(ValidationIssue(rule="incompatible", message=f"{inc.a} и {inc.b} несовместимы: {inc.reason}"))

    # Событие: заблокированные меры
    for mid in ids:
        if mid in world.blocked_measures:
            issues.append(ValidationIssue(rule="blocked_by_event", message=f"{mid} заблокировано событием «{world.event_id}» и недоступно"))

    # Правило 1: бюджет
    total = sum(mm[i].cost for i in ids)
    if total > world.budget:
        issues.append(ValidationIssue(rule="budget", message=f"Стоимость {total} превышает бюджет {world.budget} на {total - world.budget}"))

    return ValidationResult(
        valid=not issues,
        issues=issues,
        total_cost=total,
        budget=world.budget,
        remaining=world.budget - total,
        per_direction={k: per_dir.get(k, 0) for k in ds.directions},
    )
