"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bookmark,
  Calculator,
  GitCompareArrows,
  Send,
  Sparkles,
} from "lucide-react";
import type {
  AIConfig,
  AISession,
  AppUsage,
  ConstraintState,
  Decision,
  District,
  Measure,
  SavedComparison,
  SavedScenario,
  SimulationResult,
} from "@/lib/types";
import { api, fmt } from "@/lib/ui";
import { isActiveRun, useAIRun } from "@/lib/use-ai-run";
import { actionUnavailable, publicAssistantText } from "@/lib/feedback";
import { ConstraintsView, RunFeedback } from "./ai-feedback";
import { ErrorBox, Spinner } from "./common";
import ScenarioLab from "./scenario-lab";
import ScenarioLibrary, { SavedScenarioCard } from "./scenario-library";
import { CompareModal, ResultsModal } from "./results";

const examplePrompt =
  "Покажи три допустимых варианта с бюджетом не больше 90. Не используй M3. Отдельно покажи изменения школ и поликлиник Нуры.";

export default function AIWorkspace({
  districts,
  measures,
  current,
  currentDecisions,
  onUse,
}: {
  districts: District[];
  measures: Measure[];
  current: SimulationResult | null;
  currentDecisions: Decision[];
  onUse: (decisions: Decision[]) => void;
}) {
  const [mode, setMode] = useState<"ai" | "algorithmic" | "library">("ai");
  const [session, setSession] = useState<AISession | null>(null);
  const [config, setConfig] = useState<AIConfig | null>(null);
  const [usage, setUsage] = useState<AppUsage | null>(null);
  const [loadError, setLoadError] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [message, setMessage] = useState("");
  const [localUserMessage, setLocalUserMessage] = useState("");
  const [scenarios, setScenarios] = useState<SavedScenario[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [view, setView] = useState<SavedScenario | null>(null);
  const [comparison, setComparison] = useState<SavedComparison | null>(null);
  const [compareBusy, setCompareBusy] = useState(false);
  const [compareError, setCompareError] = useState("");
  const [constraints, setConstraints] = useState<ConstraintState | null>(null);
  const { run, busy, error, execute, recover, cancel } = useAIRun();
  const completedRun = useRef("");
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reloadSession = useCallback(async () => {
    const next = await api<AISession>("sessions/current");
    if (mounted.current) {
      setSession(next);
      setLocalUserMessage("");
    }
  }, []);

  useEffect(() => {
    const refreshUsage = () => {
      void api<AppUsage>("ai/usage")
        .then((next) => {
          if (mounted.current) setUsage(next);
        })
        .catch(() => {});
    };
    window.addEventListener("akim-ai-run-completed", refreshUsage);
    return () =>
      window.removeEventListener("akim-ai-run-completed", refreshUsage);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoadError("");
    Promise.all([
      api<AISession>("sessions/current", undefined, controller.signal),
      api<AIConfig>("ai/config", undefined, controller.signal),
      api<AppUsage>("ai/usage", undefined, controller.signal),
    ])
      .then(([next, settings, totals]) => {
        if (controller.signal.aborted) return;
        setSession(next);
        setConstraints(next.constraints);
        setConfig(settings);
        setUsage(totals);
        const last =
          next.runs?.find((item) => isActiveRun(item)) || next.runs?.[0];
        if (last) {
          void recover(last);
          if (last.scenarios?.length) setScenarios(last.scenarios.slice(0, 3));
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setLoadError(e.message);
      });
    return () => controller.abort();
  }, [loadAttempt, recover]);

  useEffect(() => {
    if (!run) return;
    setConstraints(run.constraints);
    if (run.scenarios.length) setScenarios(run.scenarios.slice(0, 3));
    if (!isActiveRun(run) && completedRun.current !== run.run_id) {
      completedRun.current = run.run_id;
      void reloadSession().catch((e) => setLoadError(e.message));
      void api<AppUsage>("ai/usage")
        .then(setUsage)
        .catch(() => {});
    }
  }, [run, reloadSession]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const prompt = message.trim();
    if (!prompt || busy) return;
    setLocalUserMessage(prompt);
    setMessage("");
    setSelected([]);
    setScenarios([]);
    setCompareError("");
    await execute({
      message: prompt,
      mode: "ai",
      operation: null,
      current_decisions: currentDecisions,
      scenario_ids: selected,
      constraints,
    });
  }
  async function compare() {
    if (selected.length !== 2 || compareBusy) return;
    setCompareBusy(true);
    setCompareError("");
    try {
      const response = await api<SavedComparison>("scenarios/compare", {
        scenario_ids: selected,
      });
      if (mounted.current) setComparison(response);
    } catch (e) {
      if (mounted.current)
        setCompareError(
          e instanceof Error ? e.message : "Сравнение не выполнено.",
        );
    } finally {
      if (mounted.current) setCompareBusy(false);
    }
  }
  const aiAvailable = Boolean(
    config?.enabled &&
    (config.key_configured || config.allow_template_fallback),
  );
  return (
    <div className="workspace">
      <nav className="workspace-tabs" aria-label="Режим лаборатории">
        <button
          className={mode === "ai" ? "active" : ""}
          aria-pressed={mode === "ai"}
          onClick={() => setMode("ai")}
        >
          <Sparkles size={16} />
          ИИ-генерация
        </button>
        <button
          className={mode === "algorithmic" ? "active" : ""}
          aria-pressed={mode === "algorithmic"}
          onClick={() => setMode("algorithmic")}
        >
          <Calculator size={16} />
          Алгоритмический поиск
        </button>
        <button
          className={mode === "library" ? "active" : ""}
          aria-pressed={mode === "library"}
          onClick={() => setMode("library")}
        >
          <Bookmark size={16} />
          Сохранённые сценарии
        </button>
      </nav>
      <div hidden={mode !== "ai"} className="ai-lab-layout">
        <section className="panel ai-dialog">
          <div className="section-heading">
            <div>
              <h2>Опишите задачу для города</h2>
              <p className="muted">
                Модель предлагает варианты. Движок проверяет решения и считает
                показатели.
              </p>
            </div>
            <Sparkles size={22} />
          </div>
          {loadError && (
            <ErrorBox
              text={loadError}
              retry={() => setLoadAttempt((n) => n + 1)}
            />
          )}
          {config && (
            <div className="ai-config-status">
              <span
                className={`status-dot ${aiAvailable ? "connected" : ""}`}
              />
              <span>
                {config.enabled
                  ? `Настроена модель ${config.model}. Успешный вызов подтверждается отдельно.`
                  : "Облачный ИИ отключён. Ручной режим и алгоритмический поиск доступны."}
              </span>
            </div>
          )}
          <div className="conversation" aria-label="История диалога">
            {session?.history.length ? (
              session.history.map((entry, i) => (
                <article
                  className={`conversation-message ${entry.role}`}
                  key={i}
                >
                  <strong>{entry.role === "user" ? "Вы" : "Советник"}</strong>
                  <p>
                    {entry.role === "user"
                      ? entry.content
                      : entry.kind === "error"
                        ? actionUnavailable
                        : publicAssistantText(entry.content)}
                  </p>
                </article>
              ))
            ) : (
              <div className="conversation-empty">
                <Sparkles size={30} />
                <h3>Начните с того, что важно жителям</h3>
                <p>
                  Укажите бюджет, исключения и интересующие показатели.
                  Ограничения сохранятся в следующем сообщении.
                </p>
                <button type="button" onClick={() => setMessage(examplePrompt)}>
                  Подставить пример запроса
                </button>
              </div>
            )}
            {localUserMessage && (
              <article className="conversation-message user">
                <strong>Вы</strong>
                <p>{localUserMessage}</p>
              </article>
            )}
          </div>
          <form className="prompt-form" onSubmit={submit}>
            <label htmlFor="city-prompt">Ваш запрос или уточнение</label>
            <textarea
              id="city-prompt"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Например: сохрани минимум 20 единиц бюджета, остальные ограничения оставь."
              maxLength={2000}
              rows={4}
              disabled={busy}
            />
            <div className="prompt-actions">
              <small>
                {message.length} / 2000 · запрос может использовать API-кредиты
              </small>
              <button
                className="button primary"
                type="submit"
                disabled={busy || !message.trim() || !aiAvailable}
              >
                {busy ? (
                  <Spinner text="Выполняется…" />
                ) : (
                  <>
                    <Send size={15} />
                    Отправить запрос
                  </>
                )}
              </button>
            </div>
          </form>
          {config && !aiAvailable && (
            <p className="ai-unavailable">
              ИИ недоступен в текущих настройках. Переключитесь в
              алгоритмический поиск; скрытого вызова модели не будет.
            </p>
          )}
          <RunFeedback run={run} busy={busy} error={error} onCancel={cancel} />
        </section>
        <aside className="ai-context">
          {constraints && <ConstraintsView constraints={constraints} />}
          {usage && (
            <section className="panel usage-panel">
              <h3>Расходы приложения за день</h3>
              <p>{usage.day}</p>
              <dl>
                <div>
                  <dt>Вызовы API</dt>
                  <dd>{usage.api_calls}</dd>
                </div>
                <div>
                  <dt>Оценка расхода</dt>
                  <dd>
                    {usage.estimated_cost_usd === null
                      ? "Неизвестна"
                      : `$${fmt(usage.estimated_cost_usd, 4)}`}
                  </dd>
                </div>
                <div>
                  <dt>Зарезервировано на операции</dt>
                  <dd>${fmt(usage.reserved_cost_usd, 4)}</dd>
                </div>
                <div>
                  <dt>Лимит приложения</dt>
                  <dd>${fmt(usage.daily_limit_usd, 2)}</dd>
                </div>
                <div>
                  <dt>Входные / выходные токены</dt>
                  <dd>
                    {usage.input_tokens} / {usage.output_tokens}
                  </dd>
                </div>
                <div>
                  <dt>Входные токены из кеша</dt>
                  <dd>{usage.cached_input_tokens}</dd>
                </div>
              </dl>
              {usage.usage_unknown && (
                <p>
                  Часть расхода неизвестна: провайдер не вернул полные данные.
                </p>
              )}
              <small>Оценка этого приложения, не баланс аккаунта OpenAI.</small>
            </section>
          )}
        </aside>
        <section className="ai-scenario-results">
          {scenarios.length > 0 && (
            <>
              <div className="section-heading">
                <h2>Проверенные варианты</h2>
                <span>
                  {scenarios.length} из запрошенных{" "}
                  {constraints?.requested_scenario_count ?? 3}
                </span>
              </div>
              <div className="ai-scenario-grid">
                {scenarios.map((scenario, index) => (
                  <SavedScenarioCard
                    key={scenario.scenario_id}
                    scenario={scenario}
                    label={String.fromCharCode(65 + index)}
                    measures={measures}
                    selected={selected.includes(scenario.scenario_id)}
                    onCompare={() => {
                      if (!compareBusy)
                        setSelected((ids) =>
                          ids.includes(scenario.scenario_id)
                            ? ids.filter((id) => id !== scenario.scenario_id)
                            : [...ids.slice(-1), scenario.scenario_id],
                        );
                    }}
                    onView={() => setView(scenario)}
                    onUse={() => onUse(scenario.decisions)}
                    onSaved={(row) =>
                      setScenarios((values) =>
                        values.map((item) =>
                          item.scenario_id === row.scenario_id ? row : item,
                        ),
                      )
                    }
                  />
                ))}
              </div>
            </>
          )}
          {compareError && <ErrorBox text={compareError} />}
          {selected.length > 0 && (
            <div className="compare-tray">
              <span>
                <GitCompareArrows size={17} />
                Выбрано для сравнения {selected.length} из 2
              </span>
              <button
                className="button primary"
                disabled={selected.length !== 2 || compareBusy}
                onClick={compare}
              >
                {compareBusy ? <Spinner /> : "Сравнить выбранные"}
              </button>
            </div>
          )}
        </section>
      </div>
      <div hidden={mode !== "algorithmic"}>
        <ScenarioLab
          districts={districts}
          measures={measures}
          current={current}
          onUse={onUse}
        />
      </div>
      <div hidden={mode !== "library"}>
        <ScenarioLibrary
          measures={measures}
          onUse={onUse}
          active={mode === "library"}
        />
      </div>
      {view && (
        <ResultsModal
          result={view.result}
          measures={measures}
          scenario={view}
          title="Проверенный сценарий"
          onClose={() => setView(null)}
        />
      )}
      {comparison && (
        <CompareModal
          comparison={{
            scenario_a: comparison.scenarios[0].result,
            scenario_b: comparison.scenarios[1].result,
            category_comparison: comparison.category_comparison,
          }}
          names={["Сценарий A", "Сценарий B"]}
          scenarioIds={comparison.scenarios.map((s) => s.scenario_id)}
          measures={measures}
          onClose={() => setComparison(null)}
        />
      )}
    </div>
  );
}
