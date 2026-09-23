"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Building2,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  Coins,
  FlaskConical,
  Globe2,
  Info,
  LayoutDashboard,
  MapPin,
  Plus,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Target,
  TriangleAlert,
  Users,
  Wallet,
  X,
  Zap,
} from "lucide-react";
import type {
  Category,
  Decision,
  District,
  InvalidResult,
  Measure,
  SimulationResult,
  ValidationError,
} from "@/lib/types";
import { api, categories, fmt, indicatorNames, keys, signed } from "@/lib/ui";
import { DistrictRadar } from "./charts";
import { ErrorBox, Modal, Spinner } from "./common";
import { ResultsModal } from "./results";
import ScenarioLab from "./scenario-lab";

const demoDecisions: Decision[] = [
  { measure_id: "M7", district: "Нура" },
  { measure_id: "M8", district: "Нура" },
  { measure_id: "M10", district: "Нура" },
  { measure_id: "M12" },
  { measure_id: "M5", district: "Сарыарка" },
];
const synergyPairs = [
  { ids: ["M1", "M2"], effect: "Разгрузка дорог +2", indicator: "T1" },
  { ids: ["M10", "M12"], effect: "Безопасность улиц +2", indicator: "B1" },
  { ids: ["M5", "M6"], effect: "Качество воздуха +2", indicator: "E2" },
];

export default function Dashboard() {
  const [tab, setTab] = useState<"command" | "lab">("command");
  const [districts, setDistricts] = useState<District[]>([]);
  const [measures, setMeasures] = useState<Measure[]>([]);
  const [base, setBase] = useState<SimulationResult | null>(null);
  const [loadError, setLoadError] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [selectedDistrict, setSelectedDistrict] = useState("Нура");
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [preview, setPreview] = useState<SimulationResult | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewErrors, setPreviewErrors] = useState<ValidationError[]>([]);
  const [previewError, setPreviewError] = useState("");
  const [previewAttempt, setPreviewAttempt] = useState(0);
  const [finalBusy, setFinalBusy] = useState(false);
  const [finalResult, setFinalResult] = useState<SimulationResult | null>(null);
  const [filter, setFilter] = useState<Category | "all">("all");
  const [districtChoices, setDistrictChoices] = useState<
    Record<string, string>
  >({});
  const [toast, setToast] = useState("");
  const [showInfo, setShowInfo] = useState(false);
  const catalog = useRef<HTMLElement>(null);
  const finalController = useRef<AbortController | null>(null);
  useEffect(() => () => finalController.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoadError("");
    Promise.all([
      api<District[]>("districts", undefined, controller.signal),
      api<Measure[]>("measures", undefined, controller.signal),
      api<SimulationResult>("base-state", undefined, controller.signal),
    ])
      .then(([ds, ms, bs]) => {
        if (controller.signal.aborted) return;
        setDistricts(ds);
        setMeasures(ms);
        setBase(bs);
        setPreview(bs);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setLoadError(e.message);
      });
    return () => controller.abort();
  }, [loadAttempt]);

  useEffect(() => {
    if (!base) return;
    const controller = new AbortController();
    setPreviewErrors([]);
    setPreviewError("");
    if (!decisions.length) {
      setPreview(base);
      setPreviewBusy(false);
      return;
    }
    setPreview(null);
    setPreviewBusy(true);
    const timer = window.setTimeout(() => {
      api<SimulationResult | InvalidResult>(
        "scenario/preview",
        { decisions },
        controller.signal,
      )
        .then((response) => {
          if (controller.signal.aborted) return;
          if (response.valid) setPreview(response);
          else {
            setPreviewErrors(response.errors);
            setPreview(null);
          }
        })
        .catch((e) => {
          if (!controller.signal.aborted) setPreviewError(e.message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setPreviewBusy(false);
        });
    }, 120);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [decisions, base, previewAttempt]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 6000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const spent = decisions.reduce(
    (total, d) =>
      total + (measures.find((m) => m.id === d.measure_id)?.cost ?? 0),
    0,
  );
  const displayed = preview ?? base;
  const district = displayed?.districts[selectedDistrict];
  const districtInfo = districts.find((d) => d.name === selectedDistrict);

  function updateDecisions(next: Decision[]) {
    finalController.current?.abort();
    setFinalBusy(false);
    setPreview(null);
    setPreviewBusy(next.length > 0);
    setPreviewErrors([]);
    setPreviewError("");
    setDecisions(next);
  }
  function reasonFor(measure: Measure, target: string) {
    if (decisions.some((d) => d.measure_id === measure.id))
      return "Мероприятие уже включено в ваш план.";
    if (decisions.length >= 5)
      return "В плане уже пять решений. Удалите одно, чтобы добавить это.";
    if (spent + measure.cost > 100)
      return `Недостаточно бюджета: нужно ${measure.cost}, доступно ${100 - spent} ед.`;
    if (
      decisions.filter(
        (d) =>
          measures.find((m) => m.id === d.measure_id)?.category ===
          measure.category,
      ).length >= 2
    )
      return "В одном направлении можно выбрать максимум два мероприятия.";
    if (
      (measure.id === "M1" && decisions.some((d) => d.measure_id === "M3")) ||
      (measure.id === "M3" && decisions.some((d) => d.measure_id === "M1"))
    )
      return "M1 и M3 несовместимы: автобусные полосы и ЛРТ нельзя включать в один сценарий.";
    const localPairs = [
      ["M4", "M7"],
      ["M5", "M13"],
    ];
    for (const pair of localPairs)
      if (
        pair.includes(measure.id) &&
        decisions.some(
          (d) => pair.includes(d.measure_id) && d.district === target,
        )
      )
        return `${pair.join(" и ")} нельзя размещать в одном районе. Выберите другой район.`;
    return "";
  }
  function addDecision(measure: Measure) {
    const target = districtChoices[measure.id] || selectedDistrict;
    const reason = reasonFor(measure, target);
    if (reason) {
      setToast(reason);
      return;
    }
    updateDecisions([
      ...decisions,
      {
        measure_id: measure.id,
        ...(measure.type === "district" ? { district: target } : {}),
      },
    ]);
  }
  async function finalize() {
    finalController.current?.abort();
    const controller = new AbortController();
    finalController.current = controller;
    setFinalBusy(true);
    setToast("");
    try {
      const response = await api<SimulationResult | InvalidResult>(
        "scenario/simulate",
        { decisions },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      if (response.valid) setFinalResult(response);
      else {
        setPreview(null);
        setPreviewErrors(response.errors);
      }
    } catch (e) {
      if (!controller.signal.aborted)
        setToast(
          e instanceof Error ? e.message : "Не удалось рассчитать сценарий.",
        );
    } finally {
      if (!controller.signal.aborted) setFinalBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a href="/" className="brand-mark" aria-label="Akim AI — главная">
          <Building2 size={25} />
        </a>
        <div className="sidebar-nav">
          <button
            className={tab === "command" ? "active" : ""}
            aria-pressed={tab === "command"}
            onClick={() => setTab("command")}
            aria-label="Command Center"
            title="Command Center"
          >
            <LayoutDashboard size={21} />
            <span>Центр</span>
          </button>
          <button
            className={tab === "lab" ? "active" : ""}
            aria-pressed={tab === "lab"}
            onClick={() => setTab("lab")}
            aria-label="Scenario Lab"
            title="Scenario Lab"
          >
            <FlaskConical size={22} />
            <span>Lab</span>
          </button>
        </div>
        <div className="sidebar-bottom">
          <button
            onClick={() => setShowInfo(true)}
            aria-label="О модели"
            title="О модели"
          >
            <CircleHelp size={21} />
          </button>
          <div className="avatar" title="Городской стратег">
            АК
          </div>
        </div>
      </aside>
      <div className="app-content">
        <header className="topbar">
          <div className="wordmark">
            <span>
              ASTANA<span className="wordmark-dot">.</span>
            </span>
            <small>AI CITY COMMAND CENTER</small>
          </div>
          <div className="header-status">
            <span className={`status-dot ${base ? "connected" : ""}`} />
            {base ? "Симуляция активна" : "Подключение к модели"}
            <span className="header-divider" />
            <Clock3 size={14} />
            <span>Горизонт: 8 кварталов</span>
          </div>
          <button className="header-help" onClick={() => setShowInfo(true)}>
            <Info size={16} />
            <span>О проекте</span>
          </button>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="breadcrumb">
                <span>Рабочее пространство</span>
                <ChevronRight size={12} />
                <b>
                  {tab === "command"
                    ? "Центр управления"
                    : "Лаборатория сценариев"}
                </b>
              </div>
              <h1>
                {tab === "command"
                  ? "Пять решений. Один город."
                  : "Исследуйте будущее города."}
              </h1>
              <p>
                {tab === "command"
                  ? "Примите роль акима. Распределите ресурсы и измените жизнь районов."
                  : "Задайте цель, сравните стратегии и найдите свой баланс развития."}
              </p>
            </div>
            <div className="heading-actions">
              <span className="demo-badge">
                <span />
                HACKATHON EDITION
              </span>
              {tab === "command" && (
                <button
                  className="button secondary"
                  disabled={!base}
                  onClick={() => {
                    updateDecisions(demoDecisions);
                    setSelectedDistrict("Нура");
                    setToast(
                      "Демо-сценарий загружен: пять решений, включая синергию M10 + M12.",
                    );
                  }}
                >
                  <Sparkles size={15} />
                  Демо-сценарий
                </button>
              )}
            </div>
          </div>
          <nav className="main-tabs" aria-label="Режим работы">
            <button
              className={tab === "command" ? "active" : ""}
              aria-pressed={tab === "command"}
              onClick={() => setTab("command")}
            >
              <LayoutDashboard size={16} />
              Command Center<span>01</span>
            </button>
            <button
              className={tab === "lab" ? "active" : ""}
              aria-pressed={tab === "lab"}
              onClick={() => setTab("lab")}
            >
              <FlaskConical size={17} />
              Scenario Lab<span>02</span>
            </button>
            <span className="tabs-note">
              <ShieldCheck size={14} />
              Прозрачные расчёты · понятные решения
            </span>
          </nav>
          {!base ? (
            <div className="initial-loading panel">
              {loadError ? (
                <ErrorBox
                  text={loadError}
                  retry={() => setLoadAttempt((n) => n + 1)}
                />
              ) : (
                <>
                  <Spinner text="Подключаем городскую модель…" />
                  <p className="muted">
                    Загружаем районы, мероприятия и исходные показатели.
                  </p>
                </>
              )}
            </div>
          ) : (
            <>
              <div hidden={tab !== "command"}>
                <div className="metric-grid">
                  <section className="metric-card score-metric">
                    <div className="metric-title">
                      <span>QUALITY OF LIFE</span>
                      <Activity size={16} />
                    </div>
                    <div className="metric-main">
                      <strong aria-live="polite">
                        {preview
                          ? fmt(preview.score.after)
                          : previewBusy
                            ? "…"
                            : "—"}
                      </strong>
                      {preview && (
                        <span className="delta-badge">
                          <ArrowUpRight size={14} />
                          {signed(preview.score.delta)}
                        </span>
                      )}
                    </div>
                    <div className="metric-footer">
                      <span>
                        Базовый Score <b>{fmt(base.score.before)}</b>
                      </span>
                      <span>из 100</span>
                    </div>
                    <div className="score-spark">
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                    </div>
                  </section>
                  <section className="metric-card">
                    <div className="metric-title">
                      <span>ГОРОДСКОЙ БЮДЖЕТ</span>
                      <Wallet size={16} />
                    </div>
                    <div className="metric-main">
                      <strong>{100 - spent}</strong>
                      <span className="metric-unit">ед. в резерве</span>
                    </div>
                    <div className="progress-track budget-track">
                      <i style={{ width: `${Math.min(100, spent)}%` }} />
                    </div>
                    <div className="metric-footer">
                      <span>
                        Использовано <b>{spent}</b>
                      </span>
                      <span>Лимит 100</span>
                    </div>
                  </section>
                  <section className="metric-card">
                    <div className="metric-title">
                      <span>ВАШИ РЕШЕНИЯ</span>
                      <Target size={16} />
                    </div>
                    <div className="metric-main">
                      <strong>
                        {decisions.length}
                        <span className="metric-fraction"> / 5</span>
                      </strong>
                      <span className="metric-unit">
                        {decisions.length === 5
                          ? "план собран"
                          : "шагов к переменам"}
                      </span>
                    </div>
                    <div className="decision-dots">
                      {Array.from({ length: 5 }, (_, i) => (
                        <span
                          key={i}
                          className={i < decisions.length ? "filled" : ""}
                        >
                          {i < decisions.length ? <Check size={12} /> : i + 1}
                        </span>
                      ))}
                    </div>
                  </section>
                  <section className="metric-card critical-metric">
                    <div className="metric-title">
                      <span>ТОЧКИ ВНИМАНИЯ</span>
                      <TriangleAlert size={16} />
                    </div>
                    <div className="metric-main">
                      <strong>
                        {preview ? preview.critical_after.length : "—"}
                      </strong>
                      <span className="metric-unit">
                        критических
                        <br />
                        показателей
                      </span>
                    </div>
                    <div className="metric-footer">
                      <span>
                        До решений <b>{base.critical_before.length}</b>
                      </span>
                      <span className="warning-text">Порог &lt; 40</span>
                    </div>
                  </section>
                </div>
                {previewErrors.length > 0 && (
                  <div className="validation-errors" role="alert">
                    <TriangleAlert size={18} />
                    <div>
                      <strong>Сценарий недопустим — Score не рассчитан</strong>
                      {previewErrors.map((e, i) => (
                        <p key={`${e.code}-${i}`}>
                          {e.message} <code>{e.code}</code>
                        </p>
                      ))}
                      <small>
                        Ниже отображены исходные показатели районов.
                      </small>
                    </div>
                  </div>
                )}
                {previewError && (
                  <ErrorBox
                    text={previewError}
                    retry={() => setPreviewAttempt((n) => n + 1)}
                  />
                )}
                <div className="command-grid">
                  <section className="district-list">
                    <div className="section-heading">
                      <h2>Районы города</h2>
                      <span className="count-badge">{districts.length}</span>
                    </div>
                    <p className="section-subtitle">
                      Выберите район для анализа
                    </p>
                    {districts.map((d, i) => {
                      const values = displayed!.districts[d.name];
                      const criticalCount = Object.values(
                        values.indicators_after,
                      ).filter((v) => v < 40).length;
                      return (
                        <button
                          className={`district-card ${selectedDistrict === d.name ? "selected" : ""}`}
                          key={d.name}
                          onClick={() => setSelectedDistrict(d.name)}
                          aria-pressed={selectedDistrict === d.name}
                        >
                          <div className="district-card-main">
                            <span className={`district-symbol symbol-${i}`}>
                              <Building2 size={19} />
                            </span>
                            <div>
                              <strong>{d.name}</strong>
                              <small>
                                {Math.round(d.population_share * 100)}%
                                населения
                              </small>
                            </div>
                            <b>{fmt(values.score_after, 1)}</b>
                          </div>
                          <div className="district-card-bottom">
                            <div className="mini-bars">
                              {keys.map((k) => (
                                <span
                                  key={k}
                                  style={{
                                    height: `${Math.max(15, (values.indicators_after[categories[k].indicators[0]] + values.indicators_after[categories[k].indicators[1]]) / 2)}%`,
                                    backgroundColor:
                                      selectedDistrict === d.name
                                        ? "#169b83"
                                        : categories[k].color,
                                  }}
                                />
                              ))}
                            </div>
                            {criticalCount > 0 ? (
                              <span className="critical-badge">
                                <TriangleAlert size={10} />
                                {criticalCount} критических
                              </span>
                            ) : (
                              <span className="district-stable">
                                {values.score_after > values.score_before ? (
                                  <>
                                    <ArrowUpRight size={12} />
                                    {signed(
                                      values.score_after - values.score_before,
                                    )}
                                  </>
                                ) : (
                                  "Стабильно"
                                )}
                              </span>
                            )}
                            <ChevronRight size={14} />
                          </div>
                        </button>
                      );
                    })}
                    <div className="city-note">
                      <MapPin size={15} />
                      <div>
                        <strong>Астана, Казахстан</strong>
                        <p>
                          Условная модель города
                          <br />5 районов · 10 показателей
                        </p>
                      </div>
                    </div>
                  </section>
                  <section className="panel district-detail">
                    {district && (
                      <>
                        <div className="district-detail-head">
                          <div>
                            <span className="eyebrow">
                              <MapPin size={11} />
                              РАЙОН В ФОКУСЕ
                            </span>
                            <h2>
                              {selectedDistrict}
                              <span className="outline-tag">
                                {Math.round(
                                  (districtInfo?.population_share ?? 0) * 100,
                                )}
                                % жителей
                              </span>
                            </h2>
                          </div>
                          <span className="detail-index">
                            <small>ИНДЕКС РАЙОНА</small>
                            <b>{fmt(district.score_after)}</b>
                            {district.score_after !== district.score_before && (
                              <em>
                                {signed(
                                  district.score_after - district.score_before,
                                )}
                              </em>
                            )}
                          </span>
                        </div>
                        <p className="district-profile">
                          {districtInfo?.profile}
                        </p>
                        <div className="district-analysis">
                          <div>
                            <DistrictRadar district={district} />
                            <div className="chart-legend">
                              <span>
                                <i />
                                Исходный уровень
                              </span>
                              <span>
                                <i />
                                {decisions.length
                                  ? "После решений"
                                  : "Текущий уровень"}
                              </span>
                            </div>
                          </div>
                          <div className="district-summary">
                            <div className="summary-icon">
                              <Target size={20} />
                            </div>
                            <h3>
                              {district.indicators_after.S1 < 40 ||
                              district.indicators_after.S2 < 40
                                ? "Инфраструктура для жизни"
                                : "Сбалансированное развитие"}
                            </h3>
                            <p>
                              {Object.values(district.indicators_after).some(
                                (v) => v < 40,
                              )
                                ? "Показатели ниже 40 снижают итоговый Score города. Начните с уязвимых направлений."
                                : "Все показатели выше критического порога. Сравнивайте направления, чтобы распределить ресурсы."}
                            </p>
                            <div className="district-summary-bottom">
                              <Users size={13} />
                              <span>Эффект на жителей района</span>
                            </div>
                          </div>
                        </div>
                        <div className="indicators-title">
                          <h3>Пульс района</h3>
                          <span>
                            {previewBusy ? (
                              <Spinner text="Пересчёт" />
                            ) : preview ? (
                              "Шкала 0–100 · больше = лучше"
                            ) : (
                              "Исходные значения"
                            )}
                          </span>
                        </div>
                        <div className="indicator-grid">
                          {keys.map((category) => {
                            const config = categories[category];
                            return (
                              <div
                                key={category}
                                className="indicator-category"
                              >
                                {config.indicators.map((key) => {
                                  const value = district.indicators_after[key],
                                    before = district.indicators_before[key],
                                    delta = district.indicator_deltas[key];
                                  return (
                                    <div
                                      className={`indicator ${value < 40 ? "is-critical" : ""}`}
                                      key={key}
                                    >
                                      <div className="indicator-label">
                                        <span
                                          className="indicator-code"
                                          style={{ color: config.color }}
                                        >
                                          {key}
                                        </span>
                                        <span>{indicatorNames[key]}</span>
                                        {value < 40 && (
                                          <TriangleAlert size={11} />
                                        )}
                                        <b>
                                          {delta !== 0 && (
                                            <small>{fmt(before, 0)} → </small>
                                          )}
                                          {fmt(value, value % 1 === 0 ? 0 : 1)}
                                        </b>
                                      </div>
                                      <div className="indicator-track">
                                        <i
                                          style={{
                                            width: `${value}%`,
                                            backgroundColor:
                                              value < 40
                                                ? "#d78d43"
                                                : config.color,
                                          }}
                                        />
                                        <span style={{ left: "40%" }} />
                                      </div>
                                      {delta !== 0 && (
                                        <small
                                          className={`indicator-delta ${delta < 0 ? "negative" : "positive"}`}
                                        >
                                          {signed(delta)} к исходному
                                        </small>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            );
                          })}
                        </div>
                        <div className="district-footnote">
                          <Info size={12} />
                          <span>
                            Пунктир на шкале — критический порог 40. Эффекты
                            учтены на горизонте 8 кварталов.
                          </span>
                        </div>
                      </>
                    )}
                  </section>
                  <aside className="decision-column">
                    <section className="panel decision-tray">
                      <div className="section-heading">
                        <h2>Ваш план</h2>
                        <span className="plan-count">
                          {decisions.length}
                          <small> / 5</small>
                        </span>
                      </div>
                      <p className="section-subtitle">
                        Пять решений, которые меняют город
                      </p>
                      <div className="decision-slots">
                        {Array.from({ length: 5 }, (_, i) => {
                          const decision = decisions[i];
                          const measure =
                            decision &&
                            measures.find((m) => m.id === decision.measure_id);
                          return (
                            <div
                              key={decision?.measure_id || `empty-${i}`}
                              className={`decision-slot ${decision ? "occupied" : "empty"}`}
                            >
                              <span className="slot-number">
                                {i + 1 < 10 ? `0${i + 1}` : i + 1}
                              </span>
                              {decision && measure ? (
                                <>
                                  <div>
                                    <strong>{measure.name}</strong>
                                    <small>
                                      {decision.district || "Весь город"}
                                      <span>·</span>
                                      {measure.cost} ед.
                                    </small>
                                  </div>
                                  <button
                                    className="remove-decision"
                                    aria-label={`Удалить ${measure.id}`}
                                    onClick={() =>
                                      updateDecisions(
                                        decisions.filter(
                                          (d) => d.measure_id !== measure.id,
                                        ),
                                      )
                                    }
                                  >
                                    <X size={14} />
                                  </button>
                                </>
                              ) : (
                                <button
                                  onClick={() =>
                                    catalog.current?.scrollIntoView({
                                      behavior: "smooth",
                                      block: "start",
                                    })
                                  }
                                >
                                  <span>Добавьте решение</span>
                                  <Plus size={13} />
                                </button>
                              )}
                            </div>
                          );
                        })}
                      </div>
                      <div className="tray-budget">
                        <div>
                          <span>Бюджет плана</span>
                          <b>
                            {spent} <small>/ 100</small>
                          </b>
                        </div>
                        <div className="progress-track">
                          <i style={{ width: `${Math.min(spent, 100)}%` }} />
                        </div>
                        <div>
                          <span>Остаток</span>
                          <strong>{100 - spent} ед.</strong>
                        </div>
                      </div>
                      <button
                        className="button primary full-width"
                        disabled={
                          decisions.length !== 5 ||
                          previewBusy ||
                          !preview ||
                          finalBusy
                        }
                        onClick={finalize}
                      >
                        {finalBusy ? (
                          <Spinner />
                        ) : (
                          <>
                            <BarChart3 size={16} />
                            Результат сценария
                            <ArrowRight size={16} />
                          </>
                        )}
                      </button>
                      <div className="tray-footer">
                        <span>
                          {decisions.length < 5
                            ? `Добавьте ещё ${5 - decisions.length} ${5 - decisions.length === 1 ? "решение" : "решения"}`
                            : "Все решения выбраны"}
                        </span>
                        <button
                          disabled={!decisions.length}
                          onClick={() => updateDecisions([])}
                        >
                          <RotateCcw size={11} />
                          Сбросить
                        </button>
                      </div>
                    </section>
                    <section className="advisor-card">
                      <div className="advisor-header">
                        <span>
                          <Sparkles size={17} />
                          Советник
                        </span>
                        <span className="tiny-pill">INSIGHTS</span>
                      </div>
                      <h3>
                        {preview && preview.critical_after.length === 0
                          ? "Критические точки закрыты"
                          : "Начните с самого уязвимого"}
                      </h3>
                      <p>
                        {preview ? (
                          <>
                            Слабейший район —{" "}
                            <b>{preview.weakest_district.after.name}</b>, индекс{" "}
                            <b>{fmt(preview.weakest_district.after.score)}</b>.{" "}
                            {preview.critical_after.length
                              ? "Улучшение критических показателей влияет и на район, и на итоговый Score."
                              : "Теперь оцените баланс направлений и оставшийся бюджет."}
                          </>
                        ) : (
                          "Дождитесь расчёта допустимого сценария, чтобы увидеть изменения."
                        )}
                      </p>
                      {preview && (
                        <div className="weakest-change">
                          <span>Слабейший район</span>
                          <b>
                            {fmt(base.weakest_district.before.score)}
                            <ArrowRight size={12} />
                            {fmt(preview.weakest_district.after.score)}
                          </b>
                        </div>
                      )}
                      <button onClick={() => setTab("lab")}>
                        Исследовать альтернативы
                        <ArrowUpRight size={15} />
                      </button>
                      <small>
                        Расчёты — модель. Объяснение — AI или шаблон.
                      </small>
                    </section>
                  </aside>
                </div>
                {synergyPairs.some((pair) =>
                  pair.ids.some((id) =>
                    decisions.some((d) => d.measure_id === id),
                  ),
                ) && (
                  <div className="synergy-strip">
                    {synergyPairs
                      .filter((pair) =>
                        pair.ids.some((id) =>
                          decisions.some((d) => d.measure_id === id),
                        ),
                      )
                      .map((pair) => {
                        const activated = pair.ids.every((id) =>
                          decisions.some((d) => d.measure_id === id),
                        );
                        const missing = pair.ids.find(
                          (id) => !decisions.some((d) => d.measure_id === id),
                        );
                        return (
                          <div
                            key={pair.indicator}
                            className={activated && preview ? "active" : ""}
                          >
                            <Zap size={16} />
                            <div>
                              <b>
                                {activated && preview
                                  ? "Синергия активирована"
                                  : activated
                                    ? "Синергия ожидает проверки"
                                    : `Доступна синергия с ${missing}`}
                              </b>
                              <span>
                                {pair.ids.join(" + ")} · {pair.effect} в районе
                                локальной меры
                              </span>
                            </div>
                            {activated && preview && <Check size={16} />}
                          </div>
                        );
                      })}
                  </div>
                )}
                <section className="catalog" ref={catalog}>
                  <div className="section-heading catalog-heading">
                    <div>
                      <div className="eyebrow">TOOLS FOR CHANGE</div>
                      <h2>
                        Решения для города{" "}
                        <span className="count-badge">{measures.length}</span>
                      </h2>
                      <p className="muted">
                        Выберите, во что инвестировать следующие два года.
                      </p>
                    </div>
                    <span className="catalog-help">
                      <Info size={14} />
                      Не более 2 мер в одном направлении
                    </span>
                  </div>
                  <div
                    className="category-filters"
                    role="group"
                    aria-label="Категория мероприятий"
                  >
                    <button
                      onClick={() => setFilter("all")}
                      className={filter === "all" ? "active" : ""}
                      aria-pressed={filter === "all"}
                    >
                      <Globe2 size={14} />
                      Все решения<span>{measures.length}</span>
                    </button>
                    {keys.map((k) => {
                      const Icon = categories[k].icon;
                      return (
                        <button
                          key={k}
                          onClick={() => setFilter(k)}
                          className={filter === k ? "active" : ""}
                          aria-pressed={filter === k}
                        >
                          <Icon size={15} />
                          {categories[k].label}
                        </button>
                      );
                    })}
                  </div>
                  <div className="measure-grid">
                    {measures
                      .filter((m) => filter === "all" || m.category === filter)
                      .map((measure) => {
                        const config = categories[measure.category],
                          Icon = config.icon,
                          selected = decisions.some(
                            (d) => d.measure_id === measure.id,
                          ),
                          target =
                            decisions.find((d) => d.measure_id === measure.id)
                              ?.district ||
                            districtChoices[measure.id] ||
                            selectedDistrict,
                          reason = reasonFor(measure, target);
                        return (
                          <article
                            key={measure.id}
                            className={`measure-card ${selected ? "measure-selected" : ""}`}
                          >
                            <div className="measure-card-head">
                              <span
                                className="category-icon"
                                style={{
                                  backgroundColor: config.light,
                                  color: config.color,
                                }}
                              >
                                <Icon size={19} />
                              </span>
                              <span
                                className="category-label"
                                style={{ color: config.color }}
                              >
                                {config.label}
                              </span>
                              <span className="measure-id">{measure.id}</span>
                            </div>
                            <h3>{measure.name}</h3>
                            <div className="measure-meta">
                              <span>
                                <Coins size={13} />
                                <b>{measure.cost}</b> ед.
                              </span>
                              <span>
                                <Clock3 size={13} />
                                Лаг {measure.lag} кв.
                              </span>
                              <span>
                                {measure.type === "city" ? (
                                  <Globe2 size={12} />
                                ) : (
                                  <MapPin size={12} />
                                )}
                                {measure.type === "city" ? "Город" : "Район"}
                              </span>
                            </div>
                            <div className="measure-effects">
                              {Object.entries(measure.effects).map(
                                ([key, value]) => (
                                  <span
                                    key={key}
                                    className={
                                      value < 0 ? "negative-effect" : ""
                                    }
                                    title={`${indicatorNames[key]}: фактический эффект ${signed((value * (8 - measure.lag)) / 8)}`}
                                  >
                                    <b>{key}</b>
                                    {signed(value, 0)}
                                  </span>
                                ),
                              )}
                              <small>полный эффект</small>
                            </div>
                            <div className="measure-divider" />
                            {measure.type === "district" ? (
                              <label className="measure-district-label">
                                <MapPin size={13} />
                                <select
                                  aria-label={`Район для ${measure.id}`}
                                  value={target}
                                  onChange={(e) =>
                                    setDistrictChoices((ds) => ({
                                      ...ds,
                                      [measure.id]: e.target.value,
                                    }))
                                  }
                                  disabled={selected}
                                >
                                  {districts.map((d) => (
                                    <option key={d.name}>{d.name}</option>
                                  ))}
                                </select>
                              </label>
                            ) : (
                              <div className="city-measure-label">
                                <Globe2 size={13} />
                                Эффект во всех пяти районах
                              </div>
                            )}
                            <button
                              className={`button measure-add ${selected ? "added" : ""}`}
                              onClick={() => addDecision(measure)}
                              disabled={Boolean(reason)}
                              aria-describedby={
                                reason && !selected
                                  ? `reason-${measure.id}`
                                  : undefined
                              }
                            >
                              {selected ? (
                                <>
                                  <Check size={15} />В вашем плане
                                </>
                              ) : (
                                <>
                                  <Plus size={15} />
                                  Добавить решение
                                  <ArrowUpRight size={14} />
                                </>
                              )}
                            </button>
                            {reason && !selected && (
                              <p
                                className="conflict-reason"
                                id={`reason-${measure.id}`}
                              >
                                {reason}
                              </p>
                            )}
                          </article>
                        );
                      })}
                  </div>
                </section>
              </div>
              <div hidden={tab !== "lab"}>
                <ScenarioLab
                  districts={districts}
                  measures={measures}
                  current={preview}
                  onUse={(next) => {
                    updateDecisions(next);
                    setTab("command");
                    window.scrollTo({ top: 0, behavior: "smooth" });
                    setToast(
                      "Сценарий применён. Вы можете изменить решения или открыть итоговый отчёт.",
                    );
                  }}
                />
              </div>
            </>
          )}
          <footer className="page-footer">
            <span>
              <Building2 size={14} />
              <b>AKIM AI</b> · Аким на 5 часов
            </span>
            <span>Учебная симуляция · Условные данные Астаны</span>
            <button onClick={() => setShowInfo(true)}>
              Как устроена модель
              <ArrowUpRight size={12} />
            </button>
          </footer>
        </main>
      </div>
      {toast && (
        <div className="toast" role="status">
          <Info size={18} />
          <span>{toast}</span>
          <button aria-label="Закрыть уведомление" onClick={() => setToast("")}>
            <X size={16} />
          </button>
        </div>
      )}
      {finalResult && (
        <ResultsModal
          result={finalResult}
          measures={measures}
          onClose={() => setFinalResult(null)}
        />
      )}
      {showInfo && (
        <Modal
          title="Аким на 5 часов"
          eyebrow="О ГОРОДСКОЙ МОДЕЛИ"
          onClose={() => setShowInfo(false)}
        >
          <div className="about-content">
            <div className="about-icon">
              <Building2 size={32} />
            </div>
            <h3>Пять решений. Измеримые последствия.</h3>
            <p>
              Распределите 100 условных единиц между пятью мерами и оцените
              изменения в пяти районах Астаны через восемь кварталов.
            </p>
            <h4>Как считается качество жизни</h4>
            <div className="formula">
              Score = 0,7 × средний индекс
              <br />+ 0,3 × индекс слабейшего района
              <br />− число критических показателей
            </div>
            <p>
              Индекс района — взвешенная сумма десяти показателей. Городское
              среднее учитывает доли населения. Значение строго ниже 40
              считается критическим.
            </p>
            <h4>Меры, сроки и синергии</h4>
            <p>
              Фактический эффект = полный эффект × (8 − лаг) / 8. Синергии
              прибавляются полностью. Любой показатель ограничен диапазоном
              0–100.
            </p>
            <h4>Роль AI</h4>
            <p>
              Все числа и допустимость сценария рассчитывает детерминированный
              движок. Советник объясняет готовый результат; без API-ключа
              работает шаблонное объяснение. Scenario Lab использует
              ограниченный перебор с отсечениями.
            </p>
            <div className="about-disclaimer">
              <Info size={17} />
              <span>
                Это учебный симулятор с условными данными, не прогноз и не
                официальная статистика Астаны.
              </span>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
