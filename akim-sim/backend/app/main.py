"""FastAPI-приложение «Аким на 5 часов».

Слои:
    engine/   — детерминированный движок (валидация, Score, оракул, события)
    ai/       — LLM-агенты поверх трассы движка (с fallback без ключа)
    db.py     — SQLite-лидерборд
    report.py — одностраничная презентация сценария

Все эндпоинты под /api. Если рядом лежит собранный фронтенд (frontend/dist),
он раздаётся с корня — так проект запускается одним процессом.
"""
from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, report
from .ai import agents, fallback, pipeline
from .ai.llm import get_llm
from .engine.data import load_dataset
from .engine.events import apply_event, custom_event_from_spec, pick_event, world_for_event
from .engine.models import Decision, ScoreResult, ValidationResult, WorldState
from .engine.optimizer import best_by_goal, best_swaps, oracle, percentile
from .engine.scorer import raw_score, score_scenario
from .engine.validator import validate

log = logging.getLogger("akim.api")

ds = load_dataset()


@asynccontextmanager
async def _lifespan(_: FastAPI):
    db.init()
    # прогреваем оракул для базового мира в фоне (~1-2 с)
    threading.Thread(target=oracle, kwargs={"world": world_for_event(None, ds), "ds": ds}, daemon=True).start()
    yield


app = FastAPI(title="Аким на 5 часов — AI-симулятор", version="1.0.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ----------------------------------------------------------------------------- schemas
class ScenarioIn(BaseModel):
    decisions: List[Decision] = Field(default_factory=list)
    event_id: Optional[str] = Field(None, description="ID события «Чёрный лебедь» (мир после события) или null")


class AnalyzeIn(ScenarioIn):
    agents: Optional[List[str]] = Field(None, description="Подмножество из analyst, critic, advisor")


class EventIn(ScenarioIn):
    trigger_event_id: Optional[str] = Field(None, description="Конкретное событие; если null — случайное")
    seed: Optional[int] = None
    exclude: List[str] = Field(default_factory=list)


class SubmitIn(ScenarioIn):
    team: str = Field(..., min_length=1, max_length=64)
    note: Optional[str] = None
    analysis: Optional[Dict[str, Any]] = None


class CompareIn(BaseModel):
    a: ScenarioIn
    b: ScenarioIn


class ScoreOut(BaseModel):
    validation: ValidationResult
    result: Optional[ScoreResult]
    world: WorldState


# ----------------------------------------------------------------------------- helpers
def _world(event_id: Optional[str]) -> WorldState:
    try:
        return world_for_event(event_id, ds)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


def _scored(decisions: List[Decision], event_id: Optional[str]) -> tuple[WorldState, ScoreResult]:
    world = _world(event_id)
    v = validate(decisions, world, ds)
    if not v.valid:
        raise HTTPException(422, {"message": "Невалидный набор решений", "issues": [i.model_dump() for i in v.issues]})
    return world, score_scenario(decisions, world, ds)


# ----------------------------------------------------------------------------- endpoints
@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "llm": get_llm().cfg.describe()}


@app.get("/api/meta")
def meta() -> Dict[str, Any]:
    return {
        "rules": {
            "budget": ds.budget, "decisions_required": ds.decisions_required, "max_per_direction": ds.max_per_direction,
            "horizon_quarters": ds.horizon, "critical_threshold": ds.critical_threshold,
            "formula": "Score = 0.7·D_avg + 0.3·min(D_d) − 1.0·N_crit;  I' = clip(I + Σ effect·(8−L)/8 + synergy, 0, 100)",
        },
        "directions": ds.directions,
        "indicators": [i.__dict__ for i in ds.indicators],
        "districts": [d.__dict__ for d in ds.districts],
        "measures": [m.__dict__ for m in ds.measures],
        "synergies": [s.__dict__ for s in ds.synergies],
        "incompatibilities": [i.__dict__ for i in ds.incompatibilities],
        "events": [{"id": e.id, "title": e.title} for e in ds.events],
        "base_score": score_scenario([], world_for_event(None, ds), ds).base_score,
        "llm": get_llm().cfg.describe(),
    }


@app.post("/api/validate", response_model=ValidationResult)
def api_validate(body: ScenarioIn) -> ValidationResult:
    return validate(body.decisions, _world(body.event_id), ds)


@app.post("/api/score", response_model=ScoreOut)
def api_score(body: ScenarioIn) -> ScoreOut:
    world = _world(body.event_id)
    v = validate(body.decisions, world, ds)
    result = score_scenario(body.decisions, world, ds) if v.valid else None
    return ScoreOut(validation=v, result=result, world=world)


GOALS = [
    ("score", "Максимум оценки", "Лучший возможный набор без оглядки на цену"),
    ("weakest", "Подтянуть слабейший район", "30% оценки — балл худшего района; этот набор поднимает именно его"),
    ("no_crit", "Закрыть провалы дёшево", "Ни одного показателя ниже 40 при минимальной цене"),
    ("cheap", "Лучшее за скромные деньги", "Максимум оценки, если потратить не больше 70% бюджета"),
]


@app.post("/api/guide")
def api_guide(body: ScenarioIn) -> Dict[str, Any]:
    """Подсказчик планировщика: во что обойдётся каждый следующий шаг.

    Всё здесь считает движок, LLM не участвует. Смысл — убрать «тыкаю наугад»:
    для каждого доступного варианта заранее известно, на сколько он сдвинет оценку
    именно в текущем наборе (с учётом синергий и потолка шкалы).
    """
    world = _world(body.event_id)
    current = list(body.decisions)
    chosen = {d.measure_id for d in current}
    base = raw_score(current, world, ds)
    remaining = world.budget - sum(ds.measure_map[d.measure_id].cost for d in current)

    options: List[Dict[str, Any]] = []
    for m in ds.measures:
        if m.id in chosen or m.id in world.blocked_measures:
            continue
        targets: List[Optional[str]] = [d.id for d in ds.districts] if m.scope == "district" else [None]
        for dist in targets:
            cand = current + [Decision(measure_id=m.id, district_id=dist)]
            v = validate(cand, world, ds) if len(cand) == ds.decisions_required else None
            options.append({
                "measure_id": m.id,
                "district_id": dist,
                "delta": round(raw_score(cand, world, ds) - base, 2),
                "cost": m.cost,
                "affordable": m.cost <= remaining,
                "breaks_rules": None if v is None else (None if v.valid else "; ".join(i.message for i in v.issues)),
            })
    options.sort(key=lambda o: -o["delta"])

    # что просит каждый район: самые слабые показатели и лучший ход именно для него
    trace = score_scenario(current, world, ds) if current else None
    districts: List[Dict[str, Any]] = []
    for d in ds.districts:
        cur_ind = (
            {i.code: i.final for i in next(x for x in trace.districts if x.district_id == d.id).indicators}
            if trace else dict(world.baseline[d.id])
        )
        weak = sorted(cur_ind.items(), key=lambda kv: kv[1])[:3]
        best = max(
            (o for o in options if o["district_id"] == d.id and o["affordable"]),
            key=lambda o: o["delta"], default=None,
        )
        districts.append({
            "district_id": d.id,
            "name": d.name,
            "population_share": d.population_share,
            "score": round(sum(ds.weights[c] * v for c, v in cur_ind.items()), 2),
            "weakest": [
                {"code": c, "name": next(i.name for i in ds.indicators if i.code == c),
                 "value": round(v, 1), "critical": v < ds.critical_threshold}
                for c, v in weak
            ],
            "best_move": best,
        })
    districts.sort(key=lambda x: x["score"])

    bundles: List[Dict[str, Any]] = []
    for goal, title, why in GOALS:
        found = best_by_goal(goal, world, ds)
        if not found:
            continue
        _, decs = found
        r = score_scenario(decs, world, ds)
        bundles.append({
            "goal": goal, "title": title, "why": why,
            "decisions": [{"measure_id": x.measure_id, "district_id": x.district_id} for x in decs],
            "human": [
                f"{x.measure_id} «{ds.measure_map[x.measure_id].name}»"
                + (f" — {next(y.name for y in ds.districts if y.id == x.district_id)}" if x.district_id else " — весь город")
                for x in decs
            ],
            "score": r.score, "cost": r.total_cost, "d_min": round(r.d_min, 2), "n_crit": r.n_crit,
        })

    return {"base_score": round(base, 2), "remaining": remaining,
            "options": options, "districts": districts, "bundles": bundles}


@app.post("/api/analyze")
def api_analyze(body: AnalyzeIn) -> Dict[str, Any]:
    world, result = _scored(body.decisions, body.event_id)
    return pipeline.analyze(body.decisions, result, world, ds, include=body.agents)


@app.post("/api/council")
def api_council(body: ScenarioIn) -> Dict[str, Any]:
    world, result = _scored(body.decisions, body.event_id)
    return pipeline.council(body.decisions, result, world, ds)


@app.get("/api/oracle")
def api_oracle(event_id: Optional[str] = None, top: int = Query(10, le=25)) -> Dict[str, Any]:
    world = _world(event_id)
    res = oracle(world, ds)
    return {
        "event_id": event_id,
        "n_valid": res.n_valid,
        "best_score": round(res.best_score, 2),
        "best": [d.model_dump() for d in res.best],
        "top": [{"score": round(s, 2), "cost": c, "decisions": [d.model_dump() for d in decs]} for s, c, decs in res.top[:top]],
        "pareto": [{"cost": c, "score": round(s, 2), "decisions": [d.model_dump() for d in decs]} for c, s, decs in res.pareto],
        "histogram": _histogram(res.scores_sorted),
    }


def _histogram(scores, bins: int = 24) -> List[Dict[str, float]]:
    import numpy as np

    counts, edges = np.histogram(scores, bins=bins)
    return [{"from": round(float(edges[i]), 2), "to": round(float(edges[i + 1]), 2), "count": int(counts[i])} for i in range(len(counts))]


@app.post("/api/oracle/position")
def api_oracle_position(body: ScenarioIn) -> Dict[str, Any]:
    world, result = _scored(body.decisions, body.event_id)
    res = oracle(world, ds)
    return {
        "score": result.score, "best_score": round(res.best_score, 2), "gap": round(res.best_score - result.score, 2),
        "percentile": round(percentile(result.score, res), 1), "n_valid": res.n_valid,
        "best": [d.model_dump() for d in res.best],
        "swaps": [{"replace": s["replace"].model_dump(), "with": s["with"].model_dump(), "score": s["score"], "gain": s["gain"], "cost": s["cost"]} for s in best_swaps(body.decisions, world, ds, limit=5)],
    }


@app.get("/api/events")
def api_events() -> List[Dict[str, Any]]:
    return [{"id": e.id, "title": e.title, "narrative": e.narrative, "shocks": [s.__dict__ for s in e.shocks], "blocked_measures": e.blocked_measures, "budget_delta": e.budget_delta} for e in ds.events]


@app.post("/api/event/trigger")
def api_event_trigger(body: EventIn) -> Dict[str, Any]:
    """Применяет событие к миру и показывает, как «просел» текущий план команды."""
    base_world = _world(body.event_id)
    v0 = validate(body.decisions, base_world, ds)
    before = score_scenario(body.decisions, base_world, ds) if v0.valid else None
    ev = ds.event_map.get(body.trigger_event_id) if body.trigger_event_id else pick_event(body.seed, body.exclude, ds)
    if ev is None:
        raise HTTPException(404, "Неизвестное событие")
    world = world_for_event(ev.id, ds)
    v1 = validate(body.decisions, world, ds)
    # для нарратива считаем «как если бы план остался» даже если он стал невалиден (блокировка/бюджет)
    after = score_scenario([d for d in body.decisions if d.measure_id not in world.blocked_measures], world, ds)
    narration = pipeline.narrate_event(body.decisions, after, world, before.score if before else after.base_score, ds)
    return {
        "event": {"id": ev.id, "title": ev.title, "narrative": ev.narrative, "shocks": [s.__dict__ for s in ev.shocks], "blocked_measures": ev.blocked_measures, "budget_delta": ev.budget_delta},
        "world": world,
        "score_before": before.score if before else None,
        "score_after_if_unchanged": after.score,
        "base_score_after": after.base_score,
        "plan_still_valid": v1.valid,
        "validation": v1,
        "narration": narration,
    }


class CustomEventIn(ScenarioIn):
    text: str = Field(..., min_length=10, max_length=1200, description="Проблема своими словами")


@app.post("/api/event/custom")
def api_event_custom(body: CustomEventIn) -> Dict[str, Any]:
    """«Свой чёрный лебедь»: произвольный текст → событие → пересчёт → что делать дальше.

    Разделение ответственности то же, что и везде: модель только ИНТЕРПРЕТИРУЕТ текст в
    параметры (какие показатели, каких районов, насколько), а все последствия считает движок.
    Результат модели проходит через custom_event_from_spec, который выбрасывает всё
    неопознанное и зажимает величины.
    """
    llm = get_llm()
    if llm.available():
        try:
            spec = agents.run_event_designer(llm, body.text)
            mode = "llm"
        except Exception as exc:  # noqa: BLE001 — падение модели не должно ронять функцию
            log.warning("Конструктор события упал (%s) — ключевые слова", exc)
            spec, mode = fallback.event_designer(body.text), "fallback"
    else:
        spec, mode = fallback.event_designer(body.text), "fallback"

    ev = custom_event_from_spec(spec, ds)
    if not ev.shocks and not ev.blocked_measures and ev.budget_delta == 0:
        raise HTTPException(422, "Из описания не удалось извлечь влияние на город. Опишите, что именно ухудшилось и где.")

    base_world = _world(body.event_id)
    v0 = validate(body.decisions, base_world, ds)
    before = score_scenario(body.decisions, base_world, ds) if v0.valid else None

    world = apply_event(ev, base_world, ds)
    v1 = validate(body.decisions, world, ds)
    after = score_scenario([d for d in body.decisions if d.measure_id not in world.blocked_measures], world, ds)

    narration = pipeline.narrate_event(body.decisions, after, world, before.score if before else after.base_score, ds, event=ev)
    advice = pipeline.analyze(body.decisions, after, world, ds, include=["advisor"]) if v1.valid else None

    # Если план развалился — именно тогда помощь нужнее всего, а советнику не от чего плясать.
    # Даём детерминированный ответ движка: лучший возможный набор уже в НОВОМ мире.
    res = oracle(world, ds)
    rescue = {
        "best_score": round(res.best_score, 2),
        "best_set": [{"measure_id": d.measure_id, "district_id": d.district_id} for d in res.best],
        "best_set_human": [
            f"{d.measure_id} «{ds.measure_map[d.measure_id].name}»"
            + (f" — {next(x.name for x in ds.districts if x.id == d.district_id)}" if d.district_id else " — весь город")
            for d in res.best
        ],
        "n_valid": res.n_valid,
    }

    return {
        "event": {"id": ev.id, "title": ev.title, "narrative": ev.narrative,
                  "shocks": [s.__dict__ for s in ev.shocks], "blocked_measures": ev.blocked_measures,
                  "budget_delta": ev.budget_delta},
        "interpretation": str(spec.get("interpretation") or ""),
        "world": world,
        "score_before": before.score if before else None,
        "score_after_if_unchanged": after.score,
        "base_score_after": after.base_score,
        "plan_still_valid": v1.valid,
        "validation": v1,
        "narration": narration,
        "advisor": (advice or {}).get("advisor"),
        "rescue": rescue,
        "_mode": mode,
    }


@app.post("/api/leaderboard")
def api_submit(body: SubmitIn) -> Dict[str, Any]:
    _, result = _scored(body.decisions, body.event_id)
    entry_id = db.insert(body.team, body.event_id, [d.model_dump() for d in body.decisions], result.model_dump(), body.analysis, body.note)
    return db.get(entry_id)


@app.get("/api/leaderboard")
def api_leaderboard(event_id: Optional[str] = None, scope: str = Query("all", pattern="^(all|event)$")) -> List[Dict[str, Any]]:
    entries = db.list_entries(None if scope == "all" else event_id)
    for rank, e in enumerate(entries, 1):
        e["rank"] = rank
    return entries


@app.get("/api/leaderboard/{entry_id}")
def api_entry(entry_id: int) -> Dict[str, Any]:
    e = db.get(entry_id)
    if not e:
        raise HTTPException(404, "Сценарий не найден")
    return e


@app.delete("/api/leaderboard")
def api_clear() -> Dict[str, bool]:
    if os.environ.get("AKIM_ALLOW_RESET", "1") != "1":
        raise HTTPException(403, "Сброс отключён")
    db.clear()
    return {"ok": True}


@app.post("/api/compare")
def api_compare(body: CompareIn) -> Dict[str, Any]:
    wa, ra = _scored(body.a.decisions, body.a.event_id)
    wb, rb = _scored(body.b.decisions, body.b.event_id)
    per_district = [
        {"district_id": da.district_id, "name": da.name, "a": da.score_after, "b": db_.score_after, "diff": round(db_.score_after - da.score_after, 2)}
        for da, db_ in zip(ra.districts, rb.districts)
    ]
    per_indicator = []
    for da, db_ in zip(ra.districts, rb.districts):
        for ia, ib in zip(da.indicators, db_.indicators):
            if abs(ia.final - ib.final) > 1e-9:
                per_indicator.append({"district": da.name, "code": ia.code, "a": ia.final, "b": ib.final, "diff": round(ib.final - ia.final, 2)})
    sa = {(d.measure_id, d.district_id) for d in body.a.decisions}
    sb = {(d.measure_id, d.district_id) for d in body.b.decisions}
    return {
        "a": {"score": ra.score, "cost": ra.total_cost, "n_crit": ra.n_crit, "d_min": ra.d_min, "d_avg": ra.d_avg},
        "b": {"score": rb.score, "cost": rb.total_cost, "n_crit": rb.n_crit, "d_min": rb.d_min, "d_avg": rb.d_avg},
        "score_diff": round(rb.score - ra.score, 2),
        "only_a": [{"measure_id": m, "district_id": d} for m, d in sorted(sa - sb)],
        "only_b": [{"measure_id": m, "district_id": d} for m, d in sorted(sb - sa)],
        "per_district": per_district,
        "per_indicator": per_indicator,
        "directions": [{"name": x.name, "a": x.after, "b": y.after} for x, y in zip(ra.directions, rb.directions)],
    }


@app.get("/api/report/{entry_id}", response_class=HTMLResponse)
def api_report(entry_id: int) -> str:
    e = db.get(entry_id)
    if not e:
        raise HTTPException(404, "Сценарий не найден")
    decisions = [Decision(**d) for d in e["decisions"]]
    world, result = _scored(decisions, e["event_id"])
    analysis = e.get("analysis") or pipeline.analyze(decisions, result, world, ds, include=["analyst", "critic", "advisor"])
    ev_title = ds.event_map[e["event_id"]].title if e["event_id"] else None
    return report.render_report(e["team"], decisions, result, analysis, ev_title, ds)


class ReportIn(ScenarioIn):
    team: str = "Команда"
    analysis: Optional[Dict[str, Any]] = None


@app.post("/api/report", response_class=HTMLResponse)
def api_report_adhoc(body: ReportIn) -> str:
    world, result = _scored(body.decisions, body.event_id)
    analysis = body.analysis or pipeline.analyze(body.decisions, result, world, ds)
    ev_title = ds.event_map[body.event_id].title if body.event_id else None
    return report.render_report(body.team, body.decisions, result, analysis, ev_title, ds)


# ----------------------------------------------------------------------------- static frontend
_dist = Path(os.environ.get("AKIM_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
