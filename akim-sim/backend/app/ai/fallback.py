"""Детерминированные объяснения без LLM.

Используются, когда ключ API не задан или запрос к модели упал: выдают ту же JSON-форму,
что и агенты, но на основе шаблонов и чисел из трассы. Так демо и тесты не зависят от сети.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .agents import COUNCIL_PERSONAS


def _fmt(x: float) -> str:
    return f"{x:+.2f}" if isinstance(x, (int, float)) else str(x)


def analyst(ctx: Dict[str, Any]) -> Dict[str, Any]:
    s = ctx["score"]
    ms = sorted(ctx["measures"], key=lambda m: -m["marginal_score"])
    best, worst = ms[0], ms[-1]
    strengths, risks, tradeoffs = [], [], []
    strengths.append(f"Наибольший вклад даёт {best['id']} «{best['name']}» ({best['district']}): {_fmt(best['marginal_score'])} к Score.")
    if s["n_crit_after"] < s["n_crit_before"]:
        strengths.append(f"Число критических показателей (<40) снизилось с {s['n_crit_before']} до {s['n_crit_after']} — штраф уменьшен.")
    if ctx["synergies"]:
        strengths.append("Сработали синергии: " + "; ".join(ctx["synergies"]) + ".")
    if s["n_crit_after"] > 0:
        risks.append("Остались критические значения: " + ", ".join(s["critical_cells_after"]) + " — каждое стоит −1 балл.")
    if ctx["remaining"] > 8:
        risks.append(f"Не использовано {ctx['remaining']} ед. бюджета — они не переносятся и не дают бонуса.")
    long_lag = [m for m in ctx["measures"] if m["lag"] >= 4]
    if long_lag:
        risks.append("Меры с лагом 4 квартала (" + ", ".join(m["id"] for m in long_lag) + ") реализуют только половину эффекта за горизонт.")
    if ctx["untouched_districts"]:
        risks.append("Районы без прямых изменений: " + ", ".join(ctx["untouched_districts"]) + ".")
    tradeoffs.append(f"Самый слабый район после мер — {s['d_min_district']} ({s['d_min']}); он даёт 30% веса в формуле.")
    tradeoffs.append(f"Наименее эффективная мера — {worst['id']} «{worst['name']}»: {_fmt(worst['marginal_score'])} за {worst['cost']} ед.")
    weakest = min(ctx["districts"], key=lambda d: d["score_after"])
    return {
        "headline": f"Score {s['final']} ({_fmt(s['delta'])} к базе {s['base']}) при бюджете {ctx['total_cost']}/{ctx['budget']}",
        "summary": (
            f"Сценарий поднимает городской балл с {s['base']} до {s['final']}. Средневзвешенный балл районов — {s['d_avg']}, "
            f"минимальный — {s['d_min']} ({s['d_min_district']}). Критических показателей после мер: {s['n_crit_after']}. "
            + (f"До теоретического максимума {ctx['oracle']['best_score']} не хватает {ctx['oracle']['gap_to_best']}; сценарий лучше {ctx['oracle']['percentile']}% допустимых наборов." if ctx.get("oracle") else "")
        ),
        "strengths": strengths,
        "risks": risks or ["Явных рисков по формуле не выявлено."],
        "tradeoffs": tradeoffs,
        "resident_voice": {"district": weakest["name"], "quote": f"У нас в районе балл {weakest['score_after']} — " + ("что-то сдвинулось, но до соседей далеко." if weakest["changed_indicators"] else "и ничего из плана нас не коснулось.")},
        "_mode": "fallback",
    }


def critic(ctx: Dict[str, Any]) -> Dict[str, Any]:
    s = ctx["score"]
    weaknesses: List[Dict[str, str]] = []
    if s["n_crit_after"]:
        weaknesses.append({"title": "Критические показатели не закрыты", "detail": ", ".join(s["critical_cells_after"]), "severity": "high"})
    if ctx["remaining"] >= 10:
        weaknesses.append({"title": "Простаивает бюджет", "detail": f"Остаток {ctx['remaining']} ед. — можно было усилить слабый район.", "severity": "medium"})
    low = [m for m in ctx["measures"] if m["score_per_cost"] < 0.02]
    for m in low:
        weaknesses.append({"title": f"Низкая отдача: {m['id']}", "detail": f"{m['name']} ({m['district']}): {_fmt(m['marginal_score'])} за {m['cost']} ед.", "severity": "medium"})
    if ctx["untouched_districts"]:
        weaknesses.append({"title": "Забытые районы", "detail": ", ".join(ctx["untouched_districts"]), "severity": "low"})
    if ctx.get("oracle") and ctx["oracle"]["gap_to_best"] > 1.0:
        weaknesses.append({"title": "Далеко от оптимума", "detail": f"Разрыв с лучшим набором {ctx['oracle']['gap_to_best']} балла.", "severity": "medium"})
    return {
        "verdict": "Сценарий рабочий, но есть что улучшить." if weaknesses else "Сценарий сбалансирован.",
        "weaknesses": weaknesses,
        "questions_to_team": [f"Почему именно {s['d_min_district']} остаётся самым слабым районом?", "Что команда будет делать при секвестре бюджета на 15%?"],
        "_mode": "fallback",
    }


def advisor(ctx: Dict[str, Any]) -> Dict[str, Any]:
    recs = []
    for sw in (ctx.get("oracle", {}).get("best_swaps") or [])[:3]:
        new_set = [sw["with_raw"] if d == sw["replace_raw"] else d for d in ctx["decisions_raw"]]
        recs.append({"title": f"Замена: {sw['with'].split(' — ')[0]}", "change": f"{sw['replace']} → {sw['with']}", "decisions": new_set, "new_score": sw["new_score"], "gain": sw["gain"], "cost": sw["cost"], "rationale": "Лучшая одиночная замена по расчёту движка (перебор всех вариантов «заменить одно решение»).", "verified": True})
    return {"recommendations": recs, "keep_as_is_argument": "Если команда сознательно жертвует баллами ради равномерности по районам — текущий набор оправдан.", "tool_calls": [], "_mode": "fallback"}


def council(ctx: Dict[str, Any]) -> Dict[str, Any]:
    dirs = {d["name"]: d for d in ctx["directions"]}
    s = ctx["score"]
    nura = next((d for d in ctx["districts"] if d["name"] == "Нура"), None)

    def sc(delta: float, base: int = 5) -> int:
        return max(1, min(10, round(base + delta)))

    eco = dirs["Озеленение и экология"]["after"] - dirs["Озеленение и экология"]["before"]
    tr = dirs["Транспорт"]["after"] - dirs["Транспорт"]["before"]
    speeches = [
        {"persona_id": "ecologist", "persona": "Эколог", "score": sc(eco), "statement": f"Экология в среднем по городу изменилась на {eco:+.1f}. " + ("Это движение в нужную сторону." if eco > 1 else "Смог в Сарыарке так и остаётся без ответа."), "demand": "Программа чистого топлива для Сарыарки."},
        {"persona_id": "transport", "persona": "Транспортник", "score": sc(tr), "statement": f"Транспорт: {tr:+.1f} по городу. " + ("Заметный сдвиг." if tr > 1 else "Пробки на мостах Есиля никуда не денутся."), "demand": "Хотя бы одна магистральная мера — ЛРТ или BRT."},
        {"persona_id": "finance", "persona": "Финансист", "score": sc((100 - ctx["remaining"]) / 20 - 3 + (2 if all(m["lag"] < 4 for m in ctx["measures"]) else 0)), "statement": f"Потрачено {ctx['total_cost']} из {ctx['budget']}, остаток {ctx['remaining']} сгорает. Средняя отдача {sum(m['marginal_score'] for m in ctx['measures']) / max(1, ctx['total_cost']):.3f} балла на единицу.", "demand": "Убрать меры с отдачей ниже 0.02 балла за единицу."},
        {"persona_id": "nura", "persona": "Депутат от Нуры", "score": sc((nura["score_after"] - nura["score_before"]) if nura else 0), "statement": (f"Нура: балл {nura['score_before']} → {nura['score_after']}. " if nura else "") + ("Наконец-то нас заметили." if nura and nura["score_after"] - nura["score_before"] > 2 else "Нас снова оставили последними."), "demand": "Школа и поликлиника в Нуре в первом же пакете."},
    ]
    return {
        "speeches": speeches,
        "moderator": {"consensus": f"Все согласны, что итог {s['final']} — шаг вперёд от базы {s['base']}.", "conflict": "Экология и транспорт конкурируют за один бюджет; финансист требует отдачи, депутат от Нуры — справедливости.", "verdict": "Совет принимает сценарий к сведению и просит проработать рекомендации советника."},
        "_mode": "fallback",
    }


def event_narrator(ctx: Dict[str, Any], before_score: float) -> Dict[str, Any]:
    ev = ctx["event"]
    return {
        "briefing": f"СРОЧНО. {ev['title']}. {ev['narrative']}",
        "impact_summary": f"Score текущего плана изменился с {before_score} до {ctx['score']['final']}; критических показателей теперь {ctx['score']['n_crit_after']}.",
        "advice": ["Пересмотрите набор: проверьте, не заблокированы ли меры и укладывается ли план в новый бюджет.", "Начните с района, где появились критические значения."],
        "_mode": "fallback",
    }
