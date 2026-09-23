"""Session-scoped persistence and explicit, budgeted AI operations."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.ai.agent import AgentManager, RunRequest
from app.ai.constraints import validate_candidate_constraints, validate_constraints
from app.ai.contracts import Constraints
from app.ai.presentation import public_history, public_run
from app.ai.tools import dataset_version
from app.models import Decision
from app.simulation.engine import simulate

router = APIRouter(prefix="/api", tags=["Workspace"])


def manager(request: Request) -> AgentManager:
    return request.app.state.agent


def session_id(request: Request, x_session_id: str | None = Header(default=None)) -> str:
    if not x_session_id or len(x_session_id) != 32 or not request.app.state.agent.store.get_session(x_session_id):
        raise HTTPException(status_code=401, detail="Откройте сессию приложения. Сценарии других сессий недоступны.")
    return x_session_id


class SaveScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Мой сценарий", max_length=120)
    decisions: list[Decision] = Field(max_length=5)
    provenance: Literal["manual", "algorithmic"] = "manual"
    constraints: Constraints | None = None
    saved: bool = True


class SaveName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=120)


class CompareIds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_ids: list[str] = Field(min_length=2, max_length=3)


def verified_row(mgr: AgentManager, sid: str, identifier: str) -> dict[str, Any]:
    row = mgr.store.get_scenario(sid, identifier)
    if row is None:
        raise HTTPException(status_code=404, detail="Сценарий не найден в текущей сессии.")
    if row["dataset_version"] != dataset_version():
        raise HTTPException(status_code=409, detail="Версия модели изменилась. Пересчитайте решения перед сравнением.")
    # Persisted metrics are not trusted across migrations or manual database edits.
    result = simulate(row["decisions"])
    if not result["valid"]:
        raise HTTPException(status_code=409, detail="Сохранённые решения больше не соответствуют правилам модели.")
    return {**row, "result": result}


@router.post("/sessions")
def create_session(request: Request) -> dict[str, str]:
    return {"session_id": manager(request).store.create_session()}


@router.get("/sessions/current")
def current_session(request: Request, sid: str = Depends(session_id)) -> dict[str, Any]:
    mgr = manager(request)
    session = mgr.store.get_session(sid)
    runs = mgr.store.list_runs(sid, limit=100)
    return {**session, "constraints": Constraints.model_validate(session["constraints"]).model_dump(),
            "history": public_history(session["history"], runs), "runs": [public_run(run) for run in runs[:10]]}


@router.get("/ai/config")
def ai_config(request: Request) -> dict[str, Any]:
    settings = manager(request).settings
    safe = settings.public()
    return {**safe, "enabled": settings.ai_enabled, "provider": settings.ai_provider,
            "model": settings.openai_model, "allow_template_fallback": settings.ai_allow_template_fallback,
            "limits": {key: value for key, value in safe.items() if key.startswith("ai_max_") or key.endswith("_limit_usd") or key == "ai_run_timeout_seconds"}}


@router.post("/ai/runs", status_code=202)
async def start_run(body: RunRequest, request: Request, sid: str = Depends(session_id)) -> dict[str, Any]:
    return public_run(manager(request).start(sid, body))


@router.get("/ai/runs/{run_id}")
def get_run(run_id: str, request: Request, sid: str = Depends(session_id)) -> dict[str, Any]:
    run = manager(request).store.get_run(sid, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Операция не найдена в текущей сессии.")
    return public_run(run)


@router.post("/ai/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request, sid: str = Depends(session_id)) -> dict[str, Any]:
    run = await manager(request).cancel(sid, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Операция не найдена в текущей сессии.")
    return public_run(run)


@router.get("/ai/usage")
def usage(request: Request, sid: str = Depends(session_id)) -> dict[str, Any]:
    return manager(request).provider.ledger.summary()


@router.post("/scenarios")
def save_scenario(body: SaveScenario, request: Request, sid: str = Depends(session_id)) -> Any:
    result = simulate(body.decisions)
    if not result["valid"]:
        return JSONResponse(status_code=422, content=result)
    constraints = body.constraints or Constraints()
    validation = validate_constraints(constraints)
    errors = validation["errors"] + validate_candidate_constraints(body.decisions, constraints)
    if errors:
        return JSONResponse(status_code=422, content={"valid": False, "errors": errors})
    return manager(request).store.save_scenario(sid, decisions=result["decisions"], result=result,
        provenance=body.provenance, constraints=constraints.model_dump(), dataset_version=dataset_version(), name=body.name, saved=body.saved)


@router.get("/scenarios")
def list_scenarios(request: Request, saved_only: bool = False, sid: str = Depends(session_id)) -> list[dict[str, Any]]:
    return manager(request).store.list_scenarios(sid, saved_only=saved_only)


@router.post("/scenarios/compare")
def compare_scenarios(body: CompareIds, request: Request, sid: str = Depends(session_id)) -> dict[str, Any]:
    ids = list(dict.fromkeys(body.scenario_ids))
    if len(ids) < 2:
        raise HTTPException(status_code=422, detail="Выберите разные сценарии.")
    rows = [verified_row(manager(request), sid, identifier) for identifier in ids]
    categories = rows[0]["result"]["category_deltas"]
    return {"scenarios": rows, "category_comparison": [
        {"category": category, **{f"scenario_{chr(97 + index)}": row["result"]["category_deltas"][category] for index, row in enumerate(rows)}}
        for category in categories
    ]}


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, request: Request, sid: str = Depends(session_id)) -> dict[str, Any]:
    return verified_row(manager(request), sid, scenario_id)


@router.post("/scenarios/{scenario_id}/save")
def mark_saved(scenario_id: str, body: SaveName, request: Request, sid: str = Depends(session_id)) -> dict[str, Any]:
    verified_row(manager(request), sid, scenario_id)
    return manager(request).store.mark_saved(sid, scenario_id, name=body.name)


@router.get("/scenarios/{scenario_id}/export")
def export_scenario(scenario_id: str, request: Request, sid: str = Depends(session_id)) -> JSONResponse:
    row = verified_row(manager(request), sid, scenario_id)
    return JSONResponse(content=row, headers={"Content-Disposition": f'attachment; filename="akim-{scenario_id}.json"'})
