export interface Well {
  id: number;
  tag: string;
  name?: string | null;
  well_type: string;
  p_res: number;
  t_res_f: number;
  t_wh_f: number;
  p_wh: number;
  tvd_ft: number;
  tubing_id_in: number;
  gamma_g: number;
  q_water_bpd: number;
  liquid_sg: number;
  q_gas_nominal_mscfd: number;
  load_method: string;
  vlp_model: string;
  friction_multiplier: number;
}

export interface LoadingResult {
  is_loading: boolean;
  margin_pct: number | null;
  severity: string; // stable | at_risk | mild | moderate | severe
  headline: string;
  first_action: string | null;
  bhfp_psia: number | null;
  v_actual_ft_s: number;
  v_crit_ft_s: number;
  q_crit_mscfd: number;
  metastable_regime: string; // stable | metastable | loaded
  q_min_stable_mscfd: number | null;
  film_reynolds: number | null;
}

export interface ForecastRow {
  day: number;
  Gp: number;
  Pr: number;
  q_mscfd: number;
  Pwf: number | null;
  status: string;
}

export interface ForecastResult {
  ogip_mmscf: number;
  pi_over_zi_psia: number;
  mb_slope: number;
  days_to_risk: number | null;
  history: ForecastRow[];
  preview: boolean;
  note: string | null;
}

export interface ChartFigure {
  data: unknown[];
  layout: Record<string, unknown>;
}

export interface ChartsResult {
  well_id: number;
  operating_envelope: ChartFigure;
  vcrit_vs_pressure: ChartFigure;
  vcrit_vs_temperature: ChartFigure;
  vcrit_vs_diameter: ChartFigure;
}

export interface ApiKeyInfo {
  id: number;
  label: string;
  tier: string;
  active: boolean;
  owner_id: string;
}

export interface Alert {
  well_id: number;
  tag: string;
  severity: "green" | "yellow" | "orange" | "red";
  status: string; // stable | at_risk | metastable | loaded
  message: string;
  margin_pct: number | null;
  days_to_risk: number | null;
  v_actual_ft_s: number | null;
  v_crit_ft_s: number | null;
  q_crit_mscfd: number | null;
  metastable_regime: string | null;
  q_min_stable_mscfd: number | null;
}