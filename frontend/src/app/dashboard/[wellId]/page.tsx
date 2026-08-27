"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { getWell, getLoading, getForecast } from "@/lib/api";
import type { Well, LoadingResult, ForecastResult } from "@/lib/types";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

const SEVERITY_LABEL: Record<string, string> = {
  green: "Estable",
  yellow: "En riesgo",
  orange: "Precaucion",
  red: "Cargado",
};

const STATUS_COLOR: Record<string, string> = {
  green: "text-green-600",
  yellow: "text-yellow-500",
  orange: "text-orange-500",
  red: "text-red-600",
};

export default function WellDetailPage() {
  const params = useParams();
  const wellId = Number(params.wellId);

  const [well, setWell] = useState<Well | null>(null);
  const [loading, setLoading] = useState<LoadingResult | null>(null);
  const [forecast, setForecast] = useState<ForecastResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingState, setLoadingState] = useState(true);

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

  const forecastDays = forecast?.history?.map((r) => r.day) || [];
  const forecastRates = forecast?.history?.map((r) => r.q_mscfd) || [];
  const forecastLoading = forecast?.history?.map((r) => (r.is_loading ? r.q_mscfd : null)) || [];

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 py-6">
        <Link href="/dashboard" className="text-blue-600 text-sm hover:underline">
          &larr; Volver al dashboard
        </Link>

        <header className="mt-4 mb-6">
          <h1 className="text-2xl font-bold text-gray-900">{well.tag}</h1>
          <p className="text-sm text-gray-500">
            ID {well.id} &middot; {well.well_type === "gas" ? "Gas" : "Petroleo"} &middot; TVD{" "}
            {well.tvd_ft} ft &middot; {well.tubing_id_in}&quot;
          </p>
          <p className={`text-lg font-semibold mt-1 ${STATUS_COLOR[loading.severity]}`}>
            {SEVERITY_LABEL[loading.severity] || loading.status}
          </p>
        </header>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          {[
            { label: "v actual", value: `${loading.v_actual_fts.toFixed(2)} ft/s` },
            { label: "v crit", value: `${loading.v_crit_fts.toFixed(2)} ft/s` },
            { label: "Margen", value: `${loading.margin_pct >= 0 ? "+" : ""}${loading.margin_pct.toFixed(1)}%` },
            { label: "q crit", value: `${loading.q_crit_mscfd.toFixed(0)} Mscf/D` },
          ].map((item) => (
            <div key={item.label} className="bg-white rounded-lg border p-3">
              <p className="text-xs text-gray-400">{item.label}</p>
              <p className="font-mono text-sm font-medium text-gray-800">{item.value}</p>
            </div>
          ))}
        </div>

        {loading.metastable_regime && (
          <div className="mb-6 px-4 py-3 bg-amber-50 border border-amber-300 rounded-lg text-sm text-amber-800">
            Este pozo opera en <strong>regimen metaestable</strong>. Puede continuar fluyendo
            hasta una tasa minima de {loading.q_min_stable_mscfd?.toFixed(0)} Mscf/D,
            por debajo del critico de Turner.
          </div>
        )}

        {forecast && (
          <div className="bg-white rounded-lg border p-4 mb-6">
            <h2 className="font-semibold text-gray-800 mb-3">Pronostico de vida</h2>
            <div className="grid grid-cols-2 gap-4 text-sm mb-4">
              <div>
                <span className="text-gray-400">Dia de muerte predicho</span>
                <p className="font-mono font-medium">
                  {forecast.predicted_death_day !== null
                    ? `Dia ${Math.round(forecast.predicted_death_day)}`
                    : "Sin prediccion"}
                </p>
              </div>
              <div>
                <span className="text-gray-400">Estatus</span>
                <p className="font-medium">{forecast.status}</p>
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
                    name: "Cargado",
                    marker: { color: "#ef4444", size: 4 },
                  },
                ]}
                layout={{
                  autosize: true,
                  height: 300,
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

        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold text-gray-800 mb-3">Parametros</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
            {[
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
    </main>
  );
}
