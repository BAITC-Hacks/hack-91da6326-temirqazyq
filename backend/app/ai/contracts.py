"""Application-owned contracts for normalized state and provider output."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Decision


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolDecision(StrictModel):
    measure_id: str
    district: str | None


class Constraints(StrictModel):
    max_budget: float = Field(default=100, ge=0, le=100, allow_inf_nan=False)
    reserve_budget: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    excluded_measure_ids: list[str] = Field(default_factory=list)
    locked_decisions: list[Decision] = Field(default_factory=list)
    focus_district: str | None = None
    preferred_categories: list[str] = Field(default_factory=list)
    allowed_districts: list[str] | None = None
    requested_scenario_count: int = Field(default=3, ge=1, le=3)
    analysis_indicators: list[str] = Field(default_factory=list)


class Intent(StrictModel):
    """A patch, not replacement state: null means unchanged; clear_fields resets."""

    operation: Literal["generate", "explain", "compare", "clarify"]
    max_budget: float | None = Field(ge=0, le=100, allow_inf_nan=False)
    reserve_budget: float | None = Field(ge=0, le=100, allow_inf_nan=False)
    excluded_measure_ids: list[str] | None
    locked_decisions: list[ToolDecision] | None
    focus_district: str | None
    preferred_categories: list[str] | None
    allowed_districts: list[str] | None
    requested_scenario_count: int | None = Field(ge=1, le=3)
    analysis_indicators: list[str] | None
    clear_fields: list[str]
    clarification: str | None
    unsupported_conditions: list[str]


class Narrative(StrictModel):
    summary: str
    observations: list[str]
    remaining_issues: list[str]
    tradeoffs: list[str]
    limitations: list[str]
    evidence_refs: list[str]
    scenario_ids: list[str]


class Candidate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    decisions: list[ToolDecision] = Field(max_length=20)


class EvaluateArguments(StrictModel):
    candidates: list[Candidate] = Field(min_length=1, max_length=3)


class CompareArguments(StrictModel):
    scenario_ids: list[str] = Field(min_length=2, max_length=3)


class EmptyArguments(StrictModel):
    pass
