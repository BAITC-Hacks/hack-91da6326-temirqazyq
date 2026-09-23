// Типы и клиент к FastAPI. Все числа приходят с бэкенда — фронт ничего не считает.

export type Decision = { measure_id: string; district_id: string | null }

export type Measure = {
  id: string; direction: string; name: string; scope: 'district' | 'city'; cost: number; lag: number; effects: Record<string, number>
}
export type District = { id: string; name: string; population_share: number; profile: string; indicators: Record<string, number> }
export type Indicator = { code: string; direction: string; name: string; weight: number; meaning: string }

export type Meta = {
  rules: { budget: number; decisions_required: number; max_per_direction: number; horizon_quarters: number; critical_threshold: number; formula: string }
  directions: Record<string, string>
  indicators: Indicator[]
  districts: District[]
  measures: Measure[]
  synergies: { first: string; second: string; indicator: string; bonus: number; note: string }[]
  incompatibilities: { a: string; b: string; scope: string; reason: string }[]
  events: { id: string; title: string }[]
  base_score: number
  llm: { provider: string; model: string | null; enabled: boolean }
}

export type ValidationResult = {
  valid: boolean; issues: { rule: string; message: string }[]; total_cost: number; budget: number; remaining: number; per_direction: Record<string, number>
}

export type IndicatorTrace = {
  code: string; base: number; final: number; delta: number; critical_before: boolean; critical_after: boolean
  contributions: { measure_id: string; district_id: string | null; raw: number; realized: number; kind: string }[]
}
export type DistrictTrace = { district_id: string; name: string; population_share: number; score_before: number; score_after: number; indicators: IndicatorTrace[] }
export type MeasureContribution = { measure_id: string; district_id: string | null; name: string; cost: number; lag: number; realized_share: number; marginal_score: number; solo_score: number }

export type ScoreResult = {
  score: number; base_score: number; delta: number; d_avg: number; d_min: number; d_min_district: string; n_crit: number; critical_cells: string[]
  base_d_avg: number; base_d_min: number; base_n_crit: number; total_cost: number; budget: number; remaining: number
  districts: DistrictTrace[]; measures: MeasureContribution[]
  synergies: { first: string; second: string; district_id: string; indicator: string; bonus: number; note: string }[]
  directions: { direction: string; name: string; before: number; after: number }[]
}

export type World = { event_id: string | null; budget: number; blocked_measures: string[]; baseline: Record<string, Record<string, number>> }
export type ScoreOut = { validation: ValidationResult; result: ScoreResult | null; world: World }

export type Analysis = {
  analyst?: { headline: string; summary: string; strengths: string[]; risks: string[]; tradeoffs: string[]; resident_voice?: { district: string; quote: string }; _mode: string; _error?: string }
  critic?: { verdict: string; weaknesses: { title: string; detail: string; severity: string }[]; questions_to_team: string[]; _mode: string }
  advisor?: { recommendations: { title: string; change: string; decisions: Decision[]; new_score: number; gain: number; cost: number; rationale: string; verified?: boolean; invalid_reason?: string }[]; keep_as_is_argument: string; tool_calls: { name: string; arguments: unknown }[]; _mode: string }
  oracle?: { best_score: number; gap_to_best: number; percentile: number; n_valid_sets: number; best_set: string[]; best_swaps: { replace: string; with: string; new_score: number; gain: number; cost: number }[] }
  llm: Meta['llm']
}

export type Council = {
  speeches: { persona_id: string; persona: string; score: number; statement: string; demand: string }[]
  moderator: { consensus: string; conflict: string; verdict: string }
  personas: { id: string; name: string; stance: string }[]
  _mode: string
}

export type EventOut = {
  event: { id: string; title: string; narrative: string; shocks: { district: string; indicator: string; delta: number }[]; blocked_measures: string[]; budget_delta: number }
  world: World; score_before: number | null; score_after_if_unchanged: number; base_score_after: number; plan_still_valid: boolean
  validation: ValidationResult; narration: { briefing: string; impact_summary: string; advice: string[]; _mode: string }
}

export type Oracle = {
  n_valid: number; best_score: number; best: Decision[]
  top: { score: number; cost: number; decisions: Decision[] }[]
  pareto: { cost: number; score: number; decisions: Decision[] }[]
  histogram: { from: number; to: number; count: number }[]
}

export type Entry = { id: number; team: string; event_id: string | null; decisions: Decision[]; score: number; delta: number; total_cost: number; n_crit: number; d_min: number; note: string; created_at: string; rank?: number }

export type Compare = {
  a: { score: number; cost: number; n_crit: number; d_min: number; d_avg: number }
  b: { score: number; cost: number; n_crit: number; d_min: number; d_avg: number }
  score_diff: number; only_a: Decision[]; only_b: Decision[]
  per_district: { district_id: string; name: string; a: number; b: number; diff: number }[]
  per_indicator: { district: string; code: string; a: number; b: number; diff: number }[]
  directions: { name: string; a: number; b: number }[]
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!r.ok) {
    let detail: unknown = r.statusText
    try { detail = (await r.json()).detail } catch { /* ignore */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return r.json()
}
const post = <T,>(path: string, body: unknown) => req<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  meta: () => req<Meta>('/api/meta'),
  validate: (decisions: Decision[], event_id: string | null) => post<ValidationResult>('/api/validate', { decisions, event_id }),
  score: (decisions: Decision[], event_id: string | null) => post<ScoreOut>('/api/score', { decisions, event_id }),
  analyze: (decisions: Decision[], event_id: string | null) => post<Analysis>('/api/analyze', { decisions, event_id }),
  council: (decisions: Decision[], event_id: string | null) => post<Council>('/api/council', { decisions, event_id }),
  oracle: (event_id: string | null) => req<Oracle>(`/api/oracle${event_id ? `?event_id=${event_id}` : ''}`),
  triggerEvent: (decisions: Decision[], event_id: string | null, trigger_event_id: string | null, exclude: string[]) =>
    post<EventOut>('/api/event/trigger', { decisions, event_id, trigger_event_id, exclude }),
  submit: (team: string, decisions: Decision[], event_id: string | null, analysis: Analysis | null, note: string) =>
    post<Entry>('/api/leaderboard', { team, decisions, event_id, analysis, note }),
  leaderboard: () => req<Entry[]>('/api/leaderboard'),
  entry: (id: number) => req<Entry & { result: ScoreResult }>(`/api/leaderboard/${id}`),
  compare: (a: { decisions: Decision[]; event_id: string | null }, b: { decisions: Decision[]; event_id: string | null }) => post<Compare>('/api/compare', { a, b }),
  reportUrl: (id: number) => `/api/report/${id}`,
}
