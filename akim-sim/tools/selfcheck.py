#!/usr/bin/env python3
"""Независимая перепроверка математики симулятора.

Смысл файла: НЕ доверять движку. Формула и правила реализованы здесь заново, по описанию
из датасета, и ни одна строка не импортируется из app.engine. Затем оба результата
сравниваются. Если сойдутся — значит, либо обе реализации верны, либо в них одинаковая
ошибка, что маловероятно при независимом написании.

    python tools/selfcheck.py           быстрые проверки, около секунды
    python tools/selfcheck.py --full    плюс полный перебор всех наборов (пара минут)

Код возврата 0 — всё сошлось, 1 — есть расхождение.
"""
from __future__ import annotations

import itertools
import json
import pathlib
import sys
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# ─────────────────────────── независимая реализация ───────────────────────────

_d = json.loads((DATA / "districts.json").read_text(encoding="utf-8"))
_m = json.loads((DATA / "measures.json").read_text(encoding="utf-8"))

H = _d["horizon_quarters"]
BUDGET = _d["budget"]
NEED = _d["decisions_required"]
MAXDIR = _d["max_per_direction"]
THR = _d["critical_threshold"]
W = {i["code"]: i["weight"] for i in _d["indicators"]}
CODES = [i["code"] for i in _d["indicators"]]
DISTS = [d["id"] for d in _d["districts"]]
POP = {d["id"]: d["population_share"] for d in _d["districts"]}
BASE = {d["id"]: dict(d["indicators"]) for d in _d["districts"]}
M = {m["id"]: m for m in _m["measures"]}
SYN = _m["synergies"]
INC = _m["incompatibilities"]

EXAMPLE = [("M7", "nura"), ("M8", "nura"), ("M10", "nura"), ("M12", None), ("M5", "saryarka")]


def score(plan) -> float:
    """Score по формуле раздела 3 датасета. Плоско и буквально, чтобы легко читалось глазами."""
    ind = {d: dict(BASE[d]) for d in DISTS}
    chosen = dict(plan)

    for mid, dd in plan:                                   # эффекты, масштабированные лагом
        m = M[mid]
        share = (H - m["lag"]) / H
        targets = [dd] if m["scope"] == "district" else DISTS
        for code, val in m["effects"].items():
            for t in targets:
                ind[t][code] += val * share

    for s in SYN:                                          # синергия лагом НЕ масштабируется
        if s["first"] in chosen and s["second"] in chosen:
            home = chosen[s["first"]] or chosen[s["second"]]
            if home is not None:
                ind[home][s["indicator"]] += s["bonus"]

    for t in ind:                                          # клип после всего
        for c in ind[t]:
            ind[t][c] = max(0.0, min(100.0, ind[t][c]))

    dsc = {t: sum(W[c] * ind[t][c] for c in CODES) for t in DISTS}
    d_avg = sum(POP[t] * dsc[t] for t in DISTS)
    n_crit = sum(1 for t in DISTS for c in CODES if ind[t][c] < THR)
    return 0.7 * d_avg + 0.3 * min(dsc.values()) - 1.0 * n_crit


def enumerate_all():
    """Все допустимые наборы: возвращает (количество, лучший Score, лучший набор)."""
    inc_any = [(i["a"], i["b"]) for i in INC if i["scope"] != "same_district"]
    inc_same = [(i["a"], i["b"]) for i in INC if i["scope"] == "same_district"]
    n_valid, best = 0, (-1e9, None)

    for combo in itertools.combinations(sorted(M), NEED):
        if sum(M[c]["cost"] for c in combo) > BUDGET:
            continue
        if any(v > MAXDIR for v in Counter(M[c]["direction"] for c in combo).values()):
            continue
        sset = set(combo)
        if any(a in sset and b in sset for a, b in inc_any):
            continue
        need_district = [c for c in combo if M[c]["scope"] == "district"]
        for assign in itertools.product(DISTS, repeat=len(need_district)):
            pos = dict(zip(need_district, assign))
            if any(a in pos and b in pos and pos[a] == pos[b] for a, b in inc_same):
                continue
            plan = [(c, pos.get(c)) for c in combo]
            n_valid += 1
            s = score(plan)
            if s > best[0]:
                best = (s, plan)
    return n_valid, best[0], best[1]


# ──────────────────────────────── сравнение ────────────────────────────────

def main() -> int:
    full = "--full" in sys.argv
    sys.path.insert(0, str(ROOT / "backend"))
    from app.engine.data import load_dataset                     # noqa: E402
    from app.engine.models import Decision                       # noqa: E402
    from app.engine.scorer import raw_score, shapley_contributions, score_scenario  # noqa: E402
    from app.engine.validator import default_world               # noqa: E402

    ds = load_dataset()
    world = default_world(ds)
    ex = [Decision(measure_id=m, district_id=d) for m, d in EXAMPLE]

    rows, ok = [], True

    def cmp(name, mine, theirs, tol=1e-9):
        nonlocal ok
        good = abs(mine - theirs) <= tol if isinstance(mine, float) else mine == theirs
        ok = ok and good
        rows.append((name, mine, theirs, good))

    cmp("База без решений", score([]), raw_score([], world, ds))
    cmp("Пример из датасета", score(EXAMPLE), raw_score(ex, world, ds))

    # сумма вкладов по Шепли обязана равняться приросту — это свойство, а не совпадение
    phi = shapley_contributions(ex, world, ds)
    cmp("Сумма вкладов по Шепли = прирост", sum(phi), raw_score(ex, world, ds) - raw_score([], world, ds), tol=1e-9)

    # то, что показано на экране, должно сходиться при вычитании
    r = score_scenario(ex, world, ds)
    cmp("Показанная дельта = score − база", round(r.score - r.base_score, 2), r.delta)

    if full:
        t0 = time.perf_counter()
        n_valid, best_score, best_plan = enumerate_all()
        secs = time.perf_counter() - t0
        from app.engine.optimizer import oracle                   # noqa: E402
        res = oracle(world, ds)
        cmp("Число допустимых наборов", n_valid, res.n_valid)
        cmp("Глобальный максимум", best_score, res.best_score, tol=1e-6)
        rows.append((f"(перебор занял {secs:.0f} c)", "", "", True))
        best_str = ", ".join(f"{m}{'/' + d if d else ''}" for m, d in sorted(best_plan))
        rows.append((f"Лучший набор: {best_str}", "", "", True))

    width = max(len(r[0]) for r in rows)
    print(f"\n{'проверка'.ljust(width)}  {'независимо':>14}  {'движок':>14}")
    print("─" * (width + 34))
    for name, mine, theirs, good in rows:
        f = (lambda v: f"{v:.6f}" if isinstance(v, float) else str(v))
        mark = "" if mine == "" else ("  ✓" if good else "  ✗ РАСХОЖДЕНИЕ")
        print(f"{name.ljust(width)}  {f(mine):>14}  {f(theirs):>14}{mark}")

    print("\n" + ("ВСЁ СОШЛОСЬ — две независимые реализации дают одно и то же."
                  if ok else "ЕСТЬ РАСХОЖДЕНИЕ — смотрите строки со знаком ✗."))
    if not full:
        print("Полный перебор всех наборов не запускался: добавьте --full.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
