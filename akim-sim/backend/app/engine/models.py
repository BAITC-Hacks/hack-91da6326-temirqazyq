"""Pydantic-модели, общие для движка и API."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Decision(BaseModel):
    measure_id: str = Field(..., examples=["M7"])
    district_id: Optional[str] = Field(None, examples=["nura"])


class WorldState(BaseModel):
    """Состояние мира, в котором оценивается сценарий.

    По умолчанию — исходный датасет. После события «Чёрный лебедь» здесь появляются
    сдвинутые показатели, заблокированные меры и другой бюджет.
    """

    event_id: Optional[str] = None
    budget: int
    blocked_measures: List[str] = []
    baseline: Dict[str, Dict[str, float]]


class ValidationIssue(BaseModel):
    rule: str
    message: str


class ValidationResult(BaseModel):
    valid: bool
    issues: List[ValidationIssue]
    total_cost: int
    budget: int
    remaining: int
    per_direction: Dict[str, int]


class IndicatorContribution(BaseModel):
    measure_id: str
    district_id: Optional[str]
    raw: float
    realized: float
    kind: str  # "effect" | "synergy"


class IndicatorTrace(BaseModel):
    code: str
    base: float
    final: float
    delta: float
    critical_before: bool
    critical_after: bool
    contributions: List[IndicatorContribution]


class DistrictTrace(BaseModel):
    district_id: str
    name: str
    population_share: float
    score_before: float
    score_after: float
    indicators: List[IndicatorTrace]


class MeasureContribution(BaseModel):
    measure_id: str
    district_id: Optional[str]
    name: str
    cost: int
    lag: int
    realized_share: float
    marginal_score: float  # score(all) - score(all without this measure)
    solo_score: float  # score(base + this measure) - score(base)


class SynergyHit(BaseModel):
    first: str
    second: str
    district_id: str
    indicator: str
    bonus: float
    note: str


class DirectionSummary(BaseModel):
    direction: str
    name: str
    before: float
    after: float


class ScoreResult(BaseModel):
    score: float
    base_score: float
    delta: float
    d_avg: float
    d_min: float
    d_min_district: str
    n_crit: int
    critical_cells: List[str]
    base_d_avg: float
    base_d_min: float
    base_n_crit: int
    total_cost: int
    budget: int
    remaining: int
    districts: List[DistrictTrace]
    measures: List[MeasureContribution]
    synergies: List[SynergyHit]
    directions: List[DirectionSummary]
