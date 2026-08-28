"use client";

import { useCallback, useEffect, useState } from "react";
import { getAlerts } from "@/lib/api";
import type { Alert } from "@/lib/types";
import WellCard from "./WellCard";
import AlertsPanel from "./AlertsPanel";

export default function DashboardGrid() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const POLL_MS = Number(process.env.NEXT_PUBLIC_ALERT_POLL_MS || 60000);

  const load = useCallback(async () => {
    try {
      const data = await getAlerts();
      setAlerts(data);
      setLastUpdated(new Date());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initial = setTimeout(load, 0);
    const id = setInterval(load, POLL_MS);
    return () => {
      clearTimeout(initial);
      clearInterval(id);
    };
  }, [load, POLL_MS]);

  const filtered =
    filter === "all"
      ? alerts
      : alerts.filter((a) => a.status === filter);

  const counts = {
    all: alerts.length,
    stable: alerts.filter((a) => a.status === "stable").length,
    at_risk: alerts.filter((a) => a.status === "at_risk").length,
    metastable: alerts.filter((a) => a.status === "metastable").length,
    loaded: alerts.filter((a) => a.status === "loaded").length,
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        Cargando pozos...
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center">
        <p className="text-red-700 font-medium">Error al conectar con la API</p>
        <p className="text-red-500 text-sm mt-1">{error}</p>
        <p className="text-gray-400 text-xs mt-3">
          Verifica que el backend este corriendo en {process.env.NEXT_PUBLIC_API_URL || "localhost:8000"}
        </p>
      </div>
    );
  }

  const updatedLabel = lastUpdated
    ? lastUpdated.toLocaleTimeString()
    : "nunca";

  return (
    <div>
      <div className="flex items-center justify-between mt-2 mb-1">
        <AlertsPanel alerts={alerts} />
        <div className="flex items-center gap-3 shrink-0 ml-4">
          <span className="text-xs text-gray-400 whitespace-nowrap">
            Actualizado {updatedLabel}
          </span>
          <button
            onClick={() => load()}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 transition"
          >
            Actualizar
          </button>
        </div>
      </div>

      <div className="flex gap-2 mt-6 mb-4 flex-wrap">
        {(["all", "stable", "at_risk", "metastable", "loaded"] as const).map(
          (key) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition ${
                filter === key
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {key === "all"
                ? `Todos (${counts.all})`
                : key === "stable"
                ? `Estable (${counts.stable})`
                : key === "at_risk"
                ? `En riesgo (${counts.at_risk})`
                : key === "metastable"
                ? `Metaestable (${counts.metastable})`
                : `Cargado (${counts.loaded})`}
            </button>
          )
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {filtered.map((a) => (
          <WellCard
            key={a.well_id}
            alert={a}
          />
        ))}
      </div>

      {filtered.length === 0 && (
        <div className="text-center text-gray-400 py-12 text-sm">
          No hay pozos en esta categoria
        </div>
      )}
    </div>
  );
}