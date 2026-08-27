import type {
  Well,
  LoadingResult,
  ForecastResult,
  WellsListResponse,
  ApiKeyInfo,
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

export async function getWells(): Promise<WellsListResponse> {
  return apiFetch<WellsListResponse>("/api/wells");
}

export async function getWell(id: number): Promise<Well> {
  return apiFetch<Well>(`/api/wells/${id}`);
}

export async function getLoading(id: number): Promise<LoadingResult> {
  return apiFetch<LoadingResult>(`/api/wells/${id}/analysis/loading`);
}

export async function getForecast(
  id: number,
  months: number = 60
): Promise<ForecastResult> {
  return apiFetch<ForecastResult>(`/api/wells/${id}/analysis/forecast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ forecast_months: months }),
  });
}

export async function getApiKeyInfo(): Promise<ApiKeyInfo> {
  return apiFetch<ApiKeyInfo>("/api/auth/me");
}

export async function getAllLoadingStatuses(): Promise<LoadingResult[]> {
  const { wells } = await getWells();
  const results = await Promise.allSettled(
    wells.map((w) => getLoading(w.id))
  );
  return results
    .filter((r): r is PromiseFulfilledResult<LoadingResult> => r.status === "fulfilled")
    .map((r) => r.value);
}
