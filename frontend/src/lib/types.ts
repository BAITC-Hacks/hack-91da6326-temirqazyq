export type Category =
  "transport" | "ecology" | "social" | "safety" | "services";
export type Priority =
  | Category
  | "balanced"
  | "overall_score"
  | "weakest_district"
  | "reduce_critical";
export type Indicators = Record<string, number>;
export interface District {
  name: string;
  population_share: number;
  profile: string;
  indicators: Indicators;
}
export interface Measure {
  id: string;
  name: string;
  category: Category;
  type: "district" | "city";
  cost: number;
  lag: number;
  effects: Indicators;
}
export interface Decision {
  measure_id: string;
  district?: string;
}
export interface ValidationError {
  code: string;
  message: string;
}
export interface InvalidResult {
  valid: false;
  errors: ValidationError[];
}
export interface DistrictResult {
  score_before: number;
  score_after: number;
  indicators_before: Indicators;
  indicators_after: Indicators;
  indicator_deltas: Indicators;
  population_share: number;
  profile: string;
}
export interface Critical {
  district: string;
  indicator: string;
  value: number;
}
export interface Synergy {
  measure_ids: string[];
  district: string;
  effects: Indicators;
}
export interface SimulationResult {
  valid: true;
  decisions: Decision[];
  budget: { total: number; spent: number; remaining: number };
  score: { before: number; after: number; delta: number };
  districts: Record<string, DistrictResult>;
  critical_before: Critical[];
  critical_after: Critical[];
  activated_synergies: Synergy[];
  measure_contributions: {
    measure_id: string;
    district?: string;
    contribution: number;
  }[];
  city_indicators: { before: Indicators; after: Indicators; delta: Indicators };
  category_deltas: Record<Category, number>;
  weakest_district: {
    before: { name: string; score: number };
    after: { name: string; score: number };
  };
  average_score: { before: number; after: number };
  score_decomposition?: {
    average: number;
    weakest: number;
    critical: number;
    total: number;
  };
}
export interface Advisor {
  summary: string;
  strengths: string[];
  risks: string[];
  tradeoffs: string[];
  recommendations: string[];
  source: "template" | "openai";
}
export interface Scenario {
  id: string;
  name: string;
  decisions: Decision[];
  result: SimulationResult;
  objective_value: number[];
}
export interface SearchResult {
  scenarios: Scenario[];
  search: {
    evaluated: number;
    truncated: boolean;
    elapsed_ms: number;
    effective_budget: number;
    objective: string;
    notes: string[] | string;
  };
}
export interface Comparison {
  scenario_a: SimulationResult;
  scenario_b: SimulationResult;
  category_comparison: {
    category: Category;
    scenario_a: number;
    scenario_b: number;
  }[];
  explanation?: Advisor;
}

export interface ConstraintState {
  max_budget: number;
  reserve_budget: number;
  excluded_measure_ids: string[];
  locked_decisions: Decision[];
  focus_district: string | null;
  preferred_categories: Category[];
  allowed_districts: string[] | null;
  requested_scenario_count: number;
  analysis_indicators: string[];
}
export interface SavedScenario {
  scenario_id: string;
  name: string;
  decisions: Decision[];
  result: SimulationResult;
  provenance: "llm_generated" | "algorithmic" | "manual";
  constraints: ConstraintState | null;
  dataset_version: string;
  saved: boolean;
  created_at: string;
}
export interface Narrative {
  summary: string;
  observations: string[];
  remaining_issues: string[];
  tradeoffs: string[];
  limitations: string[];
  evidence_refs: string[];
  scenario_ids: string[];
  source: "openai" | "template";
}
export interface AIMetadata {
  provider: string;
  requested_model: string;
  actual_model: string | null;
  used_llm: boolean;
  fallback_used: boolean;
  cache_hit: boolean;
  api_calls: number;
  usage: {
    input_tokens: number;
    output_tokens: number;
    cached_input_tokens: number;
  } | null;
  usage_unknown: boolean;
  estimated_cost_usd: number | null;
}
export type RunStatus =
  | "queued"
  | "interpreting"
  | "generating"
  | "validating"
  | "repairing"
  | "explaining"
  | "completed"
  | "needs_clarification"
  | "failed"
  | "cancelled"
  | "interrupted";
export interface AIRun {
  run_id: string;
  status: RunStatus;
  stage: string;
  message: string;
  error: { code: string; message: string } | null;
  constraints: ConstraintState;
  scenarios: SavedScenario[];
  explanation: Narrative | null;
  metadata: AIMetadata;
  events: { stage: string; message: string }[];
  clarification: string | null;
}
export interface AIConfig {
  enabled: boolean;
  provider: string;
  model: string;
  key_configured: boolean;
  allow_template_fallback: boolean;
  limits: Record<string, number | boolean | string>;
}
export interface AISession {
  session_id: string;
  constraints: ConstraintState;
  history: { role: "user" | "assistant"; content: string; kind?: "error" }[];
  runs?: AIRun[];
}
export interface SavedComparison {
  scenarios: SavedScenario[];
  category_comparison: Comparison["category_comparison"];
}
export interface AppUsage {
  day: string;
  estimated_cost_usd: number | null;
  api_calls: number;
  reserved_cost_usd: number;
  usage_unknown: boolean;
  daily_limit_usd: number;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
}
