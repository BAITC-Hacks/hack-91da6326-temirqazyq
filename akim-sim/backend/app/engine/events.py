"""События «Чёрный лебедь»: шоки к исходным показателям, блокировки мер, секвестр бюджета.

Событие порождает новое ``WorldState``; сценарий команды пересчитывается в нём же,
чтобы было видно, как «просел» план, и можно было перераспределить бюджет.
"""
from __future__ import annotations

import random
from typing import List, Optional

from .data import Dataset, Event, load_dataset
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
