"""Typed data and API contracts shared across the application."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["transport", "ecology", "social", "safety", "services"]


class District(BaseModel):
    name: str
    population_share: float = Field(gt=0, le=1)
    profile: str
    indicators: dict[str, float]


class Measure(BaseModel):
    id: str
    category: Category
    name: str
    type: Literal["district", "city"]
    cost: float = Field(ge=0)
    lag: int = Field(ge=0)
    effects: dict[str, float]


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    measure_id: str
    district: str | None = None


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[Decision] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    code: str
    message: str


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)


class BudgetResult(BaseModel):
    total: float
    spent: float
    remaining: float


class ScoreResult(BaseModel):
    before: float
    after: float
    delta: float


class DistrictResult(BaseModel):
    score_before: float
    score_after: float
    indicators_before: dict[str, float]
    indicators_after: dict[str, float]
    indicator_deltas: dict[str, float]
    population_share: float
    profile: str


class CriticalIndicator(BaseModel):
    district: str
    indicator: str
    value: float


class ActivatedSynergy(BaseModel):
    measure_ids: list[str]
    district: str
    effects: dict[str, float]


class MeasureContribution(BaseModel):
    measure_id: str
    district: str | None
    contribution: float


class WeakestDistrict(BaseModel):
    name: str
    score: float


class WeakestDistrictChange(BaseModel):
    before: WeakestDistrict
    after: WeakestDistrict


class AverageScoreChange(BaseModel):
    before: float
    after: float


class CityIndicators(BaseModel):
    before: dict[str, float]
    after: dict[str, float]
    delta: dict[str, float]


class ScoreDecomposition(BaseModel):
    average: float
    weakest: float
    critical: float
    total: float


class SimulationResult(BaseModel):
    valid: Literal[True] = True
    decisions: list[Decision]
    budget: BudgetResult
    score: ScoreResult
    districts: dict[str, DistrictResult]
    critical_before: list[CriticalIndicator]
    critical_after: list[CriticalIndicator]
    activated_synergies: list[ActivatedSynergy]
    measure_contributions: list[MeasureContribution]
    city_indicators: CityIndicators
    category_deltas: dict[str, float]
    weakest_district: WeakestDistrictChange
    average_score: AverageScoreChange
    score_decomposition: ScoreDecomposition
