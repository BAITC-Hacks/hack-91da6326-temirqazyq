"""«Оптимальный оракул»: полный перебор всех допустимых наборов решений.

Пространство небольшое (14 мер, 5 решений, 5 районов → ~700 тыс. допустимых
наборов), поэтому вместо эвристик считаем всё честно, векторизованно на numpy.
Результат кешируется по состоянию мира (событие + бюджет + блокировки).

Что даёт:
* глобальный максимум Score и топ-N наборов;
* Парето-фронт «стоимость → лучший Score»;
* перцентиль пользовательского сценария среди всех допустимых;
* локальные улучшения: одна замена (slot → другая мера/район) с наибольшим приростом.
"""
from __future__ import annotations

import itertools
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .data import Dataset, load_dataset
from .models import Decision, WorldState
from .scorer import W_AVG, W_CRIT, W_MIN, raw_score, realized_share
from .validator import default_world, validate


@dataclass
class OracleResult:
    n_valid: int
    best_score: float
    best: List[Decision]
    top: List[Tuple[float, int, List[Decision]]]  # (score, cost, decisions)
    pareto: List[Tuple[int, float, List[Decision]]]  # (cost, score, decisions)
    scores_sorted: np.ndarray  # для перцентилей


_cache: Dict[str, OracleResult] = {}
_lock = threading.Lock()


def world_key(world: WorldState) -> str:
    return f"{world.event_id}|{world.budget}|{','.join(sorted(world.blocked_measures))}"


def _enumerate(world: WorldState, ds: Dataset) -> OracleResult:
    codes = ds.indicator_codes
    K = len(codes)
    kidx = {c: i for i, c in enumerate(codes)}
    dists = [d.id for d in ds.districts]
    D = len(dists)
    didx = {d: i for i, d in enumerate(dists)}
    w = np.array([ds.weights[c] for c in codes])
    pop = np.array([d.population_share for d in ds.districts])
    base = np.array([[world.baseline[d][c] for c in codes] for d in dists])  # (D,K)

    measures = [m for m in ds.measures if m.id not in world.blocked_measures]
    # опции каждой меры: список (district_index | -1, delta-матрица (D,K))
    options: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for m in measures:
        share = realized_share(m.lag, ds.horizon)
        if m.is_district:
            idx = np.arange(D)
            deltas = np.zeros((D, D, K))
            for di in range(D):
                for c, v in m.effects.items():
                    deltas[di, di, kidx[c]] = v * share
        else:
            idx = np.array([-1])
            deltas = np.zeros((1, D, K))
            for c, v in m.effects.items():
                deltas[0, :, kidx[c]] = v * share
        options[m.id] = (idx, deltas)

    any_inc = {(i.a, i.b) for i in ds.incompatibilities if i.scope == "any"}
    same_inc = {(i.a, i.b) for i in ds.incompatibilities if i.scope == "same_district"}

    all_scores: List[np.ndarray] = []
    all_costs: List[int] = []
    all_choices: List[Tuple[Tuple[str, ...], np.ndarray]] = []  # (measure ids, district idx matrix (P,5))

    for combo in itertools.combinations(measures, ds.decisions_required):
        ids = tuple(m.id for m in combo)
        cost = sum(m.cost for m in combo)
        if cost > world.budget:
            continue
        if max(Counter(m.direction for m in combo).values()) > ds.max_per_direction:
            continue
        sid = set(ids)
        if any(a in sid and b in sid for a, b in any_inc):
            continue
        grids = np.meshgrid(*[options[i][0] for i in ids], indexing="ij")
        dist_mat = np.stack([g.ravel() for g in grids], axis=1)  # (P, 5)
        P = dist_mat.shape[0]
        mask = np.ones(P, dtype=bool)
        pos = {mid: j for j, mid in enumerate(ids)}
        for a, b in same_inc:
            if a in sid and b in sid:
                mask &= dist_mat[:, pos[a]] != dist_mat[:, pos[b]]
        if not mask.any():
            continue
        dist_mat = dist_mat[mask]
        P = dist_mat.shape[0]
        total = np.zeros((P, D, K))
        for j, mid in enumerate(ids):
            idx, deltas = options[mid]
            sel = dist_mat[:, j] if idx[0] != -1 else np.zeros(P, dtype=int)
            total += deltas[sel]
        for s in ds.synergies:
            if s.first in sid and s.second in sid:
                dcol = dist_mat[:, pos[s.first]]
                if dcol[0] == -1:
                    dcol = dist_mat[:, pos[s.second]]
                if dcol[0] == -1:
                    continue
                total[np.arange(P), dcol, kidx[s.indicator]] += s.bonus
        ind = np.clip(base[None] + total, 0, 100)
        dscore = ind @ w  # (P,D)
        avg = dscore @ pop
        mn = dscore.min(axis=1)
        ncrit = (ind < ds.critical_threshold).sum(axis=(1, 2))
        score = W_AVG * avg + W_MIN * mn - W_CRIT * ncrit
        all_scores.append(score)
        all_costs.append(cost)
        all_choices.append((ids, dist_mat))

    def decode(ci: int, row: int) -> List[Decision]:
        ids, dm = all_choices[ci]
        return [Decision(measure_id=m, district_id=(dists[int(d)] if d != -1 else None)) for m, d in zip(ids, dm[row])]

    flat_scores = np.concatenate(all_scores)
    combo_of = np.concatenate([np.full(len(s), i) for i, s in enumerate(all_scores)])
    row_of = np.concatenate([np.arange(len(s)) for s in all_scores])
    cost_of = np.concatenate([np.full(len(s), all_costs[i]) for i, s in enumerate(all_scores)])

    order = np.argsort(-flat_scores)
    top = [(float(flat_scores[i]), int(cost_of[i]), decode(int(combo_of[i]), int(row_of[i]))) for i in order[:25]]

    pareto = []
    best_so_far = -1e9
    for c in sorted(set(all_costs)):
        m = cost_of == c
        i = np.argmax(np.where(m, flat_scores, -1e9))
        s = float(flat_scores[i])
        if s > best_so_far + 1e-9:
            best_so_far = s
            pareto.append((int(c), s, decode(int(combo_of[i]), int(row_of[i]))))

    return OracleResult(
        n_valid=int(len(flat_scores)),
        best_score=top[0][0],
        best=top[0][2],
        top=top,
        pareto=pareto,
        scores_sorted=np.sort(flat_scores),
    )


def oracle(world: Optional[WorldState] = None, ds: Optional[Dataset] = None) -> OracleResult:
    ds = ds or load_dataset()
    world = world or default_world(ds)
    key = world_key(world)
    with _lock:
        if key in _cache:
            return _cache[key]
    res = _enumerate(world, ds)
    with _lock:
        _cache[key] = res
    return res


def percentile(score: float, res: OracleResult) -> float:
    """Доля допустимых наборов, которые не лучше данного (0..100)."""
    return float(np.searchsorted(res.scores_sorted, score, side="right") / len(res.scores_sorted) * 100)


def best_swaps(decisions: List[Decision], world: Optional[WorldState] = None, ds: Optional[Dataset] = None, limit: int = 5):
    """Локальные улучшения: заменить одно решение на любое другое (мера × район)."""
    ds = ds or load_dataset()
    world = world or default_world(ds)
    current = raw_score(decisions, world, ds)
    chosen = {d.measure_id for d in decisions}
    out = []
    for i, old in enumerate(decisions):
        for m in ds.measures:
            if m.id in chosen and m.id != old.measure_id:
                continue
            targets = [d.id for d in ds.districts] if m.is_district else [None]
            for t in targets:
                new = Decision(measure_id=m.id, district_id=t)
                if new == old:
                    continue
                cand = decisions[:i] + [new] + decisions[i + 1 :]
                v = validate(cand, world, ds)
                if not v.valid:
                    continue
                s = raw_score(cand, world, ds)
                if s > current + 1e-9:
                    out.append({"replace": old, "with": new, "score": round(s, 2), "gain": round(s - current, 2), "cost": v.total_cost})
    out.sort(key=lambda x: -x["gain"])
    return out[:limit]
