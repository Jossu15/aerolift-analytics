export interface Well {
  id: number;
  tag: string;
  well_type: string;
  p_wh: number;
  t_res_f: number;
  tvd_ft: number;
  tubing_id_in: number;
  gamma_g: number;
  q_water_bpd: number;
  q_gas_nominal_mscfd: number;
  load_method: string;
  vlp_model: string;
  ipr?: { kind: string; params: Record<string, number> };
}

export interface LoadingResult {
  well_id: number;
  status: "stable" | "at_risk" | "loaded" | "metastable";
  severity: "green" | "yellow" | "orange" | "red";
  v_actual_fts: number;
  v_crit_fts: number;
  margin_pct: number;
  q_crit_mscfd: number;
  method: string;
  metastable_regime: boolean;
  q_min_stable_mscfd: number | null;
  film_reynolds: number | null;
  recommendation?: string;
}

export interface ForecastResult {
  well_id: number;
  history: ForecastRow[];
  predicted_death_day: number | null;
  days_to_risk: number | null;
  status: string;
}

export interface ForecastRow {
  day: number;
  Gp: number;
  Pr: number;
  q_mscfd: number;
  Pwf: number | null;
  is_loading: boolean;
  status: string;
}

export interface ApiKeyInfo {
  id: number;
  label: string;
  tier: string;
  active: boolean;
  owner_id: string;
}

export interface WellsListResponse {
  wells: Well[];
  total: number;
}

export interface Alert {
  well_id: number;
  tag: string;
  severity: "green" | "yellow" | "orange" | "red";
  status: string;
  message: string;
  margin_pct: number;
  days_to_risk: number | null;
}
