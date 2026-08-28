"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { getWell, getLoading, getForecast, getCharts } from "@/lib/api";
import type { Well, LoadingResult, ForecastResult, ChartsResult } from "@/lib/types";

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

type TabKey = "resumen" | "forecast" | "carga" | "sensibilidad";

const TABS: { key: TabKey; label: string }[] = [
  { key: "resumen", label: "Resumen" },
  { key: "forecast", label: "Pronostico" },
  { key: "carga", label: "Carga liquida" },
  { key: "sensibilidad", label: "Sensibilidad" },
];

export default function WellDetailPage() {
  const params = useParams();
  const wellId = Number(params.wellId);

  const [well, setWell] = useState<Well | null>(null);
  const [loading, setLoading] = useState<LoadingResult | null>(null);
  const [forecast, setForecast] = useState<ForecastResult | null>(null);
  const [charts, setCharts] = useState<ChartsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingState, setLoadingState] = useState(true);
  const [tab, setTab] = useState<TabKey>("resumen");

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
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Error desconocido");
      } finally {
        setLoadingState(false);
      }
    }
    load();
  }, [wellId]);

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
      </div>
    </main>
  );
}