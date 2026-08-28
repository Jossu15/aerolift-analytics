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
  computed_at: string | null;
}

export interface Twin {
  version: number;
  trained_at: string;
  active: boolean;
  source: string;
  n_points: number;
  mae_psi: number | null;
  r2: number | null;
  residual_mean_psi: number | null;
  residual_std_psi: number | null;
}

export interface TrainResult extends Twin {
  features: string[];
}

export interface MlStatus {
  trained: boolean;
  version?: number | null;
  active?: boolean;
  source?: string;
  ml_path?: string | null;
  features?: string[];
  n_points?: number;
  metrics?: Record<string, number>;
  trained_at?: string;
}

export interface PortfolioRankRow {
  well_id: number;
  tag: string;
  q_nominal_mscfd: number | null;
  at_risk: boolean;
  actionable: boolean;
  intervention: string | null;
  label: string | null;
  cost_usd: number | null;
  npv_usd: number | null;
  roi_pct: number | null;
  payback_months: number | null;
  incremental_gas_mmscf: number | null;
  life_extension_days: number | null;
}

export interface BudgetChoice {
  well_id: number | null;
  tag: string | null;
  intervention: string;
  label: string | null;
  cost_usd: number;
  npv_usd: number;
  roi_pct: number | null;
  payback_months: number | null;
  incremental_gas_mmscf: number;
  life_extension_days: number | null;
}

export interface BudgetPlan {
  chosen: BudgetChoice[];
  total_cost_usd: number;
  total_npv_usd: number;
  budget_usd: number;
  utilization_pct: number;
  wells_selected: number;
  total_incremental_gas_mmscf: number;
}

export interface PortfolioSummary {
  wells_total: number;
  wells_at_risk: number;
  gas_at_risk_mscfd: number;
  wells_actionable: number;
  gas_actionable_mscfd: number;
  wells_positive_npv: number;
  positive_npv_usd: number;
  positive_cost_usd: number;
  positive_incremental_gas_mmscf: number;
  positive_roi_mean_pct: number | null;
  positive_payback_mean_months: number | null;
  budget: BudgetPlan | null;
}

export interface PortfolioRun {
  id: number;
  status: string; // queued | running | done | failed
  gas_price_usd_mcf: number;
  max_steps: number;
  wells_total: number;
  wells_actionable: number;
  created_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface PortfolioRunDetail extends PortfolioRun {
  summary: Partial<PortfolioSummary> | null;
  items: PortfolioRankRow[];
}