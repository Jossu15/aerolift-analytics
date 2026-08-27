"use client";

import type { LoadingResult } from "@/lib/types";
import Link from "next/link";

const SEVERITY_STYLES: Record<string, string> = {
  green: "border-green-500 bg-green-50 shadow-green-100",
  yellow: "border-yellow-400 bg-yellow-50 shadow-yellow-100",
  orange: "border-orange-400 bg-orange-50 shadow-orange-100",
  red: "border-red-500 bg-red-50 shadow-red-100",
};

const SEVERITY_DOT: Record<string, string> = {
  green: "bg-green-500",
  yellow: "bg-yellow-400",
  orange: "bg-orange-400",
  red: "bg-red-500",
};

const STATUS_LABELS: Record<string, string> = {
  stable: "Estable",
  at_risk: "En riesgo",
  loaded: "Cargado",
  metastable: "Metaestable",
};

interface WellCardProps {
  loading: LoadingResult;
  tag: string;
}

export default function WellCard({ loading, tag }: WellCardProps) {
  const severity = loading.severity || "green";
  const borderClass = SEVERITY_STYLES[severity] || SEVERITY_STYLES.green;

  return (
    <Link href={`/dashboard/${loading.well_id}`}>
      <div
        className={`rounded-xl border-2 p-4 shadow-md transition-all hover:shadow-lg cursor-pointer ${borderClass}`}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-800 text-sm truncate">
            {tag}
          </h3>
          <div className="flex items-center gap-2">
            <span
              className={`w-3 h-3 rounded-full ${SEVERITY_DOT[severity]}`}
            />
            <span className="text-xs font-medium text-gray-500">
              {STATUS_LABELS[loading.status] || loading.status}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs text-gray-600">
          <div>
            <span className="text-gray-400">v actual</span>
            <p className="font-mono font-medium">
              {loading.v_actual_fts.toFixed(2)} ft/s
            </p>
          </div>
          <div>
            <span className="text-gray-400">v crit</span>
            <p className="font-mono font-medium">
              {loading.v_crit_fts.toFixed(2)} ft/s
            </p>
          </div>
          <div>
            <span className="text-gray-400">Margen</span>
            <p className="font-mono font-medium">
              {loading.margin_pct >= 0 ? "+" : ""}
              {loading.margin_pct.toFixed(1)}%
            </p>
          </div>
          <div>
            <span className="text-gray-400">q crit</span>
            <p className="font-mono font-medium">
              {loading.q_crit_mscfd.toFixed(0)} Mscf/D
            </p>
          </div>
        </div>

        {loading.metastable_regime && (
          <div className="mt-3 px-2 py-1 bg-amber-100 border border-amber-300 rounded text-xs text-amber-800">
            Regimen metaestable — puede fluir hasta{" "}
            {loading.q_min_stable_mscfd?.toFixed(0)} Mscf/D
          </div>
        )}
      </div>
    </Link>
  );
}
