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
  explanation: Advisor;
}
