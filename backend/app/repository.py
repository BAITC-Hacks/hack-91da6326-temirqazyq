"""Load the replaceable city dataset independently of simulation logic."""

import json
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.models import District, Measure


@dataclass
class Repository:
    districts: list[District]
    measures: list[Measure]
    config: dict[str, Any]
    synergies: list[dict[str, Any]]
    incompatibilities: list[dict[str, Any]]
    district_by_name: dict[str, District] = field(init=False)
    measure_by_id: dict[str, Measure] = field(init=False)

    def __post_init__(self) -> None:
        self.district_by_name = {district.name: district for district in self.districts}
        self.measure_by_id = {measure.id: measure for measure in self.measures}
        if len(self.district_by_name) != len(self.districts):
            raise ValueError("Dataset contains duplicate district names")
        if len(self.measure_by_id) != len(self.measures):
            raise ValueError("Dataset contains duplicate measure IDs")
        if not math.isclose(sum(self.config["weights"].values()), 1.0, abs_tol=1e-9):
            raise ValueError("Indicator weights must sum to 1")
        if not math.isclose(sum(d.population_share for d in self.districts), 1.0, abs_tol=1e-9):
            raise ValueError("Population shares must sum to 1")
        indicators = set(self.config["weights"])
        for district in self.districts:
            if set(district.indicators) != indicators:
                raise ValueError(f"District {district.name} has inconsistent indicators")
        for measure in self.measures:
            if not set(measure.effects).issubset(indicators):
                raise ValueError(f"Measure {measure.id} has unknown indicators")
            if measure.lag > self.config["horizon"]:
                raise ValueError(f"Measure {measure.id} lag exceeds simulation horizon")


@lru_cache(maxsize=4)
def load_repository(data_dir: str | Path | None = None) -> Repository:
    directory = Path(data_dir or os.getenv("DATA_DIR") or Path(__file__).resolve().parents[2] / "data")

    def read(name: str) -> Any:
        return json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))

    return Repository(
        districts=[District.model_validate(row) for row in read("districts")],
        measures=[Measure.model_validate(row) for row in read("measures")],
        config=read("config"),
        synergies=read("synergies"),
        incompatibilities=read("incompatibilities"),
    )
