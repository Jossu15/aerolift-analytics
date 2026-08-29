import type {
  Well,
  LoadingResult,
  ForecastResult,
  ChartsResult,
  TraverseResult,
  CalibrationResult,
  EconomicsRequest,
  EconomicsResult,
  HistoryUploadResult,
  OilIprResult,
  ApiKeyInfo,
  Alert,
  Twin,
  TrainResult,
  MlStatus,
  PortfolioRankRow,
  PortfolioSummary,
  BudgetPlan,
  PortfolioRun,
  PortfolioRunDetail,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";

async function apiFetch<T>(
  path: string,
  opts: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    "X-API-Key": API_KEY,
    ...(opts.headers as Record<string, string> || {}),
  };

  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      `API ${res.status}: ${body.detail || res.statusText}`
    );
  }
  return res.json();
}

export async function getWells(): Promise<Well[]> {
  return apiFetch<Well[]>("/api/wells");
}

export async function getWell(id: number): Promise<Well> {
  return apiFetch<Well>(`/api/wells/${id}`);
}

export async function getLoading(id: number, q?: number): Promise<LoadingResult> {
  const qs = q ? `?q_gas_mscfd=${q}` : "";
  return apiFetch<LoadingResult>(`/api/wells/${id}/analysis/loading${qs}`);
}

export async function getForecast(id: number): Promise<ForecastResult> {
  return apiFetch<ForecastResult>(
    `/api/wells/${id}/analysis/forecast-view`
  );
}

export async function getCharts(id: number, q?: number): Promise<ChartsResult> {
  const qs = q ? `?q_gas_mscfd=${q}` : "";
  return apiFetch<ChartsResult>(`/api/wells/${id}/analysis/charts${qs}`);
}

export async function getTraverse(
  id: number,
  q?: number
): Promise<TraverseResult> {
  const qs = q ? `?q_gas_mscfd=${q}` : "";
  return apiFetch<TraverseResult>(`/api/wells/${id}/analysis/traverse${qs}`);
}

export async function getCalibration(id: number): Promise<CalibrationResult> {
  return apiFetch<CalibrationResult>(`/api/wells/${id}/analysis/calibration`);
}

export async function postEconomics(
  id: number,
  payload: EconomicsRequest
): Promise<EconomicsResult> {
  return apiFetch<EconomicsResult>(`/api/wells/${id}/analysis/economics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function uploadHistoryCsv(
  id: number,
  csvText: string
): Promise<HistoryUploadResult> {
  return apiFetch<HistoryUploadResult>(`/api/wells/${id}/history/csv`, {
    method: "POST",
    headers: { "Content-Type": "text/csv" },
    body: csvText,
  });
}

export async function downloadReportPdf(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/wells/${id}/analysis/report.pdf`, {
    headers: { "X-API-Key": API_KEY },
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: no se pudo generar el reporte`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `aerolift_well_${id}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function postOilIpr(
  id: number,
  qoTestStbD: number,
  pwfTestPsia: number
): Promise<OilIprResult> {
  return apiFetch<OilIprResult>(`/api/wells/${id}/analysis/oil-ipr`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ qo_test_stb_d: qoTestStbD, pwf_test_psia: pwfTestPsia }),
  });
}

export async function getAlerts(): Promise<Alert[]> {
  return apiFetch<Alert[]>("/api/wells/alerts");
}

export async function getApiKeyInfo(): Promise<ApiKeyInfo> {
  return apiFetch<ApiKeyInfo>("/api/auth/me");
}

export async function getTwins(id: number): Promise<Twin[]> {
  return apiFetch<Twin[]>(`/api/wells/${id}/ml/twins`);
}

export async function getMlStatus(id: number): Promise<MlStatus> {
  return apiFetch<MlStatus>(`/api/wells/${id}/ml/status`);
}

export async function trainTwin(id: number): Promise<TrainResult> {
  return apiFetch<TrainResult>(`/api/wells/${id}/ml/train`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
}

export async function getPortfolioRanking(
  gasPrice?: number
): Promise<PortfolioRankRow[]> {
  const q = gasPrice ? `?gas_price_usd_mcf=${gasPrice}` : "";
  return apiFetch<PortfolioRankRow[]>(`/api/portfolio/ranking${q}`, {
    headers: { "Content-Type": "application/json" },
  });
}

export async function getPortfolioSummary(
  budgetUsd?: number,
  gasPrice?: number
): Promise<PortfolioSummary> {
  const params = new URLSearchParams();
  if (budgetUsd) params.set("budget_usd", String(budgetUsd));
  if (gasPrice) params.set("gas_price_usd_mcf", String(gasPrice));
  const qs = params.toString();
  return apiFetch<PortfolioSummary>(`/api/portfolio/summary?${qs}`);
}

export async function planBudget(
  budgetUsd: number,
  gasPrice?: number,
  onePerWell: boolean = true,
  maxSteps: number = 120
): Promise<BudgetPlan> {
  return apiFetch<BudgetPlan>("/api/portfolio/budget", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      budget_usd: budgetUsd,
      gas_price_usd_mcf: gasPrice,
      one_per_well: onePerWell,
      max_steps: maxSteps,
    }),
  });
}

export async function startPortfolioRun(
  gasPrice?: number,
  maxSteps: number = 120
): Promise<PortfolioRun> {
  return apiFetch<PortfolioRun>("/api/portfolio/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      gas_price_usd_mcf: gasPrice,
      max_steps: maxSteps,
    }),
  });
}

export async function getPortfolioRuns(limit: number = 5): Promise<PortfolioRun[]> {
  return apiFetch<PortfolioRun[]>(`/api/portfolio/runs?limit=${limit}`);
}

export async function getPortfolioRun(id: number): Promise<PortfolioRunDetail> {
  return apiFetch<PortfolioRunDetail>(`/api/portfolio/runs/${id}`);
}