from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.ai.advisor import explain
from app.ai.schemas import Explanation
from app.ai.agent import RunRequest
from app.ai.tools import dataset_version
from app.ai.contracts import Constraints
from app.ai.presentation import public_run
from app.api.workspace import manager, session_id
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
    explanation: Explanation | None = None


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
def compare_scenarios(request: CompareRequest, http_request: Request) -> Any:
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
        "explanation": explain(a, b) if manager(http_request).settings.ai_allow_template_fallback else None,
    }


@router.post("/optimizer/search", tags=["Scenario Lab"])
def search_scenarios(request: SearchRequest) -> dict[str, Any]:
    return search(request)


@router.post("/ai/explain", tags=["AI Advisor"], deprecated=True)
async def explain_scenario(request: SimulationResult, http_request: Request, sid: str = Depends(session_id)) -> Any:
    # Ignore client-supplied metrics: only server-computed facts reach the advisor.
    result = checked_result(ScenarioRequest(decisions=request.decisions))
    if isinstance(result, JSONResponse):
        return result
    mgr = manager(http_request)
    row = mgr.store.save_scenario(sid, decisions=result["decisions"], result=result,
        provenance="manual", constraints=Constraints().model_dump(), dataset_version=dataset_version())
    run = mgr.start(sid, RunRequest(operation="explain", scenario_ids=[row["scenario_id"]], request_id=uuid4().hex))
    task = mgr.tasks.get(run["run_id"])
    if task:
        await task
    run = public_run(mgr.store.get_run(sid, run["run_id"]))
    value = run.get("explanation")
    if not value:
        return JSONResponse(status_code=502, content={"valid": False, "errors": [run.get("error") or {"code": "NO_EXPLANATION", "message": run["message"]}], "metadata": run["metadata"]})
    return {"summary": value["summary"], "strengths": value["observations"], "risks": value["remaining_issues"],
            "tradeoffs": value["tradeoffs"], "recommendations": value["limitations"], "source": value["source"],
            "run_id": run["run_id"], "metadata": run["metadata"]}

