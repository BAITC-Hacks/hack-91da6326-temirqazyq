"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  FlaskConical,
  GitCompareArrows,
  Info,
  Layers3,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-react";
import type {
  Comparison,
  Decision,
  District,
  InvalidResult,
  Measure,
  Priority,
  Scenario,
  SearchResult,
  SimulationResult,
  SavedScenario,
  SavedComparison,
} from "@/lib/types";
import { api, fmt, priorities, signed } from "@/lib/ui";
import { validationHint } from "@/lib/feedback";
import { ErrorBox, Spinner } from "./common";
import { CompareModal, ResultsModal } from "./results";

export default function ScenarioLab({
  districts,
  measures,
  current,
  onUse,
}: {
  districts: District[];
  measures: Measure[];
  current: SimulationResult | null;
  onUse: (decisions: Decision[]) => void;
}) {
  const [focus, setFocus] = useState("Нура");
  const [priority, setPriority] = useState<Priority>("balanced");
  const [budget, setBudget] = useState(100);
  const [reserve, setReserve] = useState(0);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [data, setData] = useState<SearchResult | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [validation, setValidation] = useState<string[]>([]);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareBusy, setCompareBusy] = useState(false);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [persistedCompareIds, setPersistedCompareIds] = useState<string[]>([]);
  const [compareNames, setCompareNames] = useState<[string, string]>(["", ""]);
  const [view, setView] = useState<Scenario | null>(null);
  const [submittedPriority, setSubmittedPriority] =
    useState<Priority>(priority);
  const searchController = useRef<AbortController | null>(null);
  const compareController = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      searchController.current?.abort();
      compareController.current?.abort();
    },
    [],
  );

  const currentScenario: Scenario | null =
    current?.decisions.length === 5
      ? {
          id: "current",
          name: "Ваш сценарий",
          decisions: current.decisions,
          result: current,
          objective_value: [],
        }
      : null;
  const scenarios = [
    ...(data?.scenarios ?? []),
    ...(currentScenario ? [currentScenario] : []),
  ];
  function nameOf(scenario: Scenario) {
    return scenario.id === "current"
      ? "Ваш сценарий"
      : `Сценарий ${String.fromCharCode(65 + (data?.scenarios.findIndex((s) => s.id === scenario.id) ?? 0))}`;
  }
  async function generate() {
    compareController.current?.abort();
    setCompareBusy(false);
    searchController.current?.abort();
    const controller = new AbortController();
    searchController.current = controller;
    setPending(true);
    setError("");
    setValidation([]);
    setCompareIds([]);
    setData(null);
    setSubmittedPriority(priority);
    try {
      const response = await api<SearchResult | InvalidResult>(
        "optimizer/search",
        {
          focus_district: focus || null,
          max_budget: budget,
          reserve_budget: reserve,
          exclude_measures: excluded,
          priority,
          limit: 3,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      if ("valid" in response && !response.valid) {
        setValidation(response.errors.map(validationHint));
      } else setData(response as SearchResult);
    } catch (e) {
      if (!controller.signal.aborted)
        setError(
          e instanceof Error ? e.message : "Не удалось завершить поиск.",
        );
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }
  async function compare() {
    const selected = compareIds
      .map((id) => scenarios.find((s) => s.id === id))
      .filter((s): s is Scenario => Boolean(s));
    if (selected.length !== 2) {
      setCompareIds([]);
      return;
    }
    compareController.current?.abort();
    const controller = new AbortController();
    compareController.current = controller;
    setCompareBusy(true);
    setError("");
    try {
      const rows = await Promise.all(
        selected.map((scenario) =>
          api<SavedScenario>(
            "scenarios",
            {
              name: nameOf(scenario),
              decisions: scenario.decisions,
              provenance: scenario.id === "current" ? "manual" : "algorithmic",
              constraints: null,
              saved: false,
            },
            controller.signal,
          ),
        ),
      );
      const response = await api<SavedComparison>(
        "scenarios/compare",
        { scenario_ids: rows.map((row) => row.scenario_id) },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setPersistedCompareIds(rows.map((row) => row.scenario_id));
      setCompareNames([nameOf(selected[0]), nameOf(selected[1])]);
      setComparison({
        scenario_a: response.scenarios[0].result,
        scenario_b: response.scenarios[1].result,
        category_comparison: response.category_comparison,
      });
    } catch (e) {
      if (!controller.signal.aborted)
        setError(
          e instanceof Error ? e.message : "Не удалось сравнить сценарии.",
        );
    } finally {
      if (!controller.signal.aborted) setCompareBusy(false);
    }
  }
  function toggleCompare(id: string) {
    compareController.current?.abort();
    setCompareBusy(false);
    setCompareIds((ids) =>
      ids.includes(id)
        ? ids.filter((i) => i !== id)
        : ids.length < 2
          ? [...ids, id]
          : [ids[1], id],
    );
  }

  return (
    <div className="lab-layout">
      <aside className="panel lab-controls">
        <div className="section-heading">
          <h3>
            <SlidersHorizontal size={17} /> Параметры поиска
          </h3>
        </div>
        <p className="muted small">
          Задайте приоритет. Алгоритм найдёт допустимые комбинации пяти решений.
        </p>
        <label className="field-label">
          Район в фокусе
          <select value={focus} onChange={(e) => setFocus(e.target.value)}>
            <option value="">Весь город</option>
            {districts.map((d) => (
              <option key={d.name}>{d.name}</option>
            ))}
          </select>
        </label>
        <label className="field-label">
          Приоритет развития
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value as Priority)}
          >
            {Object.entries(priorities).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div className="budget-inputs">
          <label className="field-label">
            Макс. бюджет
            <input
              type="number"
              min={0}
              max={100}
              value={budget}
              onChange={(e) =>
                setBudget(Math.max(0, Math.min(100, Number(e.target.value))))
              }
            />
          </label>
          <label className="field-label">
            Сохранить резерв
            <input
              type="number"
              min={0}
              max={100}
              value={reserve}
              onChange={(e) =>
                setReserve(Math.max(0, Math.min(100, Number(e.target.value))))
              }
            />
          </label>
        </div>
        <div className="effective-budget">
          <span>Доступно на решения</span>
          <strong>
            {Math.min(budget, 100 - reserve)} <small>ед.</small>
          </strong>
        </div>
        <label className="field-label">
          Исключить меры{" "}
          <span className="muted">
            {excluded.length} из {measures.length}
          </span>
        </label>
        <div className="exclude-list">
          {measures.map((m) => (
            <label key={m.id}>
              <input
                type="checkbox"
                checked={excluded.includes(m.id)}
                onChange={() =>
                  setExcluded((ids) =>
                    ids.includes(m.id)
                      ? ids.filter((id) => id !== m.id)
                      : [...ids, m.id],
                  )
                }
              />
              <span className="measure-id">{m.id}</span>
              <span>{m.name}</span>
            </label>
          ))}
        </div>
        <button
          className="button primary full-width"
          onClick={generate}
          disabled={pending}
        >
          {pending ? (
            <Spinner text="Исследуем сценарии…" />
          ) : (
            <>
              <Sparkles size={17} />
              Найти сценарии
              <ArrowRight size={16} />
            </>
          )}
        </button>
        <p className="footnote">
          <Info size={13} />
          Поиск ограничен по числу вариантов. Результаты — найденные
          альтернативы, без гарантии глобального оптимума.
        </p>
      </aside>
      <div className="lab-results">
        {error && <ErrorBox text={error} retry={generate} />}
        {validation.length > 0 && (
          <div className="validation-errors" role="alert">
            <div>
              {validation.map((message, i) => (
                <p key={i}>{message}</p>
              ))}
            </div>
          </div>
        )}
        {!data && !pending && (
          <section className="lab-empty">
            <div className="lab-orbit">
              <FlaskConical size={40} />
              <span className="orbit-dot one" />
              <span className="orbit-dot two" />
              <span className="orbit-dot three" />
            </div>
            <span className="eyebrow">ОТ ОГРАНИЧЕНИЙ К ВАРИАНТАМ</span>
            <h2>У города больше одного пути.</h2>
            <p>
              Исследуйте стратегии с разными приоритетами.
              <br />
              Сравните последствия и выберите свой сценарий.
            </p>
            <div className="lab-method">
              <span>
                <b>01</b> Ограничения
              </span>
              <ArrowRight size={16} />
              <span>
                <b>02</b> Расчёт
              </span>
              <ArrowRight size={16} />
              <span>
                <b>03</b> Решение
              </span>
            </div>
            <div className="lab-note">
              <Sparkles size={16} />
              <span>Движок считает показатели. ИИ объясняет результат.</span>
            </div>
          </section>
        )}
        {pending && (
          <section className="lab-empty">
            <div className="lab-orbit">
              <FlaskConical size={40} className="pulse" />
            </div>
            <h2>Ищем варианты развития</h2>
            <p>
              Проверяем бюджет, совместимость мер
              <br />и эффект для каждого района.
            </p>
            <Spinner text="Детерминированный перебор сценариев…" />
          </section>
        )}
        {data && (
          <>
            <div className="section-heading">
              <div>
                <h3>
                  Альтернативные стратегии{" "}
                  <span className="count-badge">{data.scenarios.length}</span>
                </h3>
                <p className="muted small">
                  {priorities[submittedPriority]} · проверено{" "}
                  {data.search.evaluated.toLocaleString("ru-RU")} вариантов ·{" "}
                  {(data.search.elapsed_ms / 1000).toFixed(1)} с
                </p>
              </div>
              <span className="outline-tag">
                <Layers3 size={13} />5 решений в каждом
              </span>
            </div>
            {data.scenarios.length === 0 ? (
              <div className="panel empty-state">
                <h3>С такими условиями сценарии не найдены</h3>
                <p>
                  Увеличьте бюджет, уменьшите резерв или разрешите больше
                  мероприятий.
                </p>
              </div>
            ) : (
              <div className="scenario-grid">
                {data.scenarios.map((scenario, index) => (
                  <ScenarioCard
                    key={scenario.id}
                    scenario={scenario}
                    index={index}
                    name={nameOf(scenario)}
                    measures={measures}
                    selected={compareIds.includes(scenario.id)}
                    onCompare={() => toggleCompare(scenario.id)}
                    onView={() => setView(scenario)}
                    onUse={() => onUse(scenario.decisions)}
                  />
                ))}
              </div>
            )}
            {data.search.truncated && (
              <p className="search-note">
                <Info size={14} />
                Поиск завершён по лимиту. Показаны найденные варианты для
                выбранного приоритета, а не доказанный глобальный оптимум.
              </p>
            )}
            {data.search.notes && (
              <div className="search-notes">
                {(Array.isArray(data.search.notes)
                  ? data.search.notes
                  : [data.search.notes]
                ).map((note, i) => (
                  <p key={i}>{note}</p>
                ))}
              </div>
            )}
          </>
        )}
        {data && currentScenario && (
          <div className="current-scenario panel">
            <div>
              <span className="eyebrow">ЦЕНТР УПРАВЛЕНИЯ</span>
              <h3>Добавить ваш сценарий к сравнению</h3>
              <p className="muted small">
                индекс {fmt(currentScenario.result.score.after)} · Бюджет{" "}
                {currentScenario.result.budget.spent} / 100
              </p>
            </div>
            <button
              className={`button ${compareIds.includes("current") ? "selected-button" : "secondary"}`}
              onClick={() => toggleCompare("current")}
              aria-pressed={compareIds.includes("current")}
            >
              {compareIds.includes("current") ? (
                <Check size={16} />
              ) : (
                <GitCompareArrows size={16} />
              )}
              Сравнить
            </button>
          </div>
        )}
        {compareIds.length > 0 && (
          <div className="compare-tray">
            <div>
              <GitCompareArrows size={20} />
              <span>
                Выбрано для сравнения <b>{compareIds.length} / 2</b>
              </span>
            </div>
            <div>
              <button
                className="icon-button"
                aria-label="Очистить сравнение"
                onClick={() => setCompareIds([])}
              >
                <X size={17} />
              </button>
              <button
                className="button primary"
                disabled={compareIds.length !== 2 || compareBusy}
                onClick={compare}
              >
                {compareBusy ? (
                  <Spinner />
                ) : (
                  <>
                    Сравнить сценарии
                    <ArrowRight size={16} />
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
      {view && (
        <ResultsModal
          result={view.result}
          measures={measures}
          title={nameOf(view)}
          provenance={view.id === "current" ? "manual" : "algorithmic"}
          onClose={() => setView(null)}
        />
      )}
      {comparison && (
        <CompareModal
          comparison={comparison}
          names={compareNames}
          scenarioIds={persistedCompareIds}
          measures={measures}
          onClose={() => setComparison(null)}
        />
      )}
    </div>
  );
}

function ScenarioCard({
  scenario,
  index,
  name,
  measures,
  selected,
  onCompare,
  onView,
  onUse,
}: {
  scenario: Scenario;
  index: number;
  name: string;
  measures: Measure[];
  selected: boolean;
  onCompare: () => void;
  onView: () => void;
  onUse: () => void;
}) {
  const result = scenario.result;
  return (
    <article
      className={`scenario-card panel ${selected ? "compare-selected" : ""}`}
    >
      <div className="scenario-card-top">
        <span className="scenario-letter">
          {String.fromCharCode(65 + index)}
        </span>
        <span className="outline-tag">{result.decisions.length} решений</span>
      </div>
      <h3>{name}</h3>
      <div className="scenario-score">
        <strong>{fmt(result.score.after)}</strong>
        <span>
          <ArrowUpRight size={15} />
          {signed(result.score.delta)}
        </span>
        <small>Качество жизни</small>
      </div>
      <div className="scenario-metrics">
        <div>
          <span>Бюджет</span>
          <b>{result.budget.spent} / 100</b>
        </div>
        <div>
          <span>Слабейший район</span>
          <b>{fmt(result.weakest_district.after.score)}</b>
        </div>
        <div>
          <span>Критические показатели</span>
          <b>{result.critical_after.length}</b>
        </div>
        <div>
          <span>Синергии</span>
          <b>{result.activated_synergies.length}</b>
        </div>
      </div>
      <div className="scenario-decisions">
        {scenario.decisions.map((d) => (
          <div key={d.measure_id}>
            <span className="measure-id">{d.measure_id}</span>
            <span title={measures.find((m) => m.id === d.measure_id)?.name}>
              {measures.find((m) => m.id === d.measure_id)?.name}
            </span>
            <small>{d.district || "Город"}</small>
          </div>
        ))}
      </div>
      <div className="scenario-actions">
        <button className="button secondary" onClick={onView}>
          Подробнее
          <ArrowUpRight size={15} />
        </button>
        <button
          className={`button ${selected ? "selected-button" : "secondary"}`}
          onClick={onCompare}
          aria-pressed={selected}
        >
          {selected ? <Check size={15} /> : <GitCompareArrows size={15} />}
          Сравнить
        </button>
      </div>
      <button className="button use-scenario" onClick={onUse}>
        Применить в Центр управления
        <ArrowRight size={15} />
      </button>
    </article>
  );
}
