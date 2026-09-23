"""Сборка компактного контекста для LLM из трассы расчёта.

Принцип: модель получает только посчитанные движком числа и объясняет их.
Ничего не считает и не придумывает — все цифры уже здесь.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..engine.data import Dataset, load_dataset
from ..engine.models import Decision, ScoreResult, WorldState
from ..engine.optimizer import best_swaps, oracle, percentile


def decisions_human(decisions: List[Decision], ds: Dataset) -> List[str]:
    out = []
    for d in decisions:
        m = ds.measure_map[d.measure_id]
        where = ds.district_map[d.district_id].name if d.district_id else "весь город"
        out.append(f"{m.id} «{m.name}» — {where} (стоимость {m.cost}, лаг {m.lag} кв.)")
    return out


def build_context(decisions: List[Decision], result: ScoreResult, world: WorldState, ds: Optional[Dataset] = None, with_oracle: bool = True) -> Dict[str, Any]:
    ds = ds or load_dataset()
    ctx: Dict[str, Any] = {
        "event": None,
        "budget": world.budget,
        "total_cost": result.total_cost,
        "remaining": result.remaining,
        "decisions": decisions_human(decisions, ds),
        "decisions_raw": [d.model_dump() for d in decisions],
        "score": {"base": result.base_score, "final": result.score, "delta": result.delta,
                  "d_avg": result.d_avg, "d_min": result.d_min, "d_min_district": ds.district_map[result.d_min_district].name,
                  "n_crit_before": result.base_n_crit, "n_crit_after": result.n_crit,
                  "critical_cells_after": [f"{ds.district_map[c.split(':')[0]].name}:{c.split(':')[1]}" for c in result.critical_cells]},
        "districts": [
            {
                "name": d.name, "population_share": d.population_share, "profile": ds.district_map[d.district_id].profile,
                "score_before": d.score_before, "score_after": d.score_after,
                "changed_indicators": {i.code: {"before": i.base, "after": i.final, "delta": i.delta} for i in d.indicators if abs(i.delta) > 1e-9},
                "weak_indicators_after": {i.code: i.final for i in d.indicators if i.final < 50},
            }
            for d in result.districts
        ],
        "measures": [
            {"id": m.measure_id, "name": m.name, "district": ds.district_map[m.district_id].name if m.district_id else "город",
             "cost": m.cost, "lag": m.lag, "realized_share": m.realized_share,
             "marginal_score": m.marginal_score, "solo_score": m.solo_score,
             "score_per_cost": round(m.marginal_score / m.cost, 3)}
            for m in result.measures
        ],
        "synergies": [s.note for s in result.synergies],
        "directions": [{"name": d.name, "before": d.before, "after": d.after} for d in result.directions],
        "indicator_legend": {i.code: i.name for i in ds.indicators},
        "untouched_districts": [d.name for d in result.districts if all(abs(i.delta) < 1e-9 for i in d.indicators)],
    }
    if world.event_id:
        ev = ds.event_map[world.event_id]
        ctx["event"] = {"id": ev.id, "title": ev.title, "narrative": ev.narrative, "blocked": ev.blocked_measures, "budget_delta": ev.budget_delta}
    if with_oracle:
        res = oracle(world, ds)
        ctx["oracle"] = {
            "best_score": round(res.best_score, 2),
            "gap_to_best": round(res.best_score - result.score, 2),
            "percentile": round(percentile(result.score, res), 1),
            "n_valid_sets": res.n_valid,
            "best_set": decisions_human(res.best, ds),
            "best_swaps": [
                {"replace": decisions_human([s["replace"]], ds)[0], "with": decisions_human([s["with"]], ds)[0],
                 "replace_raw": s["replace"].model_dump(), "with_raw": s["with"].model_dump(),
                 "new_score": s["score"], "gain": s["gain"], "cost": s["cost"]}
                for s in best_swaps(decisions, world, ds, limit=5)
            ],
        }
    return ctx


def context_json(ctx: Dict[str, Any]) -> str:
    return json.dumps(ctx, ensure_ascii=False, indent=1)
