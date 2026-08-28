"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  getPortfolioRanking,
  getPortfolioSummary,
  getPortfolioRun,
  getPortfolioRuns,
  planBudget,
  startPortfolioRun,
} from "@/lib/api";
import type {
  PortfolioRankRow,
  PortfolioSummary,
  BudgetPlan,
  PortfolioRunDetail,
} from "@/lib/types";

const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(v);

const fmtNum = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined
    ? "—"
    : v.toLocaleString("en-US", {
        maximumFractionDigits: d,
        minimumFractionDigits: d,
      });

function KpiCard({
  label,
  value,
  sub,
  accent = "text-gray-900",
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
        {label}
      </p>
      <p className={`text-2xl font-bold mt-1 ${accent}`}>{value}</p>
      {sub ? <p className="text-xs text-gray-400 mt-1">{sub}</p> : null}
    </div>
  );
}

function RankTable({ rows }: { rows: PortfolioRankRow[] }) {
  const ranked = rows.filter((r) => r.npv_usd !== null);
  const others = rows.filter((r) => r.npv_usd === null);
  const displayed = [...ranked, ...others];
  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr className="text-left text-xs text-gray-500 uppercase">
            <th className="px-4 py-3">Pozo</th>
            <th className="px-4 py-3">Riesgo</th>
            <th className="px-4 py-3">Intervención</th>
            <th className="px-4 py-3">NPV</th>
            <th className="px-4 py-3">ROI</th>
            <th className="px-4 py-3">Payback</th>
            <th className="px-4 py-3">ΔGas (MMscf)</th>
            <th className="px-4 py-3">Costo</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {displayed.map((r) => (
            <tr
              key={r.well_id}
              className={r.at_risk ? "bg-orange-50/40" : "bg-white"}
            >
              <td className="px-4 py-3 font-medium text-gray-900">
                {r.tag}
              </td>
              <td className="px-4 py-3">
                <span
                  className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                    r.at_risk
                      ? "bg-orange-100 text-orange-700"
                      : "bg-emerald-100 text-emerald-700"
                  }`}
                >
                  {r.at_risk ? "En riesgo" : "Estable"}
                </span>
              </td>
              <td className="px-4 py-3 text-gray-700">
                {r.intervention
                  ? `${r.intervention}${r.label ? ` · ${r.label}` : ""}`
                  : "—"}
              </td>
              <td
                className={`px-4 py-3 font-medium ${
                  (r.npv_usd ?? 0) >= 0
                    ? "text-emerald-600"
                    : "text-red-600"
                }`}
              >
                {fmtUsd(r.npv_usd)}
              </td>
              <td className="px-4 py-3 text-gray-700">
                {r.roi_pct === null ? "—" : `${fmtNum(r.roi_pct, 0)}%`}
              </td>
              <td className="px-4 py-3 text-gray-700">
                {r.payback_months === null
                  ? "—"
                  : `${r.payback_months} meses`}
              </td>
              <td className="px-4 py-3 text-gray-700">
                {r.incremental_gas_mmscf === null
                  ? "—"
                  : fmtNum(r.incremental_gas_mmscf, 1)}
              </td>
              <td className="px-4 py-3 text-gray-700">
                {fmtUsd(r.cost_usd)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {displayed.length === 0 && (
        <p className="text-center text-gray-400 py-10 text-sm">
          No hay pozos en la cartera
        </p>
      )}
    </div>
  );
}

function BudgetPanel({
  summaryBudget,
  onPlan,
  planning,
  error,
  plan,
}: {
  summaryBudget: BudgetPlan | null;
  onPlan: (budget: number, gas: number) => void;
  planning: boolean;
  error: string | null;
  plan: BudgetPlan | null;
}) {
  const [budget, setBudget] = useState(
    summaryBudget?.budget_usd ?? 1000000
  );
  const [gas, setGas] = useState(3.5);

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-gray-900">
        Simulador de presupuesto
      </h3>
      <p className="text-xs text-gray-500 mt-1">
        Selecciona el paquete de intervenciones con mayor NPV bajo un capex
        tope (knapsack).
      </p>
      <div className="flex flex-wrap items-center gap-3 mt-4">
        <label className="text-xs text-gray-500">
          Presupuesto (USD)
          <input
            type="number"
            min={0}
            step={50000}
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value) || 0)}
            className="ml-2 px-3 py-1.5 rounded-lg border border-gray-300 text-sm text-gray-900 w-36"
          />
        </label>
        <label className="text-xs text-gray-500">
          Gas (USD/Mscf)
          <input
            type="number"
            min={0.1}
            step={0.1}
            value={gas}
            onChange={(e) => setGas(Number(e.target.value) || 0)}
            className="ml-2 px-3 py-1.5 rounded-lg border border-gray-300 text-sm text-gray-900 w-24"
          />
        </label>
        <button
          onClick={() => onPlan(budget, gas)}
          disabled={planning || budget <= 0}
          className="px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 transition disabled:opacity-50"
        >
          {planning ? "Optimizando..." : "Optimizar"}
        </button>
      </div>
      {error ? (
        <p className="text-xs text-red-600 mt-3">{error}</p>
      ) : null}
      {plan && plan.chosen.length > 0 ? (
        <div className="mt-4">
          <div className="flex flex-wrap gap-4 text-xs mb-3">
            <span className="text-gray-500">
              Costo{" "}
              <b className="text-gray-900">{fmtUsd(plan.total_cost_usd)}</b>{" "}
              / {fmtUsd(plan.budget_usd)}
            </span>
            <span className="text-gray-500">
              Uso{" "}
              <b className="text-gray-900">
                {fmtNum(plan.utilization_pct, 1)}%
              </b>
            </span>
            <span className="text-gray-500">
              NPV{" "}
              <b className="text-emerald-600">
                {fmtUsd(plan.total_npv_usd)}
              </b>
            </span>
            <span className="text-gray-500">
              ΔGas{" "}
              <b className="text-gray-900">
                {fmtNum(plan.total_incremental_gas_mmscf, 1)} MMscf
              </b>
            </span>
          </div>
          <ul className="space-y-2">
            {plan.chosen.map((c) => (
              <li
                key={`${c.well_id}-${c.intervention}`}
                className="flex items-center justify-between text-sm rounded-lg bg-gray-50 px-3 py-2"
              >
                <span className="text-gray-700 font-medium">
                  {c.label || c.tag || `Pozo ${c.well_id}`}{" "}
                  <span className="text-gray-400 font-normal">
                    · {c.intervention}
                  </span>
                </span>
                <span className="text-gray-600 text-xs">
                  {fmtUsd(c.npv_usd)} NPV · {fmtUsd(c.cost_usd)} costo
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : plan ? (
        <p className="text-xs text-gray-400 mt-3">
          Ninguna intervención cabe dentro del presupuesto.
        </p>
      ) : null}
    </div>
  );
}

export default function PortfolioPage() {
  const [rows, setRows] = useState<PortfolioRankRow[]>([]);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [plan, setPlan] = useState<BudgetPlan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRun, setLastRun] = useState<PortfolioRunDetail | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    try {
      const runs = await getPortfolioRuns(3);
      const done = runs.find((r) => r.status === "done") || null;
      if (done) {
        const detail = await getPortfolioRun(done.id);
        setRows(detail.items);
        setSummary({
          ...(detail.summary as PortfolioSummary),
          budget: null,
        });
        setLastRun(detail);
      } else {
        const [r, s] = await Promise.all([
          getPortfolioRanking(),
          getPortfolioSummary(),
        ]);
        setRows(r);
        setSummary(s);
      }
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(load, 0);
    return () => clearTimeout(t);
  }, [load]);

  const handleBatch = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const run = await startPortfolioRun(3.5, 120);
      let current = await getPortfolioRun(run.id);
      while (current.status === "queued" || current.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        current = await getPortfolioRun(run.id);
      }
      if (current.status === "failed") {
        setError(
          `El run ${run.id} falló: ${current.error || "error desconocido"}`
        );
      } else {
        setRows(current.items);
        setSummary({
          ...(current.summary as PortfolioSummary),
          budget: null,
        });
        setLastRun(current);
        setPlan(null);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setRunning(false);
    }
  }, []);

  const handlePlan = useCallback(
    async (budget: number, gas: number) => {
      setPlanning(true);
      setError(null);
      try {
        setPlan(await planBudget(budget, gas));
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Error desconocido");
      } finally {
        setPlanning(false);
      }
    },
    []
  );

  const s = summary;
  const kpis = s
    ? [
        { label: "Pozos", value: String(s.wells_total) },
        {
          label: "En riesgo",
          value: String(s.wells_at_risk),
          sub: `${fmtNum(s.gas_at_risk_mscfd)} Mscf/D`,
          accent: s.wells_at_risk > 0 ? "text-orange-600" : "text-gray-900",
        },
        {
          label: "Accionables",
          value: String(s.wells_actionable),
          sub: `${fmtNum(s.gas_actionable_mscfd)} Mscf/D recuperables`,
        },
        {
          label: "NPV positivo",
          value: fmtUsd(s.positive_npv_usd),
          sub: `${s.wells_positive_npv} pozos · costo ${fmtUsd(
            s.positive_cost_usd
          )} · ROI ${fmtNum(s.positive_roi_mean_pct, 0)}% · ΔGas ${fmtNum(
            s.positive_incremental_gas_mmscf,
            1
          )} MMscf`,
          accent: "text-emerald-600",
        },
      ]
    : [];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            Portfolio Optimizer
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Ranking de intervenciones, recuperación de gas y simulación de
            presupuesto
          </p>
        </div>
        <Link
          href="/dashboard"
          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 transition"
        >
          ← Dashboard
        </Link>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64 text-gray-400">
          Evaluando cartera...
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-red-700 font-medium">
            Error al conectar con la API
          </p>
          <p className="text-red-500 text-sm mt-1">{error}</p>
        </div>
      ) : (
        <>
          <div className="rounded-xl border border-gray-200 bg-white px-5 py-3 shadow-sm mb-6 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3 text-xs">
              <span className="text-gray-500">Evaluación batch:</span>
              {running ? (
                <span className="inline-flex items-center gap-2 text-blue-600 font-medium">
                  <span className="inline-block w-3 h-3 rounded-full border-2 border-blue-600 border-t-transparent animate-spin" />
                  Calculando sobre todo el campo...
                </span>
              ) : lastRun ? (
                <span className="text-gray-600">
                  #{lastRun.id} ·{" "}
                  {lastRun.finished_at
                    ? new Date(lastRun.finished_at).toLocaleTimeString()
                    : "—"}{" "}
                  · {lastRun.wells_total} pozos,{" "}
                  {lastRun.wells_actionable} accionables · gas $
                  {lastRun.gas_price_usd_mcf}/Mscf · max {lastRun.max_steps}
                  pasos
                </span>
              ) : (
                <span className="text-gray-400">
                  Aún no hay runs; mostrando evaluación síncrona
                </span>
              )}
            </div>
            <button
              onClick={handleBatch}
              disabled={running}
              className="px-4 py-1.5 rounded-lg text-sm font-medium bg-gray-900 text-white hover:bg-gray-700 transition disabled:opacity-50"
            >
              {running ? "En cola..." : "Recalcular en batch"}
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {kpis.map((k) => (
              <KpiCard key={k.label} {...k} />
            ))}
          </div>

          <BudgetPanel
            key={summary ? "loaded" : "init"}
            summaryBudget={summary?.budget ?? null}
            onPlan={handlePlan}
            planning={planning}
            error={error}
            plan={plan}
          />

          <h2 className="text-sm font-semibold text-gray-900 mt-8 mb-3">
            Ranking por pozo (mejor NPV primero)
          </h2>
          <RankTable rows={rows} />
        </>
      )}
    </div>
  );
}