"""Расчёт Astana Quality of Life Score с полной трассой.

Формула (раздел 3 датасета):
    I'_dk  = clip(I_dk + Σ effect_m,k × (H − L_m)/H + synergies, 0, 100)
    D_d    = Σ w_k × I'_dk
    D_avg  = Σ pop_d × D_d
    Score  = 0.7 × D_avg + 0.3 × min(D_d) − 1.0 × N_crit
где N_crit — число пар «район × показатель» со значением строго меньше порога (40).

Функция ``raw_score`` — быстрый расчёт без трассы (для оптимизатора и вкладов),
``score_scenario`` — полная трасса для UI и LLM.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .data import Dataset, load_dataset
from .models import (
    Decision,
    DirectionSummary,
    DistrictTrace,
    IndicatorContribution,
    IndicatorTrace,
    MeasureContribution,
    ScoreResult,
    SynergyHit,
    WorldState,
)
from .validator import default_world

W_AVG = 0.7
W_MIN = 0.3
W_CRIT = 1.0


def realized_share(lag: int, horizon: int) -> float:
    return (horizon - lag) / horizon


def _apply(decisions: List[Decision], world: WorldState, ds: Dataset, with_trace: bool):
    """Возвращает (indicators_after, contributions, synergy_hits)."""
    ind: Dict[str, Dict[str, float]] = {d: dict(v) for d, v in world.baseline.items()}
    contrib: Dict[Tuple[str, str], List[IndicatorContribution]] = {}
    mm = ds.measure_map
    chosen: Dict[str, Optional[str]] = {}

    for dec in decisions:
        m = mm[dec.measure_id]
        chosen[m.id] = dec.district_id
        share = realized_share(m.lag, ds.horizon)
        targets = [dec.district_id] if m.is_district else list(ind.keys())
        for d in targets:
            for code, raw in m.effects.items():
                val = raw * share
                ind[d][code] += val
                if with_trace:
                    contrib.setdefault((d, code), []).append(
                        IndicatorContribution(measure_id=m.id, district_id=dec.district_id, raw=raw, realized=round(val, 4), kind="effect")
                    )

    hits: List[SynergyHit] = []
    for s in ds.synergies:
        if s.first in chosen and s.second in chosen:
            # бонус в районе первой меры пары; если первая — городская, берём район второй
            d = chosen[s.first] or chosen[s.second]
            if d is None:
                continue
            ind[d][s.indicator] += s.bonus
            hits.append(SynergyHit(first=s.first, second=s.second, district_id=d, indicator=s.indicator, bonus=s.bonus, note=s.note))
            if with_trace:
                contrib.setdefault((d, s.indicator), []).append(
                    IndicatorContribution(measure_id=f"{s.first}+{s.second}", district_id=d, raw=s.bonus, realized=s.bonus, kind="synergy")
                )

    for d in ind:
        for k in ind[d]:
            ind[d][k] = min(100.0, max(0.0, ind[d][k]))
    return ind, contrib, hits


def _aggregate(ind: Dict[str, Dict[str, float]], ds: Dataset):
    w = ds.weights
    dscore = {d: sum(w[k] * v for k, v in vals.items()) for d, vals in ind.items()}
    pop = {d.id: d.population_share for d in ds.districts}
    d_avg = sum(pop[d] * s for d, s in dscore.items())
    d_min_id = min(dscore, key=dscore.get)
    crit = [f"{d}:{k}" for d, vals in ind.items() for k, v in vals.items() if v < ds.critical_threshold]
    score = W_AVG * d_avg + W_MIN * dscore[d_min_id] - W_CRIT * len(crit)
    return score, dscore, d_avg, d_min_id, crit


def raw_score(decisions: List[Decision], world: Optional[WorldState] = None, ds: Optional[Dataset] = None) -> float:
    ds = ds or load_dataset()
    world = world or default_world(ds)
    ind, _, _ = _apply(decisions, world, ds, with_trace=False)
    return _aggregate(ind, ds)[0]


def score_scenario(decisions: List[Decision], world: Optional[WorldState] = None, ds: Optional[Dataset] = None) -> ScoreResult:
    ds = ds or load_dataset()
    world = world or default_world(ds)
    mm = ds.measure_map

    base_ind = {d: dict(v) for d, v in world.baseline.items()}
    base_score, base_dscore, base_avg, base_min_id, base_crit = _aggregate(base_ind, ds)

    ind, contrib, hits = _apply(decisions, world, ds, with_trace=True)
    score, dscore, d_avg, d_min_id, crit = _aggregate(ind, ds)

    districts: List[DistrictTrace] = []
    for dist in ds.districts:
        rows = []
        for code in ds.indicator_codes:
            b, f = base_ind[dist.id][code], ind[dist.id][code]
            rows.append(
                IndicatorTrace(
                    code=code,
                    base=round(b, 3),
                    final=round(f, 3),
                    delta=round(f - b, 3),
                    critical_before=b < ds.critical_threshold,
                    critical_after=f < ds.critical_threshold,
                    contributions=contrib.get((dist.id, code), []),
                )
            )
        districts.append(
            DistrictTrace(
                district_id=dist.id,
                name=dist.name,
                population_share=dist.population_share,
                score_before=round(base_dscore[dist.id], 3),
                score_after=round(dscore[dist.id], 3),
                indicators=rows,
            )
        )

    measures: List[MeasureContribution] = []
    for dec in decisions:
        m = mm[dec.measure_id]
        without = [x for x in decisions if x is not dec]
        marginal = score - raw_score(without, world, ds)
        solo = raw_score([dec], world, ds) - base_score
        measures.append(
            MeasureContribution(
                measure_id=m.id,
                district_id=dec.district_id,
                name=m.name,
                cost=m.cost,
                lag=m.lag,
                realized_share=realized_share(m.lag, ds.horizon),
                marginal_score=round(marginal, 3),
                solo_score=round(solo, 3),
            )
        )

    pop = {d.id: d.population_share for d in ds.districts}
    dirs: List[DirectionSummary] = []
    for key, name in ds.directions.items():
        codes = [i.code for i in ds.indicators if i.direction == key]
        before = sum(pop[d] * sum(base_ind[d][c] for c in codes) / len(codes) for d in base_ind)
        after = sum(pop[d] * sum(ind[d][c] for c in codes) / len(codes) for d in ind)
        dirs.append(DirectionSummary(direction=key, name=name, before=round(before, 2), after=round(after, 2)))

    total = sum(mm[d.measure_id].cost for d in decisions)
    return ScoreResult(
        score=round(score, 2),
        base_score=round(base_score, 2),
        delta=round(score - base_score, 2),
        d_avg=round(d_avg, 3),
        d_min=round(dscore[d_min_id], 3),
        d_min_district=d_min_id,
        n_crit=len(crit),
        critical_cells=crit,
        base_d_avg=round(base_avg, 3),
        base_d_min=round(base_dscore[base_min_id], 3),
        base_n_crit=len(base_crit),
        total_cost=total,
        budget=world.budget,
        remaining=world.budget - total,
        districts=districts,
        measures=measures,
        synergies=hits,
        directions=dirs,
    )
