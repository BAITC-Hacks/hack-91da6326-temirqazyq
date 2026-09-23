import type { ValidationError } from "./types";

export const actionUnavailable =
  "Не удалось выполнить действие. Повторите попытку.";
export const serviceUnavailable =
  "Сервис временно недоступен. Попробуйте позже.";

// Error text is diagnostic data, including responses from an older backend.
// Only messages owned by the interface may enter an error notice.
export function publicErrorMessage(value: unknown): string {
  const message = value instanceof Error ? value.message : value;
  return message === serviceUnavailable
    ? serviceUnavailable
    : actionUnavailable;
}

const technicalDetails =
  /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b|\b[A-C]\.[a-z_]|\[fact:|Traceback|\b(?:TypeError|SyntaxError|ReferenceError|Exception)\b|(?:[a-z]:\\|node_modules|\/app\/)|неизвестн\S* ссылк\S* на факт|объяснение содержит|ошибка(?:\s+\w+){0,3}\s*:/i;

export function publicAssistantText(
  value: string,
  fallback = actionUnavailable,
): string {
  return technicalDetails.test(value) ? fallback : value;
}

const validationHints: Record<string, string> = {
  DECISION_COUNT: "Выберите ровно 5 решений.",
  TOO_MANY_DECISIONS: "Можно выбрать не больше 5 решений.",
  DUPLICATE_MEASURE: "Каждую меру можно выбрать только один раз.",
  UNKNOWN_MEASURE: "Выберите меру из доступного списка.",
  UNKNOWN_DISTRICT: "Выберите район из доступного списка.",
  DISTRICT_REQUIRED: "Укажите район для выбранной меры.",
  CITY_DISTRICT_FORBIDDEN: "Для общегородской меры не нужно указывать район.",
  CATEGORY_LIMIT: "Выберите не больше двух мер из одной категории.",
  BUDGET_EXCEEDED: "Стоимость выбранных решений превышает бюджет.",
  USER_BUDGET_EXCEEDED: "Уменьшите стоимость решений с учётом резерва бюджета.",
  INCOMPATIBLE_MEASURES: "Замените несовместимые меры в выбранном сценарии.",
  EXCLUDED_MEASURE: "Уберите исключённую меру из выбранного сценария.",
  DISTRICT_NOT_ALLOWED: "Выберите район, разрешённый условиями запроса.",
  LOCKED_DECISION_MISSING: "Сохраните зафиксированные решения в сценарии.",
};

export function validationHint(issue: ValidationError): string {
  return (
    validationHints[issue.code] || "Проверьте выбранные решения и ограничения."
  );
}
