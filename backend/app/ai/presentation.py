"""Public operation status, separate from diagnostic records kept on the server."""

import re
from typing import Any

FAILED_MESSAGE = "Не удалось завершить операцию. Попробуйте ещё раз."
MESSAGES = {
    "queued": "Операция принята.",
    "interpreting": "Уточняем условия запроса.",
    "generating": "Формируем варианты.",
    "validating": "Проверяем варианты.",
    "repairing": "Уточняем варианты с учётом ваших условий.",
    "explaining": "Готовим объяснение результатов.",
    "failed": FAILED_MESSAGE,
    "interrupted": "Операция прервана. Отправьте запрос ещё раз.",
    "cancelled": "Операция отменена. Уже возникший расход сохраняется.",
    "needs_clarification": "Уточните условия запроса.",
    "completed": "Результаты готовы.",
}
_INTERNAL = re.compile(
    r"\b[A-Z]+(?:_[A-Z]+)+\b|\[fact:|\b[A-C]\.(?:critical_|activated_synergies|districts\.|score\.)"
    r"|Traceback|\b(?:TypeError|ReferenceError|SyntaxError|WinError|EPERM)\b"
    r"|Объяснение содержит неизвестную ссылку|Числа в пояснениях должны быть ссылками",
)


def public_run(run: dict[str, Any]) -> dict[str, Any]:
    """Copy without mutating the persisted failure or the agent's working state."""
    result = dict(run)
    status = run.get("status", "")
    if status != "completed":
        result["message"] = MESSAGES.get(status, "Обрабатываем запрос.")
    elif run.get("error"):
        result["message"] = "Расчёты готовы. Объяснение подготовлено по шаблону."
    result["events"] = [
        {"stage": event.get("stage", ""), "message": MESSAGES.get(event.get("stage"), "Обрабатываем запрос.")}
        for event in run.get("events", [])
    ]
    if run.get("error"):
        # Keep the stable machine-readable code, but never send diagnostic prose.
        result["error"] = {"code": run["error"].get("code", "OPERATION_FAILED"), "message": FAILED_MESSAGE}
    if result.get("clarification") and _INTERNAL.search(result["clarification"]):
        result["clarification"] = "Уточните желаемый результат и ограничения."
    return result


def public_history(history: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Cover historical errors, before entries received an explicit kind.
    diagnostic_texts = set()
    for run in runs:
        if run.get("error") or run.get("status") in {"failed", "interrupted"}:
            diagnostic_texts.update(text[:2000] for text in (
                run.get("message"), (run.get("error") or {}).get("message"),
            ) if isinstance(text, str))
    result = []
    for entry in history:
        content = str(entry.get("content", ""))
        if entry.get("role") == "assistant" and (
            entry.get("kind") == "error" or content in diagnostic_texts or _INTERNAL.search(content)
        ):
            result.append({**entry, "content": FAILED_MESSAGE, "kind": "error"})
        else:
            result.append(dict(entry))
    return result
