"use client";

import type { Alert } from "@/lib/types";
import Link from "next/link";

const SEVERITY_BORDER: Record<string, string> = {
  green: "border-l-green-500",
  yellow: "border-l-yellow-400",
  orange: "border-l-orange-400",
  red: "border-l-red-500",
};

const SEVERITY_BG: Record<string, string> = {
  green: "bg-green-50",
  yellow: "bg-yellow-50",
  orange: "bg-orange-50",
  red: "bg-red-50",
};

interface AlertsPanelProps {
  alerts: Alert[];
}

export default function AlertsPanel({ alerts }: AlertsPanelProps) {
  const sorted = [...alerts].sort((a, b) => {
    const order: Record<string, number> = { red: 0, orange: 1, yellow: 2, green: 3 };
    return (order[a.severity] ?? 4) - (order[b.severity] ?? 4);
  });

  const critical = sorted.filter((a) => a.severity === "red" || a.severity === "orange");

  if (critical.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 p-4 text-center text-gray-400 text-sm">
        Sin alertas criticas
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {critical.map((alert) => (
        <Link
          key={alert.well_id}
          href={`/dashboard/${alert.well_id}`}
          className={`block border-l-4 rounded-r-lg p-3 ${SEVERITY_BORDER[alert.severity]} ${SEVERITY_BG[alert.severity]} transition hover:shadow-sm`}
        >
          <div className="flex justify-between items-start">
            <div>
              <span className="font-semibold text-sm text-gray-800">
                {alert.tag}
              </span>
              <p className="text-xs text-gray-600 mt-0.5">{alert.message}</p>
            </div>
            <div className="text-right shrink-0 ml-3">
              {alert.margin_pct !== null && (
                <span className="text-xs font-mono text-gray-500">
                  {alert.margin_pct >= 0 ? "+" : ""}
                  {alert.margin_pct.toFixed(1)}%
                </span>
              )}
              {alert.days_to_risk !== null && (
                <p className="text-xs text-gray-400">
                  ~{Math.round(alert.days_to_risk)}d a critico
                </p>
              )}
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}
