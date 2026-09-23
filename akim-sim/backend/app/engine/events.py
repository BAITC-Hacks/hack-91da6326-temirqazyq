"""События «Чёрный лебедь»: шоки к исходным показателям, блокировки мер, секвестр бюджета.

Событие порождает новое ``WorldState``; сценарий команды пересчитывается в нём же,
чтобы было видно, как «просел» план, и можно было перераспределить бюджет.
"""
from __future__ import annotations

import random
from typing import List, Optional

from .data import Dataset, Event, Shock, load_dataset
from .models import WorldState
from .validator import default_world


def apply_event(event: Event, world: Optional[WorldState] = None, ds: Optional[Dataset] = None) -> WorldState:
    ds = ds or load_dataset()
    world = world or default_world(ds)
    baseline = {d: dict(v) for d, v in world.baseline.items()}
    for s in event.shocks:
        baseline[s.district][s.indicator] = min(100.0, max(0.0, baseline[s.district][s.indicator] + s.delta))
    return WorldState(
        event_id=event.id,
        budget=world.budget + event.budget_delta,
        blocked_measures=sorted(set(world.blocked_measures) | set(event.blocked_measures)),
        baseline=baseline,
    )


MAX_SHOCKS = 6
SHOCK_LIMIT = 25.0      # один показатель нельзя уронить сильнее чем на 25 пунктов
BUDGET_LIMIT = 40       # и нельзя срезать больше 40 единиц бюджета


def custom_event_from_spec(spec: dict, ds: Optional[Dataset] = None) -> Event:
    """Превращает ответ модели в валидное событие движка.

    Модель предлагает — движок решает. Всё, что не опознано (чужой район, несуществующий
    показатель, выдуманная мера), отбрасывается; величины зажимаются в рамки, чтобы одним
    запросом нельзя было обнулить город. Без этого произвольный текст пользователя
    давал бы модели писать прямо в состояние мира.
    """
    ds = ds or load_dataset()
    known_districts = {d.id for d in ds.districts}
    known_codes = {i.code for i in ds.indicators}
    known_measures = set(ds.measure_map)

    shocks: List[Shock] = []
    for raw in (spec.get("shocks") or [])[:MAX_SHOCKS]:
        if not isinstance(raw, dict):
            continue
        dist, code = raw.get("district"), raw.get("indicator")
        if dist not in known_districts or code not in known_codes:
            continue
        try:
            delta = float(raw.get("delta", 0))
        except (TypeError, ValueError):
            continue
        if delta == 0:
            continue
        delta = max(-SHOCK_LIMIT, min(SHOCK_LIMIT, delta))
        shocks.append(Shock(district=dist, indicator=code, delta=delta))

    blocked = [m for m in (spec.get("blocked_measures") or []) if m in known_measures][:3]

    try:
        budget_delta = int(spec.get("budget_delta") or 0)
    except (TypeError, ValueError):
        budget_delta = 0
    budget_delta = max(-BUDGET_LIMIT, min(BUDGET_LIMIT, budget_delta))

    title = str(spec.get("title") or "Внеплановая ситуация").strip()[:120]
    narrative = str(spec.get("narrative") or "").strip()[:600]
    return Event(id="custom", title=title, narrative=narrative, shocks=shocks,
                 blocked_measures=blocked, budget_delta=budget_delta)


def world_for_event(event_id: Optional[str], ds: Optional[Dataset] = None) -> WorldState:
    ds = ds or load_dataset()
    if not event_id:
        return default_world(ds)
    ev = ds.event_map.get(event_id)
    if ev is None:
        raise KeyError(f"Неизвестное событие {event_id}")
    return apply_event(ev, default_world(ds), ds)


def pick_event(seed: Optional[int] = None, exclude: Optional[List[str]] = None, ds: Optional[Dataset] = None) -> Event:
    ds = ds or load_dataset()
    pool = [e for e in ds.events if e.id not in set(exclude or [])] or list(ds.events)
    rng = random.Random(seed)
    return rng.choice(pool)
