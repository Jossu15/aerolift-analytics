"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { getWell, getLoading, getForecast, getCharts, getTwins, getMlStatus, trainTwin } from "@/lib/api";
import type { Well, LoadingResult, ForecastResult, ChartsResult, Twin, MlStatus } from "@/lib/types";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

const SEVERITY_COLOR: Record<string, string> = {
  stable: "green",
  at_risk: "yellow",
  mild: "orange",
  moderate: "orange",
  severe: "red",
};

const SEVERITY_LABEL: Record<string, string> = {
  stable: "Estable",
  at_risk: "En riesgo",
  mild: "Cargado leve",
  moderate: "Cargado moderado",
  severe: "Cargado severo",
};

const STATUS_TEXT: Record<string, string> = {
  green: "text-green-600",
  yellow: "text-yellow-500",
  orange: "text-orange-500",
  red: "text-red-600",
};

type TabKey = "resumen" | "forecast" | "carga" | "sensibilidad" | "twin";

const TABS: { key: TabKey; label: string }[] = [
  { key: "resumen", label: "Resumen" },
  { key: "forecast", label: "Pronostico" },
  { key: "carga", label: "Carga liquida" },
  { key: "sensibilidad", label: "Sensibilidad" },
  { key: "twin", label: "Digital Twin" },
];

export default function WellDetailPage() {
  const params = useParams();
  const wellId = Number(params.wellId);

  const [well, setWell] = useState<Well | null>(null);
  const [loading, setLoading] = useState<LoadingResult | null>(null);
  const [forecast, setForecast] = useState<ForecastResult | null>(null);
  const [charts, setCharts] = useState<ChartsResult | null>(null);
  const [twins, setTwins] = useState<Twin[]>([]);
  const [mlStatus, setMlStatus] = useState<MlStatus | null>(null);
  const [twinBusy, setTwinBusy] = useState(false);
  const [twinMsg, setTwinMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingState, setLoadingState] = useState(true);
  const [tab, setTab] = useState<TabKey>("resumen");

  const refreshTwinCb = useCallback(async () => {
    const [t, s] = await Promise.all([getTwins(wellId), getMlStatus(wellId)]);
    setTwins(t);
    setMlStatus(s);
  }, [wellId]);

  async function handleTrain() {
    setTwinBusy(true);
    setTwinMsg(null);
    try {
      await trainTwin(wellId);
      await refreshTwinCb();
      setTwinMsg("Twin reentrenado correctamente.");
    } catch (e: unknown) {
      setTwinMsg(e instanceof Error ? e.message : "Error al entrenar twin");
    } finally {
      setTwinBusy(false);
    }
  }

  useEffect(() => {
    async function load() {
      try {
        const [w, l, f] = await Promise.all([
          getWell(wellId),
          getLoading(wellId),
          getForecast(wellId),
        ]);
        setWell(w);
        setLoading(l);
        setForecast(f);
        getCharts(wellId)
          .then(setCharts)
          .catch(() => setCharts(null));
        refreshTwinCb().catch(() => undefined);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Error desconocido");
      } finally {
        setLoadingState(false);
      }
    }
    load();
  }, [wellId, refreshTwinCb]);

  if (loadingState) {
    return (
      <div className="flex items-center justify-center h-screen text-gray-400">
        Cargando pozo...
      </div>
    );
  }

  if (error || !well || !loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-600 font-medium">Error</p>
          <p className="text-sm text-gray-500 mt-1">{error || "Pozo no encontrado"}</p>
          <Link href="/dashboard" className="text-blue-600 text-sm mt-3 inline-block">
            Volver al dashboard
          </Link>
        </div>
      </div>
    );
  }

  const severityColor = SEVERITY_COLOR[loading.severity] || "green";
  const forecastDays = forecast?.history?.map((r) => r.day) || [];
  const forecastRates = forecast?.history?.map((r) => r.q_mscfd) || [];
  const forecastStatuses = forecast?.history || [];
  const forecastLoading = forecastStatuses
    .filter((r) => r.status === "loaded" || r.status === "loaded_forecast")
    .map((r) => r.q_mscfd);

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto px-4 py-6">
        <Link href="/dashboard" className="text-blue-600 text-sm hover:underline">
          &larr; Volver al dashboard
        </Link>

        <header className="mt-4 mb-4">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">{well.tag}</h1>
            <span className={`text-lg font-semibold ${STATUS_TEXT[severityColor] || STATUS_TEXT.green}`}>
              {SEVERITY_LABEL[loading.severity] || "Estable"}
            </span>
          </div>
          <p className="text-sm text-gray-500">
            ID {well.id} &middot; {well.well_type === "gas" ? "Gas" : "Petroleo"} &middot; TVD{" "}
            {well.tvd_ft} ft &middot; {well.tubing_id_in}&quot;
          </p>
        </header>

        <nav className="flex gap-1 mb-6 border-b border-gray-200">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2 -mb-px text-sm font-medium border-b-2 transition ${
                tab === t.key
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        {tab === "resumen" && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {[
                { label: "v actual", value: `${loading.v_actual_ft_s.toFixed(2)} ft/s` },
                { label: "v crit", value: `${loading.v_crit_ft_s.toFixed(2)} ft/s` },
                {
                  label: "Margen",
                  value: loading.margin_pct !== null
                    ? `${loading.margin_pct >= 0 ? "+" : ""}${loading.margin_pct.toFixed(1)}%`
                    : "n/a",
                },
                { label: "q crit", value: `${loading.q_crit_mscfd.toFixed(0)} Mscf/D` },
              ].map((item) => (
                <div key={item.label} className="bg-white rounded-lg border p-3">
                  <p className="text-xs text-gray-400">{item.label}</p>
                  <p className="font-mono text-sm font-medium text-gray-800">{item.value}</p>
                </div>
              ))}
            </div>

            <div className="bg-white rounded-lg border p-4">
              <h2 className="font-semibold text-gray-800 mb-2">Diagnostico</h2>
              <p className="text-sm text-gray-700">{loading.headline}</p>
              {loading.first_action && (
                <p className="text-sm text-gray-500 mt-1">
                  Accion sugerida: <span className="font-medium">{loading.first_action}</span>
                </p>
              )}
            </div>

            {loading.metastable_regime === "metastable" && (
              <div className="px-4 py-3 bg-amber-50 border border-amber-300 rounded-lg text-sm text-amber-800">
                Este pozo opera en <strong>regimen metaestable</strong>. Puede continuar fluyendo
                hasta una tasa minima de {loading.q_min_stable_mscfd?.toFixed(0)} Mscf/D,
                por debajo del critico de Turner (Dousi 2006).
              </div>
            )}

            <div className="bg-white rounded-lg border p-4">
              <h2 className="font-semibold text-gray-800 mb-3">Parametros</h2>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
                {[
                  ["P_res", `${well.p_res} psia`],
                  ["Pwh", `${well.p_wh} psia`],
                  ["T_res", `${well.t_res_f} F`],
                  ["TVD", `${well.tvd_ft} ft`],
                  ["D tubing", `${well.tubing_id_in} in`],
                  ["gamma_g", well.gamma_g.toFixed(3)],
                  ["q agua", `${well.q_water_bpd} bbl/D`],
                  ["q nominal", `${well.q_gas_nominal_mscfd} Mscf/D`],
                  ["Metodo", well.load_method],
                  ["VLP", well.vlp_model],
                ].map(([label, value]) => (
                  <div key={label}>
                    <span className="text-gray-400 text-xs">{label}</span>
                    <p className="font-mono text-gray-800">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === "forecast" && forecast && (
          <div className="bg-white rounded-lg border p-4">
            <h2 className="font-semibold text-gray-800 mb-3">Declinacion y vida util</h2>
            {forecast.preview && forecast.note && (
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-300 rounded px-3 py-2 mb-3">
                {forecast.note}
              </p>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm mb-4">
              <div>
                <span className="text-gray-400">Dias a carga critica</span>
                <p className="font-mono font-medium">
                  {forecast.days_to_risk !== null
                    ? `${Math.round(forecast.days_to_risk)} dias`
                    : "No prevista"}
                </p>
              </div>
              <div>
                <span className="text-gray-400">OGIP</span>
                <p className="font-mono font-medium">
                  {forecast.ogip_mmscf.toFixed(0)} MMscf
                </p>
              </div>
              <div>
                <span className="text-gray-400">Pi/Zi</span>
                <p className="font-mono font-medium">
                  {forecast.pi_over_zi_psia.toFixed(0)} psia
                </p>
              </div>
              <div>
                <span className="text-gray-400">Pendiente MB</span>
                <p className="font-mono font-medium">
                  {forecast.mb_slope.toExponential(2)}
                </p>
              </div>
            </div>

            {forecastDays.length > 0 && (
              <Plot
                data={[
                  {
                    x: forecastDays,
                    y: forecastRates,
                    type: "scatter",
                    mode: "lines",
                    name: "Tasa",
                    line: { color: "#2563eb" },
                  },
                  {
                    x: forecastDays,
                    y: forecastLoading,
                    type: "scatter",
                    mode: "markers",
                    name: "Carga critica",
                    marker: { color: "#ef4444", size: 4 },
                  },
                ]}
                layout={{
                  autosize: true,
                  height: 320,
                  margin: { l: 50, r: 20, t: 10, b: 40 },
                  xaxis: { title: "Dia" },
                  yaxis: { title: "Tasa (Mscf/D)" },
                  legend: { orientation: "h", y: 1.1 },
                }}
                config={{ responsive: true, displayModeBar: false }}
                style={{ width: "100%" }}
              />
            )}
          </div>
        )}

        {tab === "forecast" && !forecast && (
          <div className="bg-white rounded-lg border p-6 text-center text-gray-400 text-sm">
            No hay pronostico disponible para este pozo.
          </div>
        )}

        {tab === "carga" && (
          <div className="space-y-6">
            {(charts ? [["Envolvente operativa", "operating_envelope"] as const] : []).map(
              ([label, key]) => (
                <div key={key} className="bg-white rounded-lg border p-4">
                  <h2 className="font-semibold text-gray-800 mb-3">{label}</h2>
                  <Plot
                    data={charts![key].data as never[]}
                    layout={{
                      autosize: true,
                      height: 380,
                      margin: { l: 50, r: 20, t: 20, b: 40 },
                      ...(charts![key].layout as object),
                    }}
                    config={{ responsive: true, displayModeBar: false }}
                    style={{ width: "100%" }}
                  />
                </div>
              )
            )}
            {!charts && (
              <div className="bg-white rounded-lg border p-6 text-center text-gray-400 text-sm">
                Graficas no disponibles para este pozo.
              </div>
            )}
          </div>
        )}

        {tab === "sensibilidad" && (
          <div className="space-y-6">
            {(charts
              ? [
                  ["vcrit vs presion", "vcrit_vs_pressure"],
                  ["vcrit vs temperatura", "vcrit_vs_temperature"],
                  ["vcrit vs diametro", "vcrit_vs_diameter"],
                ] as const
              : []
            ).map(([label, key]) => (
              <div key={key} className="bg-white rounded-lg border p-4">
                <h2 className="font-semibold text-gray-800 mb-3">{label}</h2>
                <Plot
                  data={charts![key].data as never[]}
                  layout={{
                    autosize: true,
                    height: 360,
                    margin: { l: 50, r: 20, t: 20, b: 40 },
                    ...(charts![key].layout as object),
                  }}
                  config={{ responsive: true, displayModeBar: false }}
                  style={{ width: "100%" }}
                />
              </div>
            ))}
            {!charts && (
              <div className="bg-white rounded-lg border p-6 text-center text-gray-400 text-sm">
                Graficas no disponibles para este pozo.
              </div>
            )}
          </div>
        )}

        {tab === "twin" && (
          <div className="space-y-6">
            <div className="bg-white rounded-lg border p-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold text-gray-800">
                  {mlStatus?.trained ? "Twin activo" : "Sin twin entrenado"}
                </h2>
                <p className="text-sm text-gray-500 mt-1">
                  Correccion residual (ML) sobre el VLP f&iacute;sico.
                  {mlStatus?.active === false ? " Este twin no esta activo." : ""}
                </p>
              </div>
              <button
                onClick={handleTrain}
                disabled={twinBusy}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 text-white disabled:opacity-50 hover:bg-blue-700 transition"
              >
                {twinBusy ? "Entrenando..." : mlStatus?.trained ? "Reentrenar" : "Entrenar"}
              </button>
            </div>

            {twinMsg && (
              <p className="text-sm text-gray-600 bg-gray-50 border rounded-lg px-3 py-2">
                {twinMsg}
              </p>
            )}

            {(twins.length > 0 ? twins : [{ active: true, version: null, source: "", trained_at: "", n_points: 0, mae_psi: null, r2: null, residual_mean_psi: null, residual_std_psi: null }])
              .slice(0, 1)
              .map((t, i) => (
                <div key={i} className="bg-white rounded-lg border p-4">
                  <h3 className="text-sm font-semibold text-gray-700 mb-3">
                    {t.version !== null ? `Version v${t.version}` : "Perfil actual"}
                  </h3>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                    {[
                      ["Fuente", t.source || "legacy"],
                      ["Puntos", t.n_points !== null && t.n_points !== 0 ? `${t.n_points}` : "n/a"],
                      ["MAE", t.mae_psi !== null ? `${t.mae_psi.toFixed(2)} psi` : "n/a"],
                      ["r²", t.r2 !== null ? t.r2.toFixed(3) : "n/a"],
                      ["Residuo medio", t.residual_mean_psi !== null ? `${t.residual_mean_psi.toFixed(2)} psi` : "n/a"],
                      ["Banda ±1σ", t.residual_std_psi !== null ? `± ${t.residual_std_psi.toFixed(2)} psi` : "n/a"],
                      ["Entrenado", t.trained_at ? new Date(t.trained_at).toLocaleString() : "n/a"],
                      ["Estado", t.active ? "activo" : "historico"],
                    ].map(([label, value]) => (
                      <div key={label as string}>
                        <span className="text-gray-400 text-xs block">{label}</span>
                        <p className="font-mono text-gray-800">{value}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ))}

            <div className="bg-white rounded-lg border p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-3">
                Historial de calibracion
              </h3>
              {twins.length === 0 ? (
                <p className="text-sm text-gray-400">
                  Aun no hay versiones. Entrena el twin para generar la primera.
                </p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-400 text-xs border-b">
                      <th className="pb-2">Version</th>
                      <th className="pb-2">Puntos</th>
                      <th className="pb-2">MAE (psi)</th>
                      <th className="pb-2">r²</th>
                      <th className="pb-2">±1σ (psi)</th>
                      <th className="pb-2">Fuente</th>
                      <th className="pb-2">Estado</th>
                      <th className="pb-2">Entrenado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {twins.map((t) => (
                      <tr key={t.version} className="border-b last:border-0">
                        <td className="py-2 font-mono">v{t.version}</td>
                        <td className="py-2">{t.n_points}</td>
                        <td className="py-2">{t.mae_psi?.toFixed(2) ?? "n/a"}</td>
                        <td className="py-2">{t.r2?.toFixed(3) ?? "n/a"}</td>
                        <td className="py-2">
                          {t.residual_std_psi !== null ? `± ${t.residual_std_psi.toFixed(2)}` : "n/a"}
                        </td>
                        <td className="py-2">{t.source}</td>
                        <td className="py-2">{t.active ? "activo" : "historico"}</td>
                        <td className="py-2">{new Date(t.trained_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}