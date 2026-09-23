"""Загрузка синтетического датасета (районы, показатели, мероприятия, события).

Единственный источник правды — JSON-файлы в каталоге ``data/`` в корне репозитория.
Модуль не содержит игровой логики, только структуры данных и доступ к ним.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

DATA_DIR = Path(os.environ.get("AKIM_DATA_DIR", Path(__file__).resolve().parents[3] / "data"))


@dataclass(frozen=True)
class Indicator:
    code: str
    direction: str
    name: str
    weight: float
    meaning: str


@dataclass(frozen=True)
class District:
    id: str
    name: str
    population_share: float
    profile: str
    indicators: Dict[str, float]


@dataclass(frozen=True)
class Measure:
    id: str
    direction: str
    name: str
    scope: str  # "district" | "city"
    cost: int
    lag: int
    effects: Dict[str, float]

    @property
    def is_district(self) -> bool:
        return self.scope == "district"


@dataclass(frozen=True)
class Synergy:
    first: str
    second: str
    indicator: str
    bonus: float
    note: str


@dataclass(frozen=True)
class Incompatibility:
    a: str
    b: str
    scope: str  # "any" | "same_district"
    reason: str


@dataclass(frozen=True)
class Shock:
    district: str
    indicator: str
    delta: float


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    narrative: str
    shocks: List[Shock]
    blocked_measures: List[str]
    budget_delta: int


@dataclass
class Dataset:
    horizon: int
    budget: int
    decisions_required: int
    max_per_direction: int
    critical_threshold: float
    indicators: List[Indicator]
    directions: Dict[str, str]
    districts: List[District]
    measures: List[Measure]
    synergies: List[Synergy]
    incompatibilities: List[Incompatibility]
    events: List[Event] = field(default_factory=list)

    # --- удобные индексы -------------------------------------------------
    @property
    def indicator_codes(self) -> List[str]:
        return [i.code for i in self.indicators]

    @property
    def weights(self) -> Dict[str, float]:
        return {i.code: i.weight for i in self.indicators}

    @property
    def district_map(self) -> Dict[str, District]:
        return {d.id: d for d in self.districts}

    @property
    def measure_map(self) -> Dict[str, Measure]:
        return {m.id: m for m in self.measures}

    @property
    def event_map(self) -> Dict[str, Event]:
        return {e.id: e for e in self.events}

    def baseline(self) -> Dict[str, Dict[str, float]]:
        """Копия исходных показателей: {district_id: {code: value}}."""
        return {d.id: dict(d.indicators) for d in self.districts}


def _read(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def load_dataset() -> Dataset:
    d = _read("districts.json")
    m = _read("measures.json")
    e = _read("events.json") if (DATA_DIR / "events.json").exists() else {"events": []}
    return Dataset(
        horizon=d["horizon_quarters"],
        budget=d["budget"],
        decisions_required=d["decisions_required"],
        max_per_direction=d["max_per_direction"],
        critical_threshold=d["critical_threshold"],
        indicators=[Indicator(**i) for i in d["indicators"]],
        directions=d["directions"],
        districts=[District(**x) for x in d["districts"]],
        measures=[Measure(**x) for x in m["measures"]],
        synergies=[Synergy(**x) for x in m["synergies"]],
        incompatibilities=[Incompatibility(**x) for x in m["incompatibilities"]],
        events=[
            Event(
                id=x["id"],
                title=x["title"],
                narrative=x["narrative"],
                shocks=[Shock(**s) for s in x["shocks"]],
                blocked_measures=list(x.get("blocked_measures", [])),
                budget_delta=int(x.get("budget_delta", 0)),
            )
            for x in e["events"]
        ],
    )
