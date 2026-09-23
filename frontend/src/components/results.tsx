"use client";

import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  CheckCircle2,
  Download,
  Sparkles,
  Zap,
} from "lucide-react";
import type {
  Advisor,
  Comparison,
  Measure,
  SimulationResult,
} from "@/lib/types";
import { api, categories, fmt, indicatorNames, keys, signed } from "@/lib/ui";
import { AdvisorContent, ErrorBox, Modal, Spinner } from "./common";
import { ComparisonChart } from "./charts";

export function ResultsModal({
  result,
  measures,
  title = "Будущее города в цифрах",
  onClose,
}: {
  result: SimulationResult;
  measures: Measure[];
  title?: string;
  onClose: () => void;
}) {
  const [advisor, setAdvisor] = useState<Advisor | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setAdvisor(null);
    api<Advisor>("ai/explain", result, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) setAdvisor(response);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [result, attempt]);
  function download() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "akim-ai-scenario.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }
  return (
    <Modal
      title={title}
      eyebrow="SCENARIO REPORT / 8 КВАРТАЛОВ"
      onClose={onClose}
      wide
    >
      <div className="report-hero">
        <div>
          <span className="report-label">QUALITY OF LIFE</span>
          <div className="report-score">
            <span>{fmt(result.score.before)}</span>
            <ArrowUpRight size={26} />
            <strong>{fmt(result.score.after)}</strong>
            <b>{signed(result.score.delta)}</b>
          </div>
          <p>Индекс качества жизни после пяти решений</p>
        </div>
        <div className="report-budget">
          <small>Использовано бюджета</small>
          <strong>
            {result.budget.spent} <span>/ {result.budget.total}</span>
          </strong>
          <small>Резерв: {result.budget.remaining} ед.</small>
        </div>
      </div>
      <div className="report-stat-grid">
        <div>
          <small>Слабейший район</small>
          <strong>{result.weakest_district.after.name}</strong>
          <span>
            {fmt(result.weakest_district.before.score)} →{" "}
            {fmt(result.weakest_district.after.score)}
          </span>
        </div>
        <div>
          <small>Критические показатели</small>
          <strong>
            {result.critical_before.length} → {result.critical_after.length}
          </strong>
          <span>Порог: строго ниже 40</span>
        </div>
        <div>
          <small>Средний индекс города</small>
          <strong>{fmt(result.average_score.after)}</strong>
          <span>С учётом долей населения</span>
        </div>
        <div>
          <small>Активные синергии</small>
          <strong>{result.activated_synergies.length}</strong>
          <span>Дополнительные эффекты решений</span>
        </div>
      </div>
      <div className="report-grid">
        <section className="panel">
          <h3>Каждый район имеет значение</h3>
          <p className="muted small">Индекс района до и после решений</p>
          <ComparisonChart
            data={Object.entries(result.districts).map(([name, d]) => ({
              name,
              before: d.score_before,
              after: d.score_after,
            }))}
          />
          <div className="report-district-values">
            {Object.entries(result.districts).map(([name, d]) => (
              <div key={name}>
                <span>{name}</span>
                <b>
                  {fmt(d.score_before)} → {fmt(d.score_after)}
                </b>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <h3>Вклад каждого решения</h3>
          <p className="muted small">Разница Score при исключении одной меры</p>
          <div className="contribution-list">
            {[...result.measure_contributions]
              .sort((a, b) => b.contribution - a.contribution)
              .map((c) => (
                <div key={c.measure_id}>
                  <div>
                    <span className="measure-id">{c.measure_id}</span>
                    <strong>
                      {measures.find((m) => m.id === c.measure_id)?.name ??
                        c.measure_id}
                    </strong>
                    <b>{signed(c.contribution)}</b>
                  </div>
                  <small>{c.district || "Весь город"}</small>
                  <div className="progress-track">
                    <i
                      style={{
                        width: `${Math.min(100, (Math.abs(c.contribution) / Math.max(...result.measure_contributions.map((m) => Math.abs(m.contribution)), 0.01)) * 100)}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
          </div>
          <p className="footnote">
            Вклады могут пересекаться из-за синергий и штрафов; их сумма не
            обязана равняться общему приросту.
          </p>
        </section>
      </div>
      <section className="panel city-indicators">
        <h3>10 показателей города</h3>
        <p className="muted small">
          Средние показатели, взвешенные по населению
        </p>
        <ComparisonChart
          data={Object.keys(indicatorNames).map((key) => ({
            name: key,
            before: result.city_indicators.before[key],
            after: result.city_indicators.after[key],
          }))}
        />
        <div className="city-indicator-legend">
          {Object.entries(indicatorNames).map(([key, name]) => (
            <div key={key}>
              <small>
                {key} · {name}
              </small>
              <b>
                {fmt(result.city_indicators.before[key])} →{" "}
                {fmt(result.city_indicators.after[key])}
              </b>
              <span
                className={
                  result.city_indicators.delta[key] < 0
                    ? "negative"
                    : "positive"
                }
              >
                {signed(result.city_indicators.delta[key])}
              </span>
            </div>
          ))}
        </div>
      </section>
      <div className="report-grid">
        <section className="panel">
          <h3>
            <Zap size={17} /> Активированные синергии
          </h3>
          {result.activated_synergies.length ? (
            result.activated_synergies.map((s, i) => (
              <div className="synergy-result" key={i}>
                <b>
                  {s.measure_ids.join(" + ")}
                  <span>{s.district}</span>
                </b>
                <p>
                  {Object.entries(s.effects)
                    .map(
                      ([key, value]) =>
                        `${indicatorNames[key]} ${signed(value, 0)}`,
                    )
                    .join(" · ")}
                </p>
              </div>
            ))
          ) : (
            <p className="muted small">
              В этом сценарии нет пар с дополнительным эффектом.
            </p>
          )}
        </section>
        <section className="panel">
          <h3>Оставшиеся критические показатели</h3>
          {result.critical_after.length ? (
            result.critical_after.map((c) => (
              <div
                className="critical-row"
                key={`${c.district}-${c.indicator}`}
              >
                <span>
                  {c.district} · {indicatorNames[c.indicator]}
                </span>
                <b>{fmt(c.value)}</b>
              </div>
            ))
          ) : (
            <div className="success-state">
              <CheckCircle2 size={22} />
              <span>Все показатели достигли порога 40.</span>
            </div>
          )}
        </section>
      </div>
      <section className="panel report-advisor">
        <h3>
          <Sparkles size={18} /> Объяснение советника
        </h3>
        {error ? (
          <ErrorBox text={error} retry={() => setAttempt((a) => a + 1)} />
        ) : advisor ? (
          <AdvisorContent advisor={advisor} />
        ) : (
          <Spinner text="Готовим объяснение результатов…" />
        )}
      </section>
      <div className="modal-actions">
        <p className="muted small">
          Условная модель Астаны. Показатели не являются реальной городской
          статистикой.
        </p>
        <button className="button secondary" onClick={download}>
          <Download size={16} />
          Скачать JSON
        </button>
      </div>
    </Modal>
  );
}

export function CompareModal({
  comparison,
  names,
  onClose,
}: {
  comparison: Comparison;
  names: [string, string];
  onClose: () => void;
}) {
  const a = comparison.scenario_a,
    b = comparison.scenario_b;
  const rows = [
    ["Бюджет", `${a.budget.spent} / 100`, `${b.budget.spent} / 100`],
    ["Резерв", String(a.budget.remaining), String(b.budget.remaining)],
    ["Quality of Life", fmt(a.score.after), fmt(b.score.after)],
    ["Прирост Score", signed(a.score.delta), signed(b.score.delta)],
    [
      "Слабейший район",
      `${a.weakest_district.after.name} · ${fmt(a.weakest_district.after.score)}`,
      `${b.weakest_district.after.name} · ${fmt(b.weakest_district.after.score)}`,
    ],
    [
      "Критические показатели",
      String(a.critical_after.length),
      String(b.critical_after.length),
    ],
    ...keys.map((k) => [
      `${categories[k].label} · прирост`,
      signed(a.category_deltas[k]),
      signed(b.category_deltas[k]),
    ]),
    [
      "Активные синергии",
      a.activated_synergies
        .map((s) => `${s.measure_ids.join(" + ")} (${s.district})`)
        .join("; ") || "Нет",
      b.activated_synergies
        .map((s) => `${s.measure_ids.join(" + ")} (${s.district})`)
        .join("; ") || "Нет",
    ],
  ];
  return (
    <Modal
      title="Два пути развития города"
      eyebrow="SCENARIO COMPARE"
      onClose={onClose}
      wide
    >
      <div className="compare-heading">
        <span>
          <i />A · {names[0]}
        </span>
        <span>
          <i />B · {names[1]}
        </span>
      </div>
      <div className="report-grid">
        <section className="panel">
          <h3>Изменения по направлениям</h3>
          <ComparisonChart
            data={comparison.category_comparison.map((c) => ({
              name: categories[c.category].label
                .replace("Социальная сфера", "Социум")
                .replace("Городские сервисы", "Сервисы"),
              before: c.scenario_a,
              after: c.scenario_b,
            }))}
            labels={["Сценарий A", "Сценарий B"]}
          />
        </section>
        <section className="panel">
          <h3>Качество жизни в районах</h3>
          <ComparisonChart
            data={Object.keys(a.districts).map((name) => ({
              name,
              before: a.districts[name].score_after,
              after: b.districts[name].score_after,
            }))}
            labels={["Сценарий A", "Сценарий B"]}
          />
        </section>
      </div>
      <div className="panel table-scroll">
        <table className="compare-table">
          <thead>
            <tr>
              <th>Показатель</th>
              <th>Сценарий A</th>
              <th>Сценарий B</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, av, bv]) => (
              <tr key={label}>
                <td>{label}</td>
                <td>{av}</td>
                <td>{bv}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <section className="panel report-advisor">
        <h3>
          <Sparkles size={18} /> Что меняется при выборе стратегии
        </h3>
        <AdvisorContent advisor={comparison.explanation} />
      </section>
    </Modal>
  );
}
