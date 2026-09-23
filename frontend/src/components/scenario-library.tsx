"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Bookmark,
  Check,
  Download,
  GitCompareArrows,
  Printer,
} from "lucide-react";
import type {
  Decision,
  Measure,
  SavedComparison,
  SavedScenario,
  SimulationResult,
} from "@/lib/types";
import { api, fmt, signed } from "@/lib/ui";
import { ErrorBox, Spinner } from "./common";
import { CompareModal, ResultsModal } from "./results";

export const provenanceLabels = {
  llm_generated: "Предложен моделью, проверен движком",
  algorithmic: "Алгоритмический поиск",
  manual: "Ручной сценарий",
};
export function notifyScenarioSaved() {
  window.dispatchEvent(new Event("akim-scenarios-saved"));
}

export function ScenarioActions({
  result,
  initialScenario,
  provenance = "manual",
  defaultName = "Мой сценарий",
}: {
  result: SimulationResult;
  initialScenario?: SavedScenario;
  provenance?: "manual" | "algorithmic";
  defaultName?: string;
}) {
  const [row, setRow] = useState<SavedScenario | undefined>(initialScenario);
  const [name, setName] = useState(initialScenario?.name || defaultName);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const guard = useRef(false);
  async function ensureRecord(saved: boolean) {
    if (row) {
      if (saved)
        return api<SavedScenario>(
          `scenarios/${encodeURIComponent(row.scenario_id)}/save`,
          { name: name.trim() || defaultName },
        );
      return row;
    }
    return api<SavedScenario>("scenarios", {
      name: name.trim() || defaultName,
      decisions: result.decisions,
      provenance,
      constraints: null,
      saved,
    });
  }
  async function perform(action: "save" | "export") {
    if (guard.current) return;
    guard.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await ensureRecord(action === "save");
      setRow(next);
      if (action === "save") notifyScenarioSaved();
      else {
        const payload = await api<unknown>(
          `scenarios/${encodeURIComponent(next.scenario_id)}/export`,
        );
        const url = URL.createObjectURL(
          new Blob([JSON.stringify(payload, null, 2)], {
            type: "application/json",
          }),
        );
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `akim-ai-${next.scenario_id}.json`;
        anchor.click();
        URL.revokeObjectURL(url);
      }
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Не удалось сохранить сценарий.",
      );
    } finally {
      guard.current = false;
      setBusy(false);
    }
  }
  return (
    <div className="scenario-persistence no-print">
      <label className="field-label">
        Название для сохранения
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={120}
        />
      </label>
      <div className="persistence-buttons">
        <button
          className="button primary"
          disabled={busy}
          onClick={() => perform("save")}
        >
          {busy ? (
            <Spinner text="Обработка…" />
          ) : (
            <>
              {row?.saved ? <Check size={16} /> : <Bookmark size={16} />}
              {row?.saved ? "Сохранить название" : "Сохранить сценарий"}
            </>
          )}
        </button>
        <button
          className="button secondary"
          onClick={() => perform("export")}
          disabled={busy}
        >
          <Download size={16} />
          Экспорт JSON
        </button>
        <button className="button secondary" onClick={() => window.print()}>
          <Printer size={16} />
          Печатный отчёт
        </button>
      </div>
      {row?.saved && (
        <p className="save-success" role="status">
          <Check size={14} />
          Сценарий сохранён в библиотеке этой сессии.
        </p>
      )}
      {error && <ErrorBox text={error} />}
    </div>
  );
}

export function SavedScenarioCard({
  scenario,
  label,
  measures,
  selected,
  onCompare,
  onView,
  onUse,
  onSaved,
}: {
  scenario: SavedScenario;
  label: string;
  measures: Measure[];
  selected: boolean;
  onCompare: () => void;
  onView: () => void;
  onUse: () => void;
  onSaved: (scenario: SavedScenario) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const savingRef = useRef(false);
  async function save() {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError("");
    try {
      const row = await api<SavedScenario>(
        `scenarios/${encodeURIComponent(scenario.scenario_id)}/save`,
        {},
      );
      onSaved(row);
      notifyScenarioSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Сохранение не выполнено.");
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }
  const result = scenario.result;
  return (
    <article
      className={`scenario-card panel ${selected ? "compare-selected" : ""}`}
    >
      <div className="scenario-card-top">
        <span className="scenario-letter">{label}</span>
        <span className="verified-tag">
          <Check size={13} />
          Проверен движком
        </span>
      </div>
      <h3>{`Сценарий ${label}`}</h3>
      <p className="scenario-origin">{provenanceLabels[scenario.provenance]}</p>
      <div className="scenario-score">
        <strong>{fmt(result.score.after)}</strong>
        <span>{signed(result.score.delta)}</span>
        <small>Индекс качества жизни</small>
      </div>
      <div className="scenario-metrics">
        <div>
          <span>Расход / резерв</span>
          <b>
            {result.budget.spent} / {result.budget.remaining}
          </b>
        </div>
        <div>
          <span>Критические показатели</span>
          <b>{result.critical_after.length}</b>
        </div>
        <div>
          <span>Слабейший район</span>
          <b>{result.weakest_district.after.name}</b>
        </div>
        <div>
          <span>Индекс слабейшего района</span>
          <b>{fmt(result.weakest_district.after.score)}</b>
        </div>
      </div>
      <div className="scenario-decisions">
        {scenario.decisions.map((d) => (
          <div key={d.measure_id}>
            <span className="measure-id">{d.measure_id}</span>
            <span>
              {measures.find((m) => m.id === d.measure_id)?.name ||
                d.measure_id}
            </span>
            <small>{d.district || "Весь город"}</small>
          </div>
        ))}
      </div>
      {scenario.constraints?.focus_district && (
        <div className="focus-analysis">
          <b>{scenario.constraints.focus_district}: выбранные показатели</b>
          {(scenario.constraints.analysis_indicators.length
            ? scenario.constraints.analysis_indicators
            : ["S1", "S2"]
          ).map((key) => {
            const district =
              result.districts[scenario.constraints!.focus_district!];
            if (!district || !(key in district.indicators_after)) return null;
            return (
              <div key={key}>
                <span>{key}</span>
                <b>
                  {fmt(district.indicators_before[key])} →{" "}
                  {fmt(district.indicators_after[key])}
                </b>
              </div>
            );
          })}
        </div>
      )}
      <div className="scenario-actions">
        <button className="button secondary" onClick={onView}>
          Подробнее
        </button>
        <button
          className={`button ${selected ? "selected-button" : "secondary"}`}
          onClick={onCompare}
          aria-pressed={selected}
        >
          <GitCompareArrows size={15} />
          Сравнить
        </button>
      </div>
      <button className="button use-scenario" onClick={onUse}>
        Применить в центре управления
        <ArrowRight size={15} />
      </button>
      <button
        className="button secondary full-width"
        disabled={saving || scenario.saved}
        onClick={save}
      >
        {saving ? (
          <Spinner text="Сохранение…" />
        ) : (
          <>
            <Bookmark size={15} />
            {scenario.saved ? "Сохранён" : "Сохранить"}
          </>
        )}
      </button>
      {error && <ErrorBox text={error} />}
    </article>
  );
}

export default function ScenarioLibrary({
  measures,
  onUse,
  active,
}: {
  measures: Measure[];
  onUse: (decisions: Decision[]) => void;
  active: boolean;
}) {
  const [rows, setRows] = useState<SavedScenario[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [view, setView] = useState<SavedScenario | null>(null);
  const [comparison, setComparison] = useState<SavedComparison | null>(null);
  const [comparing, setComparing] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    setLoading(true);
    setError("");
    try {
      const response = await api<SavedScenario[]>(
        "scenarios?saved_only=true",
        undefined,
        next.signal,
      );
      if (!next.signal.aborted) setRows(response);
    } catch (e) {
      if (!next.signal.aborted)
        setError(
          e instanceof Error ? e.message : "Не удалось загрузить библиотеку.",
        );
    } finally {
      if (!next.signal.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => {
    if (active) void refresh();
    const handler = () => {
      if (active) void refresh();
    };
    window.addEventListener("akim-scenarios-saved", handler);
    return () => {
      controller.current?.abort();
      window.removeEventListener("akim-scenarios-saved", handler);
    };
  }, [active, refresh]);
  async function compare() {
    if (selected.length !== 2 || comparing) return;
    setComparing(true);
    setError("");
    try {
      setComparison(
        await api<SavedComparison>("scenarios/compare", {
          scenario_ids: selected,
        }),
      );
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Не удалось сравнить сценарии.",
      );
    } finally {
      setComparing(false);
    }
  }
  async function openScenario(row: SavedScenario) {
    setError("");
    try {
      setView(
        await api<SavedScenario>(
          `scenarios/${encodeURIComponent(row.scenario_id)}`,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось открыть сценарий.");
    }
  }
  return (
    <section className="saved-library">
      <div className="section-heading">
        <div>
          <h2>Библиотека сценариев</h2>
          <p className="muted">
            Сценарии сохраняются на сервере и доступны в этой сессии после
            перезапуска.
          </p>
        </div>
        <button
          className="button secondary"
          onClick={refresh}
          disabled={loading}
        >
          Обновить
        </button>
      </div>
      {error && <ErrorBox text={error} retry={refresh} />}
      {loading && <Spinner text="Загружаем сохранённые сценарии…" />}
      {!loading && !rows.length && (
        <div className="panel empty-state">
          <Bookmark size={28} />
          <h3>Пока нет сохранённых сценариев</h3>
          <p>
            Откройте результат ручного сценария или сохраните проверенный
            вариант из лаборатории.
          </p>
        </div>
      )}
      <div className="saved-grid">
        {rows.map((row) => (
          <article className="panel saved-row" key={row.scenario_id}>
            <div>
              <span className="scenario-origin">
                {provenanceLabels[row.provenance]}
              </span>
              <h3>{row.name}</h3>
              <p>
                Индекс {fmt(row.result.score.after)} · бюджет{" "}
                {row.result.budget.spent} · резерв {row.result.budget.remaining}
              </p>
              <small>
                Данные: {row.dataset_version} ·{" "}
                {new Date(row.created_at).toLocaleString("ru-RU")}
              </small>
            </div>
            <div className="saved-row-actions">
              <button
                className="button secondary"
                onClick={() => openScenario(row)}
              >
                Открыть
              </button>
              <button
                className={`button ${selected.includes(row.scenario_id) ? "selected-button" : "secondary"}`}
                aria-pressed={selected.includes(row.scenario_id)}
                disabled={comparing}
                onClick={() =>
                  setSelected((ids) =>
                    ids.includes(row.scenario_id)
                      ? ids.filter((id) => id !== row.scenario_id)
                      : [...ids.slice(-1), row.scenario_id],
                  )
                }
              >
                <GitCompareArrows size={15} />
                Сравнить
              </button>
              <button
                className="button primary"
                onClick={() => onUse(row.decisions)}
              >
                Применить
              </button>
            </div>
          </article>
        ))}
      </div>
      {selected.length > 0 && (
        <div className="compare-tray">
          <span>Выбрано {selected.length} из 2</span>
          <button
            className="button primary"
            disabled={selected.length !== 2 || comparing}
            onClick={compare}
          >
            {comparing ? <Spinner /> : "Сравнить выбранные"}
          </button>
        </div>
      )}
      {view && (
        <ResultsModal
          result={view.result}
          measures={measures}
          scenario={view}
          title={view.name}
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
          names={[comparison.scenarios[0].name, comparison.scenarios[1].name]}
          scenarioIds={comparison.scenarios.map((s) => s.scenario_id)}
          measures={measures}
          onClose={() => setComparison(null)}
        />
      )}
    </section>
  );
}
