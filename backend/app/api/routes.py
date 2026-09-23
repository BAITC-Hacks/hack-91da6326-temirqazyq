from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.ai.advisor import explain
from app.ai.schemas import Explanation
from app.models import District, Measure, ScenarioRequest, SimulationResult, ValidationResult
from app.optimizer.search import SearchRequest, search
from app.repository import load_repository
from app.simulation.engine import simulate
from app.simulation.validator import validate

router = APIRouter(prefix="/api")


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_a: ScenarioRequest
    scenario_b: ScenarioRequest


class CategoryComparison(BaseModel):
    category: str
    scenario_a: float
    scenario_b: float


class CompareResult(BaseModel):
    scenario_a: SimulationResult
    scenario_b: SimulationResult
    category_comparison: list[CategoryComparison]
    explanation: Explanation


def checked_result(request: ScenarioRequest, *, preview: bool = False) -> dict[str, Any] | JSONResponse:
    result = simulate(request.decisions, preview=preview)
    return result if result["valid"] else JSONResponse(status_code=422, content=result)


@router.get("/districts", response_model=list[District], tags=["Dataset"])
def districts() -> list[District]:
    return load_repository().districts


@router.get("/measures", response_model=list[Measure], tags=["Dataset"])
def measures() -> list[Measure]:
    return load_repository().measures


@router.get("/base-state", response_model=SimulationResult, tags=["Simulation"])
def base_state() -> dict[str, Any]:
    return simulate([], preview=True)


@router.post("/scenario/validate", response_model=ValidationResult, tags=["Simulation"])
def validate_scenario(request: ScenarioRequest) -> dict[str, Any]:
    return validate(request.decisions)


@router.post("/scenario/preview", response_model=SimulationResult, tags=["Simulation"])
def preview_scenario(request: ScenarioRequest) -> Any:
    return checked_result(request, preview=True)


@router.post("/scenario/simulate", response_model=SimulationResult, tags=["Simulation"])
def simulate_scenario(request: ScenarioRequest) -> Any:
    return checked_result(request)


@router.post("/scenario/compare", response_model=CompareResult, tags=["Simulation"])
def compare_scenarios(request: CompareRequest) -> Any:
    a = checked_result(request.scenario_a)
    if isinstance(a, JSONResponse):
        return a
    b = checked_result(request.scenario_b)
    if isinstance(b, JSONResponse):
        return b
    return {
        "scenario_a": a,
        "scenario_b": b,
        "category_comparison": [
            {"category": category, "scenario_a": a["category_deltas"][category], "scenario_b": b["category_deltas"][category]}
            for category in a["category_deltas"]
        ],
        "explanation": explain(a, b),
    }


@router.post("/optimizer/search", tags=["Scenario Lab"])
def search_scenarios(request: SearchRequest) -> dict[str, Any]:
    return search(request)


@router.post("/ai/explain", response_model=Explanation, tags=["AI Advisor"])
def explain_scenario(request: SimulationResult) -> Any:
    # Ignore client-supplied metrics: only server-computed facts reach the advisor.
    result = checked_result(ScenarioRequest(decisions=request.decisions), preview=True)
    if isinstance(result, JSONResponse):
        return result
    return explain(result)

