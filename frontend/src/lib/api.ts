import type {
  Well,
  LoadingResult,
  ForecastResult,
  ChartsResult,
  ApiKeyInfo,
  Alert,
  Twin,
  TrainResult,
  MlStatus,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
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

export async function getLoading(id: number): Promise<LoadingResult> {
  return apiFetch<LoadingResult>(`/api/wells/${id}/analysis/loading`);
}

export async function getForecast(id: number): Promise<ForecastResult> {
  return apiFetch<ForecastResult>(
    `/api/wells/${id}/analysis/forecast-view`
  );
}

export async function getCharts(id: number): Promise<ChartsResult> {
  return apiFetch<ChartsResult>(
    `/api/wells/${id}/analysis/charts`
  );
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