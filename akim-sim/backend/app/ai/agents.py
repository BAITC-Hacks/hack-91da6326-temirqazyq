"""Агенты: Аналитик, Критик, Советник (с инструментами движка), Совет депутатов, Рассказчик событий.

Каждый агент = системный промпт + контекст (числа из движка) + JSON-схема ответа.
Советник дополнительно работает в агентном цикле: вызывает инструменты движка
(``score_scenario``, ``best_swaps``, ``oracle_best``) и обязан цитировать только
цифры, полученные от инструментов.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..engine.data import Dataset, load_dataset
from ..engine.models import Decision, WorldState
from ..engine.optimizer import best_swaps, oracle
from ..engine.scorer import score_scenario
from ..engine.validator import validate
from .context import context_json, decisions_human
from .llm import LLM

COMMON_RULES = """Ты работаешь внутри AI-симулятора «Аким на 5 часов» (Астана, 5 условных районов, 8 кварталов).
Все числа уже посчитаны детерминированным движком и переданы тебе в JSON. Твоя задача — объяснять, сравнивать и советовать.
Жёсткие правила:
1. Не считай и не придумывай числа. Цитируй только значения из контекста (Score, дельты, стоимость, перцентиль).
2. Пиши по-русски, конкретно, без воды. Называй районы и мероприятия по именам.
3. Отвечай строго JSON-объектом по указанной схеме, без текста вокруг."""

ANALYST_SYS = COMMON_RULES + """
Роль: главный аналитик акимата. Объясни итоговый Astana Quality of Life Score: почему он такой, какие меры дали вклад, где компромиссы.
Схема ответа:
{"headline": "одна фраза-вердикт", "summary": "3-5 предложений", "strengths": ["..."], "risks": ["..."], "tradeoffs": ["..."], "resident_voice": {"district": "название района", "quote": "1-2 предложения от лица жителя района о том, что изменится за 2 года"}}"""

CRITIC_SYS = COMMON_RULES + """
Роль: независимый критик (аудитор). Ищи слабые места сценария: неиспользованный бюджет, забытые районы (особенно самый слабый), меры с низкой отдачей на единицу стоимости, длинные лаги, оставшиеся критические показатели (<40), перекос в одно направление.
Схема ответа:
{"verdict": "одна фраза", "weaknesses": [{"title": "...", "detail": "...", "severity": "high|medium|low"}], "questions_to_team": ["..."]}"""

ADVISOR_SYS = COMMON_RULES + """
Роль: советник по оптимизации. У тебя есть инструменты движка: score_scenario (посчитать любой набор), best_swaps (лучшие одиночные замены для текущего набора), oracle_best (глобально лучший допустимый набор).
Алгоритм: 1) вызови best_swaps для текущего набора; 2) при желании проверь 1-2 собственные идеи через score_scenario (учитывай правила: ровно 5 мер, ≤2 на направление, без повторов, несовместимости M1/M3, M4+M7 и M5+M13 в одном районе, бюджет); 3) сформируй 2-3 рекомендации с посчитанным Score.
Никогда не приводи Score, который не вернул инструмент.
Схема финального ответа:
{"recommendations": [{"title": "...", "change": "что заменить на что", "decisions": [{"measure_id": "M1", "district_id": "nura|null"}], "new_score": 0.0, "gain": 0.0, "cost": 0, "rationale": "почему это лучше и какой ценой"}], "keep_as_is_argument": "когда текущий набор всё же оправдан"}"""

COUNCIL_PERSONAS = [
    {"id": "ecologist", "name": "Эколог", "stance": "Качество воздуха и зелень важнее всего; смог в Сарыарке — чрезвычайная ситуация."},
    {"id": "transport", "name": "Транспортник", "stance": "Пробки — главная боль; без ЛРТ/BRT и светофоров город встанет."},
    {"id": "finance", "name": "Финансист", "stance": "Отдача на единицу бюджета, остаток, лаги; длинные проекты с лагом 4 — риск."},
    {"id": "nura", "name": "Депутат от Нуры", "stance": "Самый слабый район должен получить приоритет: школы, поликлиники, транспорт."},
]

COUNCIL_SYS = COMMON_RULES + """
Роль: ты — модератор Совета депутатов. Ниже 4 персоны с разными ценностями. Сгенерируй выступление каждого (2-3 предложения, в характере персоны, с опорой на числа из контекста) и оценку сценария от 1 до 10 с точки зрения персоны. Затем — итог модератора: где консенсус, где конфликт, чего не хватает.
Схема ответа:
{"speeches": [{"persona_id": "...", "persona": "...", "score": 7, "statement": "...", "demand": "одно конкретное требование"}], "moderator": {"consensus": "...", "conflict": "...", "verdict": "..."}}"""

EVENT_SYS = COMMON_RULES + """
Роль: рассказчик. Дано событие «Чёрный лебедь» и то, как оно изменило показатели и текущий план команды. Напиши короткую драматичную сводку (3-4 предложения) как срочное сообщение в акимат и 2-3 совета, что пересмотреть.
Схема ответа:
{"briefing": "...", "impact_summary": "1-2 предложения с числами из контекста", "advice": ["..."]}"""


def _tools_spec() -> List[Dict[str, Any]]:
    dec_schema = {
        "type": "array",
        "items": {"type": "object", "properties": {"measure_id": {"type": "string"}, "district_id": {"type": ["string", "null"]}}, "required": ["measure_id"]},
    }
    return [
        {"type": "function", "function": {"name": "score_scenario", "description": "Проверить и посчитать Score для набора из 5 решений. Возвращает валидность, причины ошибок, score, стоимость.", "parameters": {"type": "object", "properties": {"decisions": dec_schema}, "required": ["decisions"]}}},
        {"type": "function", "function": {"name": "best_swaps", "description": "Лучшие одиночные замены для текущего набора команды (уже посчитаны движком).", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "oracle_best", "description": "Глобально лучший допустимый набор и его Score.", "parameters": {"type": "object", "properties": {}}}},
    ]


def _tool_handlers(decisions: List[Decision], world: WorldState, ds: Dataset):
    def score_tool(decisions: List[Dict[str, Any]] = None, **_: Any):  # noqa: A002 — имя параметра диктует схема инструмента
        decs = [Decision(measure_id=d["measure_id"], district_id=d.get("district_id") or None) for d in (decisions or [])]
        v = validate(decs, world, ds)
        if not v.valid:
            return {"valid": False, "issues": [i.message for i in v.issues], "cost": v.total_cost}
        r = score_scenario(decs, world, ds)
        return {"valid": True, "score": r.score, "delta_vs_base": r.delta, "cost": r.total_cost, "remaining": r.remaining, "n_crit": r.n_crit, "d_min_district": ds.district_map[r.d_min_district].name}

    def swaps_tool():
        return [{"replace": decisions_human([s["replace"]], ds)[0], "with": decisions_human([s["with"]], ds)[0],
                 "with_raw": s["with"].model_dump(), "replace_raw": s["replace"].model_dump(), "new_score": s["score"], "gain": s["gain"], "cost": s["cost"]}
                for s in best_swaps(decisions, world, ds, limit=6)]

    def oracle_tool():
        res = oracle(world, ds)
        return {"best_score": round(res.best_score, 2), "decisions": [d.model_dump() for d in res.best], "human": decisions_human(res.best, ds)}

    return {"score_scenario": score_tool, "best_swaps": swaps_tool, "oracle_best": oracle_tool}


# ----------------------------------------------------------------------------
def run_analyst(llm: LLM, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return llm.chat_json(ANALYST_SYS, "Контекст расчёта:\n" + context_json(ctx))


def run_critic(llm: LLM, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return llm.chat_json(CRITIC_SYS, "Контекст расчёта:\n" + context_json(ctx), temperature=0.4)


def run_advisor(llm: LLM, ctx: Dict[str, Any], decisions: List[Decision], world: WorldState, ds: Optional[Dataset] = None) -> Dict[str, Any]:
    ds = ds or load_dataset()
    slim = {k: v for k, v in ctx.items() if k not in ("districts",)}
    out = llm.chat_tools(ADVISOR_SYS, "Текущий набор и расчёт:\n" + context_json(slim), _tools_spec(), _tool_handlers(decisions, world, ds))
    result = out["result"]
    # страховка: перепроверяем каждую рекомендацию движком, чтобы в UI не попали выдуманные числа
    verified = []
    for rec in result.get("recommendations", []) or []:
        try:
            decs = [Decision(measure_id=d["measure_id"], district_id=d.get("district_id") or None) for d in rec.get("decisions", [])]
            v = validate(decs, world, ds)
            if v.valid:
                r = score_scenario(decs, world, ds)
                rec["new_score"], rec["cost"], rec["gain"], rec["verified"] = r.score, r.total_cost, round(r.score - ctx["score"]["final"], 2), True
            else:
                rec["verified"] = False
                rec["invalid_reason"] = "; ".join(i.message for i in v.issues)
        except Exception as exc:  # noqa: BLE001
            rec["verified"] = False
            rec["invalid_reason"] = str(exc)
        verified.append(rec)
    result["recommendations"] = verified
    result["tool_calls"] = [{"name": t["name"], "arguments": t["arguments"]} for t in out["tool_calls"]]
    return result


DESIGNER_SYS = """Ты — аналитик кризисного штаба акимата Астаны в AI-симуляторе «Аким на 5 часов».
Тебе описывают своими словами городскую проблему. Задача: перевести её в ПАРАМЕТРЫ модели, ничего не выдумывая сверх описанного.

Показатели (0-100, больше = лучше):
T1 разгрузка дорог, T2 доступность общественного транспорта, E1 озеленение, E2 качество воздуха,
S1 школы и детсады, S2 поликлиники, B1 безопасность улиц, B2 безопасность дорожного движения,
C1 надёжность ЖКХ, C2 скорость решения обращений.

Районы: esil (Есиль), almaty (Алматы), saryarka (Сарыарка), baikonur (Байконур), nura (Нура).
Меры, которые можно заблокировать: M1…M14.

Правила перевода:
1. Проблема ухудшает показатели — значит delta ОТРИЦАТЕЛЬНАЯ. Типичный масштаб: −5 лёгкий, −12 серьёзный, −20 катастрофический.
2. Ставь шок только тем районам и показателям, которые реально затронуты описанием. От 1 до 6 шоков.
3. Если из описания следует, что какую-то меру больше нельзя реализовать (сорван подрядчик, запрет) — укажи её в blocked_measures. Иначе пустой список.
4. Если описание про деньги (секвестр, штраф, удорожание) — укажи budget_delta отрицательным числом, иначе 0.
5. Если район не назван, но проблема общегородская — распредели шоки по нескольким районам.

Схема ответа:
{"title": "короткий заголовок события", "narrative": "2-3 предложения в стиле новостной сводки",
 "shocks": [{"district": "nura", "indicator": "C1", "delta": -12}],
 "blocked_measures": [], "budget_delta": 0,
 "interpretation": "одно предложение: как ты понял описание и почему выбрал такие показатели"}"""


def run_event_designer(llm: LLM, text: str) -> Dict[str, Any]:
    """Свободный текст пользователя → структура события. Числа применяет движок, не модель."""
    return llm.chat_json(DESIGNER_SYS, f"Описание проблемы от команды:\n{text}", temperature=0.4)


def run_council(llm: LLM, ctx: Dict[str, Any]) -> Dict[str, Any]:
    personas = "\n".join(f"- {p['id']} / {p['name']}: {p['stance']}" for p in COUNCIL_PERSONAS)
    return llm.chat_json(COUNCIL_SYS, f"Персоны:\n{personas}\n\nКонтекст расчёта:\n" + context_json(ctx), temperature=0.7)


def run_event_narrator(llm: LLM, ctx: Dict[str, Any], before_score: float) -> Dict[str, Any]:
    payload = {"event": ctx["event"], "score_before_event": before_score, "score_after_event": ctx["score"]["final"], "critical_after": ctx["score"]["critical_cells_after"], "districts": ctx["districts"], "budget": ctx["budget"]}
    return llm.chat_json(EVENT_SYS, context_json(payload), temperature=0.8)
