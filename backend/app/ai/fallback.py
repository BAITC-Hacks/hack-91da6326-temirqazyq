from typing import Any

from .schemas import Explanation

INDICATOR_NAMES = {
    "T1": "разгрузка дорог", "T2": "общественный транспорт",
    "E1": "озеленение", "E2": "качество воздуха",
    "S1": "школы и детсады", "S2": "первичная медицинская помощь",
    "B1": "безопасность улиц", "B2": "безопасность движения",
    "C1": "надёжность ЖКХ", "C2": "обработка обращений",
}
CATEGORY_NAMES = {
    "transport": "Транспорт", "ecology": "Экология", "social": "Социальная сфера",
    "safety": "Безопасность", "services": "Городские сервисы",
}


def explain_simulation(result: dict[str, Any]) -> Explanation:
    score, budget = result["score"], result["budget"]
    improved = sorted(result["city_indicators"]["delta"].items(), key=lambda item: (-item[1], item[0]))
    strengths = [
        f"{INDICATOR_NAMES.get(key, key).capitalize()}: средний городской показатель вырос на {delta:.2f}."
        for key, delta in improved[:3] if delta > 0
    ]
    for synergy in result["activated_synergies"]:
        effects = ", ".join(f"{key} +{value:g}" for key, value in synergy["effects"].items())
        strengths.append(f"Синергия {' + '.join(synergy['measure_ids'])} в районе {synergy['district']}: {effects} без снижения из-за лага.")
    risks = [
        f"{item['district']}: {INDICATOR_NAMES.get(item['indicator'], item['indicator'])} остаётся на уровне {item['value']:.2f}, ниже критического порога."
        for item in result["critical_after"]
    ]
    weakest = result["weakest_district"]["after"]
    risks.append(f"Самый низкий районный индекс: {weakest['name']} — {weakest['score']:.2f}.")
    tradeoffs = [f"Использовано {budget['spent']:g} из {budget['total']:g} единиц бюджета; резерв — {budget['remaining']:g}."]
    for name, district in result["districts"].items():
        for key, delta in district["indicator_deltas"].items():
            if delta < 0:
                tradeoffs.append(f"Побочный эффект в районе {name}: {INDICATOR_NAMES.get(key, key)} {delta:+.2f}.")
    tradeoffs.append("Эффекты мер уменьшены с учётом времени запуска. Вклад leave-one-out включает потерю связанных синергий; вклады нельзя просто складывать.")
    recommendations = []
    if result["critical_after"]:
        recommendations.append("В следующем сценарии направьте меры на оставшиеся критические показатели и сравните потерю эффекта в других направлениях.")
    else:
        recommendations.append("Критических показателей не осталось. Сравните рост слабейшего района с улучшением среднего городского индекса.")
    untouched = [CATEGORY_NAMES[key] for key, delta in result["category_deltas"].items() if delta <= 0]
    if untouched:
        recommendations.append(f"Проверьте альтернативу с акцентом на направления без улучшения: {', '.join(untouched)}.")
    recommendations.append("Откройте Scenario Lab, задайте резерв бюджета и сравните несколько допустимых вариантов.")
    return Explanation(
        summary=f"Качество жизни: {score['before']:.2f} → {score['after']:.2f} ({score['delta']:+.2f}). Критических показателей: {len(result['critical_before'])} → {len(result['critical_after'])}. Это результат условной модели города.",
        strengths=strengths, risks=risks, tradeoffs=tradeoffs, recommendations=recommendations,
    )


def explain_comparison(a: dict[str, Any], b: dict[str, Any]) -> Explanation:
    strengths = [
        f"{CATEGORY_NAMES[key]}: прирост A {a['category_deltas'][key]:+.2f}, B {b['category_deltas'][key]:+.2f}."
        for key in CATEGORY_NAMES
        if abs(a["category_deltas"][key] - b["category_deltas"][key]) > 1e-9
    ]
    return Explanation(
        summary=f"Сценарий A: Score {a['score']['after']:.2f}, бюджет {a['budget']['spent']:g}. Сценарий B: Score {b['score']['after']:.2f}, бюджет {b['budget']['spent']:g}. Выбор зависит от приоритета и распределения улучшений.",
        strengths=strengths or ["У сценариев одинаковые изменения по направлениям."],
        risks=[f"Критических показателей: A — {len(a['critical_after'])}, B — {len(b['critical_after'])}.",
               f"Слабейший район A: {a['weakest_district']['after']['name']} ({a['weakest_district']['after']['score']:.2f}); B: {b['weakest_district']['after']['name']} ({b['weakest_district']['after']['score']:.2f})."],
        tradeoffs=[f"Резерв бюджета: A — {a['budget']['remaining']:g}, B — {b['budget']['remaining']:g}.",
                  f"Активных синергий: A — {len(a['activated_synergies'])}, B — {len(b['activated_synergies'])}."],
        recommendations=["Сопоставьте городской Score, слабейший район и оставшиеся критические показатели с выбранным приоритетом.", "Проверьте показатели конкретных районов: одинаковый городской прирост может распределяться по-разному."],
    )

