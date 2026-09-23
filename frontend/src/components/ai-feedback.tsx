"use client";

import { useRef, useState } from "react";
import {
  Info,
  Sparkles,
  Square,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import type {
  AIRun,
  ConstraintState,
  Narrative,
  SavedScenario,
  SimulationResult,
} from "@/lib/types";
import { api, categories, fmt, indicatorNames } from "@/lib/ui";
import { isActiveRun, useAIRun } from "@/lib/use-ai-run";
import { publicAssistantText } from "@/lib/feedback";
import { ErrorBox, Spinner } from "./common";

const stages: Record<string, string> = {
  queued: "Ожидание запуска",
  interpreting: "Интерпретация запроса",
  generating: "Формирование вариантов",
  validating: "Проверка ограничений",
  repairing: "Исправление вариантов",
  explaining: "Подготовка объяснения",
  completed: "Операция завершена",
  needs_clarification: "Нужно уточнение",
  failed: "Операция не выполнена",
  cancelled: "Операция отменена",
  interrupted: "Операция прервана перезапуском сервера",
};

export function ConstraintsView({
  constraints,
}: {
  constraints: ConstraintState;
}) {
  return (
    <section className="constraints-view">
      <h3>Как понят запрос</h3>
      <dl>
        <div>
          <dt>Максимальный бюджет</dt>
          <dd>{constraints.max_budget}</dd>
        </div>
        <div>
          <dt>Минимальный резерв</dt>
          <dd>{constraints.reserve_budget}</dd>
        </div>
        <div>
          <dt>Доступно на решения</dt>
          <dd>
            {Math.min(
              100,
              constraints.max_budget,
              100 - constraints.reserve_budget,
            )}
          </dd>
        </div>
        <div>
          <dt>Исключённые меры</dt>
          <dd>{constraints.excluded_measure_ids.join(", ") || "Нет"}</dd>
        </div>
        <div>
          <dt>Зафиксированные решения</dt>
          <dd>
            {constraints.locked_decisions
              .map((d) => `${d.measure_id} · ${d.district || "Весь город"}`)
              .join("; ") || "Нет"}
          </dd>
        </div>
        <div>
          <dt>Разрешённые районы для мер</dt>
          <dd>
            {constraints.allowed_districts === null
              ? "Все районы"
              : constraints.allowed_districts.length
                ? constraints.allowed_districts.join(", ")
                : "Ни один район"}
          </dd>
        </div>
        <div>
          <dt>Фокус анализа</dt>
          <dd>{constraints.focus_district || "Весь город"}</dd>
        </div>
        <div>
          <dt>Предпочтения</dt>
          <dd>
            {constraints.preferred_categories
              .map((c) => categories[c]?.label || c)
              .join(", ") || "Не заданы"}
          </dd>
        </div>
        <div>
          <dt>Показатели для анализа</dt>
          <dd>
            {constraints.analysis_indicators
              .map((k) => indicatorNames[k] || k)
              .join(", ") || "Все показатели"}
          </dd>
        </div>
        <div>
          <dt>Запрошено вариантов</dt>
          <dd>{constraints.requested_scenario_count}</dd>
        </div>
      </dl>
      <p>
        <Info size={13} />
        Фокус анализа и предпочтения не запрещают меры в других районах. Жёсткие
        ограничения показаны отдельно.
      </p>
    </section>
  );
}

export function NarrativeView({ narrative }: { narrative: Narrative }) {
  const sections = [
    { label: "Наблюдения", values: narrative.observations },
    { label: "Оставшиеся проблемы", values: narrative.remaining_issues },
    { label: "Компромиссы", values: narrative.tradeoffs },
    { label: "Ограничения анализа", values: narrative.limitations },
  ];
  return (
    <div className="advisor-content">
      <div className="advisor-source">
        <Sparkles size={13} />
        {narrative.source === "template"
          ? "Шаблонное объяснение, без вызова модели"
          : "Объяснение модели по проверенным расчётам"}
      </div>
      <p>{narrative.summary}</p>
      {sections
        .filter((s) => s.values.length)
        .map((s) => (
          <div key={s.label}>
            <h4>{s.label}</h4>
            <ul>
              {s.values.map((value, i) => (
                <li key={i}>{value}</li>
              ))}
            </ul>
          </div>
        ))}
      {narrative.evidence_refs.length > 0 && (
        <details className="evidence-list">
          <summary>
            Ссылки на расчётные факты ({narrative.evidence_refs.length})
          </summary>
          <ul>
            {narrative.evidence_refs.map((ref) => (
              <li key={ref}>
                <code>{ref}</code>
              </li>
            ))}
          </ul>
          <p>
            Ссылки помогают проверить цифры; они не гарантируют отсутствие
            содержательных ошибок модели.
          </p>
        </details>
      )}
    </div>
  );
}

export function RunFeedback({
  run,
  busy,
  error,
  onCancel,
}: {
  run: AIRun | null;
  busy: boolean;
  error: string;
  onCancel: () => void;
}) {
  const metadata = run?.metadata;
  return (
    <div className="run-feedback" aria-live="polite">
      {error && run?.status !== "failed" && <ErrorBox text={error} />}
      {busy && !run && <Spinner text="Запускаем операцию…" />}
      {run && (
        <>
          <div className="run-stage">
            <strong>
              {busy ? (
                <Spinner text={stages[run.status] || "Выполняется операция"} />
              ) : (
                <>
                  {run.status === "completed" ? (
                    <CheckCircle2 size={16} />
                  ) : (
                    <AlertTriangle size={16} />
                  )}
                  {stages[run.status] || "Состояние операции неизвестно"}
                </>
              )}
            </strong>
            {isActiveRun(run) && (
              <button className="button secondary" onClick={onCancel}>
                <Square size={13} />
                Отменить
              </button>
            )}
          </div>
          {run.status === "failed" || run.status === "interrupted" ? (
            <p>
              Попробуйте отправить запрос ещё раз. Ручной режим остаётся
              доступен.
            </p>
          ) : run.message && run.status !== "needs_clarification" ? (
            <p>{publicAssistantText(run.message, stages[run.status])}</p>
          ) : null}
          {run.clarification && (
            <div className="clarification-box">
              <Info size={16} />
              <span>
                {publicAssistantText(
                  run.clarification,
                  "Уточните условия запроса и отправьте его ещё раз.",
                )}
              </span>
            </div>
          )}
          {run.events.length > 0 && (
            <details className="run-events">
              <summary>Этапы выполнения</summary>
              <ol>
                {run.events.map((event, i) => (
                  <li key={i}>
                    <b>{stages[event.stage] || "Событие операции"}</b>
                  </li>
                ))}
              </ol>
            </details>
          )}
          {run.explanation && <NarrativeView narrative={run.explanation} />}
          {metadata && (
            <details className="ai-metadata" open={!busy}>
              <summary>Модель и расходы этой операции</summary>
              <p>
                {metadata.cache_hit
                  ? "Ранее сформировано моделью; возвращено из кеша."
                  : metadata.fallback_used
                    ? "Шаблонный режим: провайдер модели не сформировал этот результат."
                    : metadata.used_llm
                      ? "Получен ответ облачной модели."
                      : "Использование облачной модели не подтверждено."}
              </p>
              <dl>
                <div>
                  <dt>Операция</dt>
                  <dd>{run.run_id}</dd>
                </div>
                <div>
                  <dt>Провайдер</dt>
                  <dd>{metadata.provider || "Не задан"}</dd>
                </div>
                <div>
                  <dt>Запрошенная модель</dt>
                  <dd>{metadata.requested_model || "Не задана"}</dd>
                </div>
                <div>
                  <dt>Ответившая модель</dt>
                  <dd>{metadata.actual_model || "Неизвестна"}</dd>
                </div>
                <div>
                  <dt>Фактические вызовы API</dt>
                  <dd>{metadata.api_calls}</dd>
                </div>
                <div>
                  <dt>Входные / выходные токены</dt>
                  <dd>
                    {metadata.usage
                      ? `${metadata.usage.input_tokens} / ${metadata.usage.output_tokens}`
                      : "Неизвестно"}
                  </dd>
                </div>
                <div>
                  <dt>Входные токены из кеша</dt>
                  <dd>{metadata.usage?.cached_input_tokens ?? "Неизвестно"}</dd>
                </div>
                <div>
                  <dt>Оценка стоимости</dt>
                  <dd>
                    {metadata.estimated_cost_usd === null
                      ? "Неизвестна"
                      : `$${fmt(metadata.estimated_cost_usd, 6)}`}
                    {metadata.usage_unknown
                      ? " · часть расхода неизвестна"
                      : ""}
                  </dd>
                </div>
              </dl>
              <small>
                Это учёт приложения, а не баланс аккаунта OpenAI. Отмена не
                обнуляет уже возникший расход.
              </small>
            </details>
          )}
        </>
      )}
    </div>
  );
}

export function AIExplanation({
  results,
  scenarioIds,
  provenance = "manual",
  constraints = null,
}: {
  results: SimulationResult[];
  scenarioIds?: string[];
  provenance?: "manual" | "algorithmic";
  constraints?: ConstraintState | null;
}) {
  const operation = results.length > 1 ? "compare" : "explain";
  const { run, busy, error, execute, cancel } = useAIRun();
  const [preparing, setPreparing] = useState(false);
  const [saveError, setSaveError] = useState("");
  const guard = useRef(false);
  const ids = useRef<string[] | undefined>(scenarioIds);
  async function explain() {
    if (guard.current || busy) return;
    guard.current = true;
    setPreparing(true);
    setSaveError("");
    try {
      if (!ids.current) {
        const rows = await Promise.all(
          results.map((result, index) =>
            api<SavedScenario>("scenarios", {
              name: `Сценарий ${String.fromCharCode(65 + index)}`,
              decisions: result.decisions,
              provenance,
              constraints,
              saved: false,
            }),
          ),
        );
        ids.current = rows.map((row) => row.scenario_id);
      }
      setPreparing(false);
      await execute({
        message:
          operation === "compare"
            ? "Объясни различия выбранных сценариев на основе расчётов."
            : "Объясни рассчитанный результат сценария, компромиссы и оставшиеся проблемы.",
        mode: "ai",
        operation,
        current_decisions: [],
        scenario_ids: ids.current,
        constraints,
      });
    } catch (e) {
      setSaveError(
        e instanceof Error ? e.message : "Не удалось подготовить сценарий.",
      );
    } finally {
      setPreparing(false);
      guard.current = false;
    }
  }
  return (
    <section className="explicit-ai">
      <div className="explicit-ai-head">
        <div>
          <h3>
            <Sparkles size={18} />
            Объяснение результатов
          </h3>
          <p>
            Модель получает готовые расчёты. Облачный запрос выполняется только
            по этой кнопке.
          </p>
        </div>
        <button
          className="button primary"
          onClick={explain}
          disabled={busy || preparing}
        >
          {preparing ? (
            <Spinner text="Подготавливаем…" />
          ) : (
            <>
              <Sparkles size={16} />
              Объяснить с помощью ИИ
            </>
          )}
        </button>
      </div>
      {saveError && <ErrorBox text={saveError} />}
      <RunFeedback run={run} busy={busy} error={error} onCancel={cancel} />
    </section>
  );
}
