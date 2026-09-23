"use client";

import type { ConstraintState, District, Measure } from "@/lib/types";
import { categories } from "@/lib/ui";

export const defaultConditions: ConstraintState = {
  max_budget: 100,
  reserve_budget: 0,
  excluded_measure_ids: [],
  locked_decisions: [],
  focus_district: null,
  preferred_categories: [],
  allowed_districts: null,
  requested_scenario_count: 3,
  analysis_indicators: [],
};

export function ConditionsForm({ value, districts, measures, disabled, onChange }: {
  value: ConstraintState;
  districts: District[];
  measures: Measure[];
  disabled: boolean;
  onChange: (next: ConstraintState) => void;
}) {
  const change = (patch: Partial<ConstraintState>) => onChange({ ...value, ...patch });
  const available = Math.min(100, value.max_budget, 100 - value.reserve_budget);
  return (
    <fieldset className="ux-condition-form" disabled={disabled}>
      <legend>Условия для следующего запроса</legend>
      <div className="ux-condition-grid">
        <label className="field-label">Максимальный бюджет
          <input type="number" min={0} max={100} step={1} value={value.max_budget} onChange={(e) => change({ max_budget: Math.max(0, Math.min(100, Number(e.target.value))) })} />
        </label>
        <label className="field-label">Оставить в резерве
          <input type="number" min={0} max={100} step={1} value={value.reserve_budget} onChange={(e) => change({ reserve_budget: Math.max(0, Math.min(100, Number(e.target.value))) })} />
        </label>
      </div>
      <p className="ux-condition-summary" role="status">Доступно на решения: <strong>{available} условных единиц</strong>. Резерв остаётся от общего бюджета 100; на решения выделяется не больше указанного максимума.</p>
      <label className="field-label">Интересующий район
        <select value={value.focus_district || ""} onChange={(e) => change({ focus_district: e.target.value || null })}>
          <option value="">Весь город</option>
          {districts.map((district) => <option key={district.name}>{district.name}</option>)}
        </select>
      </label>
      <p className="muted">Это пожелание для анализа. Инициативы в других районах остаются разрешены.</p>
      <fieldset className="ux-condition-group">
        <legend>Направления для анализа</legend>
        {Object.entries(categories).map(([key, category]) => {
          const checked = category.indicators.every((indicator) => value.analysis_indicators.includes(indicator));
          return <label key={key}><input type="checkbox" checked={checked} onChange={() => change({ analysis_indicators: checked ? value.analysis_indicators.filter((id) => !category.indicators.includes(id)) : [...new Set([...value.analysis_indicators, ...category.indicators])] })} />{category.label}</label>;
        })}
        <small>Если ничего не выбрано, рассмотрим все направления.</small>
      </fieldset>
      <fieldset className="ux-condition-group">
        <legend>Не включать в план</legend>
        {measures.map((measure) => <label key={measure.id}><input type="checkbox" checked={value.excluded_measure_ids.includes(measure.id)} onChange={() => change({ excluded_measure_ids: value.excluded_measure_ids.includes(measure.id) ? value.excluded_measure_ids.filter((id) => id !== measure.id) : [...value.excluded_measure_ids, measure.id] })} />{measure.name}</label>)}
      </fieldset>
      {value.locked_decisions.length > 0 && <fieldset className="ux-condition-group"><legend>Обязательно сохранить</legend>{value.locked_decisions.map((decision) => <label key={decision.measure_id}><input type="checkbox" checked onChange={() => change({ locked_decisions: value.locked_decisions.filter((item) => item !== decision) })} />{measures.find((measure) => measure.id === decision.measure_id)?.name || "Инициатива из текущего плана"} · {decision.district || "Весь город"}</label>)}</fieldset>}
      {value.allowed_districts !== null && <fieldset className="ux-condition-group"><legend>Районы, в которых разрешены инициативы</legend>{districts.map((district) => <label key={district.name}><input type="checkbox" checked={value.allowed_districts?.includes(district.name)} onChange={() => change({ allowed_districts: value.allowed_districts?.includes(district.name) ? value.allowed_districts.filter((name) => name !== district.name) : [...(value.allowed_districts || []), district.name] })} />{district.name}</label>)}<button type="button" className="button secondary" onClick={() => change({ allowed_districts: null })}>Разрешить все районы</button></fieldset>}
      <p className="muted">Изменение условий не запускает помощника. Нажмите «Подготовить варианты», когда будете готовы.</p>
    </fieldset>
  );
}
