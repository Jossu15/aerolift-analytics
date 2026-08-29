"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { getWell, getLoading, getForecast, getCharts, getTraverse, getCalibration, postEconomics, postOilIpr, downloadReportPdf, uploadHistoryCsv, getTwins, getMlStatus, trainTwin } from "@/lib/api";
import type { Well, LoadingResult, ForecastResult, ChartsResult, TraverseResult, CalibrationResult, EconomicsResult, HistoryUploadResult, OilIprResult, Twin, MlStatus } from "@/lib/types";

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

type TabKey =
  | "resumen"
  | "forecast"
  | "carga"
  | "sensibilidad"
  | "traverse"
  | "nodal"
  | "calibracion"
  | "economia"
  | "ingenieria"
  | "petroleo"
  | "twin";

function figureTabs(well: Well, isPro: boolean): { key: TabKey; label: string }[] {
  const tabs: { key: TabKey; label: string }[] = [
    { key: "resumen", label: "Resumen" },
    { key: "forecast", label: "Pronostico" },
    { key: "carga", label: "Carga liquida" },
    { key: "sensibilidad", label: "Sensibilidad" },
    { key: "traverse", label: "Traverse" },
  ];
  if (isPro) {
    tabs.push({ key: "nodal", label: "Nodal" });
    tabs.push({ key: "calibracion", label: "Calibracion" });
    tabs.push({ key: "economia", label: "Economia" });
  }
  tabs.push({ key: "ingenieria", label: "Ingenieria" });
  if (well.well_type === "oil") {
    tabs.push({ key: "petroleo", label: "Petroleo" });
  }
  tabs.push({ key: "twin", label: "Digital Twin" });
  return tabs;
}

const inputCls =
  "w-full px-2 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400";

export default function WellDetailPage() {
  const params = useParams();
  const wellId = Number(params.wellId);

  const [well, setWell] = useState<Well | null>(null);
  const [loading, setLoading] = useState<LoadingResult | null>(null);
  const [forecast, setForecast] = useState<ForecastResult | null>(null);
  const [charts, setCharts] = useState<ChartsResult | null>(null);
  const [traverse, setTraverse] = useState<TraverseResult | null>(null);
  const [calibration, setCalibration] = useState<CalibrationResult | null>(null);
  const [histFile, setHistFile] = useState<File | null>(null);
  const [histBusy, setHistBusy] = useState(false);
  const [histMsg, setHistMsg] = useState<string | null>(null);
  const [histResult, setHistResult] = useState<HistoryUploadResult | null>(null);
  const [twins, setTwins] = useState<Twin[]>([]);
  const [mlStatus, setMlStatus] = useState<MlStatus | null>(null);
  const [twinBusy, setTwinBusy] = useState(false);
  const [twinMsg, setTwinMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingState, setLoadingState] = useState(true);
  const [tab, setTab] = useState<TabKey>("resumen");
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfMsg, setPdfMsg] = useState<string | null>(null);

  const [qOverride, setQOverride] = useState<number | null>(null);
  const [qDraft, setQDraft] = useState("");

  const [econ, setEcon] = useState<EconomicsResult | null>(null);
  const [econBusy, setEconBusy] = useState(false);
  const [econMsg, setEconMsg] = useState<string | null>(null);
  const [intervention, setIntervention] = useState("velocity_string");
  const [targetTubing, setTargetTubing] = useState("");
  const [targetPwh, setTargetPwh] = useState("");
  const [gasPrice, setGasPrice] = useState("3.5");
  const [costUsd, setCostUsd] = useState("");

  const [oilIpr, setOilIpr] = useState<OilIprResult | null>(null);
  const [oilBusy, setOilBusy] = useState(false);
  const [oilMsg, setOilMsg] = useState<string | null>(null);
  const [qoTest, setQoTest] = useState("");
  const [pwfTest, setPwfTest] = useState("");

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

  const loadRateData = useCallback(
    async (q?: number) => {
      const prm = q ?? undefined;
      try {
        const [l, c, t] = await Promise.all([
          getLoading(wellId, prm),
          getCharts(wellId, prm).catch(() => null),
          getTraverse(wellId, prm).catch(() => null),
        ]);
        setLoading(l);
        setCharts(c);
        setTraverse(t);
      } catch {
        /* keep old values */
      }
    },
    [wellId]
  );

  useEffect(() => {
    async function load() {
      try {
        const [w, f] = await Promise.all([
          getWell(wellId),
          getForecast(wellId).catch(() => null),
        ]);
        setWell(w);
        setForecast(f);
        setQDraft(w.q_gas_nominal_mscfd ? String(w.q_gas_nominal_mscfd) : "");
        getCalibration(wellId)
          .then(setCalibration)
          .catch(() => setCalibration(null));
        await loadRateData(w.q_gas_nominal_mscfd ?? undefined);
        refreshTwinCb().catch(() => undefined);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Error desconocido");
      } finally {
        setLoadingState(false);
      }
    }
    load();
  }, [wellId, refreshTwinCb, loadRateData]);

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

  const TABS = figureTabs(well, true);

  async function handlePdf() {
    setPdfBusy(true);
    setPdfMsg(null);
    try {
      await downloadReportPdf(wellId);
      setPdfMsg("Reporte PDF generado.");
    } catch (e: unknown) {
      setPdfMsg(e instanceof Error ? e.message : "No se pudo generar el PDF");
    } finally {
      setPdfBusy(false);
    }
  }

  function handleHistFile(e: React.ChangeEvent<HTMLInputElement>) {
    setHistFile(e.target.files?.[0] ?? null);
    setHistMsg(null);
    setHistResult(null);
  }

  async function handleUploadHistory() {
    if (!histFile) {
      setHistMsg("Selecciona un archivo CSV primero.");
      return;
    }
    setHistBusy(true);
    setHistMsg(null);
    try {
      const text = await histFile.text();
      const res = await uploadHistoryCsv(wellId, text);
      setHistResult(res);
      const cal = await getCalibration(wellId);
      setCalibration(cal);
      if (res.records_added > 0 && cal.n_points > 0) {
        setHistMsg(`Historial cargado: ${cal.n_points} filas con Pwf para calibrar.`);
      } else if (res.records_added > 0) {
        setHistMsg("Historial agregado, pero ninguna fila trae pwf_psia para calibrar.");
      } else {
        setHistMsg("No se agrego ninguna fila (revisa el formato del CSV).");
      }
    } catch (e: unknown) {
      setHistMsg(e instanceof Error ? e.message : "Error al subir el historial");
    } finally {
      setHistBusy(false);
    }
  }

  function downloadTemplate() {
    const pr = well?.p_res ?? 2400;
    const qn = well?.q_gas_nominal_mscfd ?? 900;
    const rows = [
      [qn, pr * 0.21],
      [qn - 10, pr * 0.215],
      [qn - 20, pr * 0.22],
    ];
    const csv =
      "date,q_gas_mscfd,pwf_psia,q_water_bpd,p_wh_psia\r\n" +
      rows.map(([q, pwf], i) => `2026-0${i + 1}-01,${q},${Math.round(pwf)},5,180`)
        .join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "historial_pwf_plantilla.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function applyRate() {
    const n = parseFloat(qDraft);
    if (!isNaN(n) && n > 0) {
      setQOverride(n);
      loadRateData(n);
    } else {
      setQOverride(null);
      loadRateData(well!.q_gas_nominal_mscfd ?? undefined);
    }
  }

  function resetRate() {
    setQDraft(well!.q_gas_nominal_mscfd ? String(well!.q_gas_nominal_mscfd) : "");
    setQOverride(null);
    loadRateData(well!.q_gas_nominal_mscfd ?? undefined);
  }

  async function handleEconomics() {
    if (!forecast?.history || forecast.history.length < 2) {
      setEconMsg("Se requiere pronostico con historial p/z para evaluar.");
      return;
    }
    setEconBusy(true);
    setEconMsg(null);
    try {
      const payload = {
        gp_mmscf: forecast.history.map((r) => r.Gp),
        p_psia: forecast.history.map((r) => r.Pr),
        intervention,
        target_tubing_id_in: intervention === "velocity_string" && targetTubing ? parseFloat(targetTubing) : null,
        target_p_wh_psia: intervention === "compression" && targetPwh ? parseFloat(targetPwh) : null,
        gas_price_usd_mcf: gasPrice ? parseFloat(gasPrice) : 3.5,
        cost_usd: costUsd ? parseFloat(costUsd) : null,
        time_step_days: 30,
      };
      const res = await postEconomics(wellId, payload);
      setEcon(res);
      setEconMsg(null);
    } catch (e: unknown) {
      setEconMsg(e instanceof Error ? e.message : "Error al evaluar economia");
    } finally {
      setEconBusy(false);
    }
  }

  async function handleOilIpr() {
    const qo = parseFloat(qoTest);
    const pwf = parseFloat(pwfTest);
    if (isNaN(qo) || qo <= 0 || isNaN(pwf) || pwf <= 0) {
      setOilMsg("Ingresa qo test y Pwf test validos.");
      return;
    }
    setOilBusy(true);
    setOilMsg(null);
    try {
      setOilIpr(await postOilIpr(wellId, qo, pwf));
    } catch (e: unknown) {
      setOilMsg(e instanceof Error ? e.message : "Error al calcular IPR de petroleo");
    } finally {
      setOilBusy(false);
    }
  }

  function renderFigure(fig: { data: unknown[]; layout: Record<string, unknown> } | null | undefined, height = 360) {
    if (!fig) return null;
    return (
      <Plot
        data={fig.data as never[]}
        layout={{
          autosize: true,
          height,
          margin: { l: 50, r: 20, t: 20, b: 40 },
          ...(fig.layout as object),
        }}
        config={{ responsive: true, displayModeBar: false }}
        style={{ width: "100%" }}
      />
    );
  }

  function figBlock(key: string, label: string) {
    if (!charts || !charts[key as keyof ChartsResult]) return null;
    return (
      <div key={key} className="bg-white rounded-lg border p-4">
        <h2 className="font-semibold text-gray-800 mb-3">{label}</h2>
        {renderFigure(charts[key as keyof ChartsResult] as never)}
      </div>
    );
  }

  const econFormat = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });

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
            <button
              onClick={handlePdf}
              disabled={pdfBusy}
              className="ml-auto px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-100 disabled:opacity-50 transition"
            >
              {pdfBusy ? "Generando..." : "Reporte PDF"}
            </button>
          </div>
          <p className="text-sm text-gray-500">
            ID {well.id} &middot; {well.well_type === "gas" ? "Gas" : "Petroleo"} &middot; TVD{" "}
            {well.tvd_ft} ft &middot; {well.tubing_id_in}&quot;
          </p>
          {pdfMsg && <p className="text-xs text-gray-500 mt-1">{pdfMsg}</p>}
        </header>

        <div className="flex flex-wrap items-center gap-3 mb-4 p-3 bg-white rounded-lg border">
          <label className="text-sm font-medium text-gray-600">Tasa de gas q (Mscf/D):</label>
          <input
            type="number"
            value={qDraft}
            onChange={(e) => setQDraft(e.target.value)}
            className={`${inputCls} w-32`}
            placeholder="nominal"
          />
          <button
            onClick={applyRate}
            className="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition"
          >
            Aplicar
          </button>
          <button
            onClick={resetRate}
            className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-100 transition"
          >
            Reset
          </button>
          {qOverride !== null && (
            <span className="text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded px-2 py-1">
              Analizando a {qOverride.toFixed(0)} Mscf/D
            </span>
          )}
        </div>

        <nav className="flex gap-1 mb-6 border-b border-gray-200 overflow-x-auto">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2 -mb-px text-sm font-medium border-b-2 whitespace-nowrap transition ${
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
            {figBlock("operating_envelope", "Envolvente operativa")}
            {!charts && (
              <div className="bg-white rounded-lg border p-6 text-center text-gray-400 text-sm">
                Graficas no disponibles para este pozo.
              </div>
            )}
          </div>
        )}

        {tab === "sensibilidad" && (
          <div className="space-y-6">
            {[["vcrit vs presion", "vcrit_vs_pressure"],
              ["vcrit vs temperatura", "vcrit_vs_temperature"],
              ["vcrit vs diametro", "vcrit_vs_diameter"]].map(([label, key]) =>
                figBlock(key, label)
            )}
            {!charts && (
              <div className="bg-white rounded-lg border p-6 text-center text-gray-400 text-sm">
                Graficas no disponibles para este pozo.
              </div>
            )}
          </div>
        )}

        {tab === "traverse" && traverse && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm mb-2">
              <div className="bg-white rounded-lg border p-3">
                <span className="text-gray-400">BHP dry gas</span>
                <p className="font-mono font-medium">{traverse.bhfp_dry_gas_psia.toFixed(0)} psia</p>
              </div>
              <div className="bg-white rounded-lg border p-3">
                <span className="text-gray-400">BHP Beggs-Brill</span>
                <p className="font-mono font-medium">
                  {traverse.bhfp_beggs_brill_psia !== null
                    ? `${traverse.bhfp_beggs_brill_psia.toFixed(0)} psia`
                    : "n/a"}
                </p>
              </div>
            </div>

            <div className="bg-white rounded-lg border p-4">
              <h2 className="font-semibold text-gray-800 mb-3">Presion vs profundidad</h2>
              <Plot
                data={[
                  {
                    x: traverse.P_dry_gas_psia,
                    y: traverse.depths_ft,
                    type: "scatter",
                    mode: "lines",
                    name: "Dry gas",
                    line: { color: "#2563eb" },
                  },
                  ...(traverse.P_beggs_brill_psia
                    ? [
                        {
                          x: traverse.P_beggs_brill_psia,
                          y: traverse.depths_ft,
                          type: "scatter",
                          mode: "lines",
                          name: "Beggs-Brill",
                          line: { color: "#db2777", dash: "dash" },
                        } as never,
                      ]
                    : []),
                ]}
                layout={{
                  autosize: true,
                  height: 420,
                  margin: { l: 50, r: 20, t: 20, b: 40 },
                  xaxis: { title: "Presion (psia)", autorange: "reversed" },
                  yaxis: { title: "Profundidad (ft)", autorange: "reversed" },
                  legend: { orientation: "h", y: 1.1 },
                }}
                config={{ responsive: true, displayModeBar: false }}
                style={{ width: "100%" }}
              />
            </div>

            {traverse.bb_flow_patterns && (
              <div className="bg-white rounded-lg border p-4">
                <h2 className="font-semibold text-gray-800 mb-3">Patrones de flujo (Beggs-Brill)</h2>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                  {Object.entries(traverse.bb_flow_patterns).map(([k, v]) => (
                    <div key={k}>
                      <span className="text-gray-400 text-xs">{k}</span>
                      <p className="font-mono text-gray-800">{v}%</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {tab === "traverse" && !traverse && (
          <div className="bg-white rounded-lg border p-6 text-center text-gray-400 text-sm">
            Traverse no disponible para este pozo.
          </div>
        )}

        {tab === "nodal" && (
          <div className="space-y-6">
            {figBlock("pz", "Balance de materiales p/z")}
            {figBlock("deliverability_loglog", "Deliverability (log-log)")}
            {!charts?.pz && !charts?.deliverability_loglog && (
              <div className="bg-white rounded-lg border p-6 text-center text-gray-400 text-sm">
                Nodal no disponible para este pozo.
              </div>
            )}
          </div>
        )}

        {tab === "calibracion" && (
          <div className="space-y-6">
            <div className="bg-white rounded-lg border p-4">
              <h2 className="font-semibold text-gray-800 mb-2">
                Cargar historial de produccion para calibrar
              </h2>
              <p className="text-sm text-gray-500 mb-3">
                Sube un CSV con columnas <code className="font-mono">date</code>,{" "}
                <code className="font-mono">q_gas_mscfd</code> y{" "}
                <code className="font-mono">pwf_psia</code> (alias: fecha, q_gas,
                gas_rate, tasa_gas, pwf, bhfp, presion_fondo). Las filas con Pwf seran
                comparadas contra el VLP calculado.
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={handleHistFile}
                  className="text-sm text-gray-600 file:mr-3 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-blue-50 file:text-blue-700 file:text-sm file:font-medium hover:file:bg-blue-100"
                />
                <button
                  onClick={handleUploadHistory}
                  disabled={histBusy}
                  className="px-3 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition"
                >
                  {histBusy ? "Subiendo..." : "Subir y calibrar"}
                </button>
                <button
                  onClick={downloadTemplate}
                  className="px-3 py-2 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-100 transition"
                >
                  Descargar plantilla
                </button>
              </div>
              {histMsg && (
                <p className="text-sm text-gray-700 bg-gray-50 border rounded-lg px-3 py-2 mt-3">
                  {histMsg}
                </p>
              )}
              {histResult && histResult.records_skipped > 0 && (
                <div className="mt-3 px-3 py-2 bg-amber-50 border border-amber-300 rounded-lg text-sm text-amber-800">
                  <p>
                    {histResult.records_added} agregadas, {histResult.records_skipped}{" "}
                    omitidas.
                  </p>
                  {histResult.errors.slice(0, 5).map((err, i) => (
                    <p key={i} className="text-xs mt-1">
                      {err}
                    </p>
                  ))}
                </div>
              )}
            </div>

            {calibration?.note && (
              <div className="px-4 py-3 bg-amber-50 border border-amber-300 rounded-lg text-sm text-amber-800">
                {calibration.note}
              </div>
            )}

            {calibration && calibration.n_points > 0 && (
              <>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
                  <div className="bg-white rounded-lg border p-3">
                    <span className="text-gray-400">Puntos</span>
                    <p className="font-mono font-medium">{calibration.n_points}</p>
                  </div>
                  <div className="bg-white rounded-lg border p-3">
                    <span className="text-gray-400">Bias</span>
                    <p className="font-mono font-medium">
                      {calibration.bias_pct !== null
                        ? `${calibration.bias_pct.toFixed(1)}%`
                        : "n/a"}
                    </p>
                  </div>
                  <div className="bg-white rounded-lg border p-3">
                    <span className="text-gray-400">MAE</span>
                    <p className="font-mono font-medium">
                      {calibration.mae_pct !== null
                        ? `${calibration.mae_pct.toFixed(1)}%`
                        : "n/a"}
                    </p>
                  </div>
                </div>

                <div className="bg-white rounded-lg border p-4">
                  <h2 className="font-semibold text-gray-800 mb-3">Medido vs predicho</h2>
                  <Plot
                    data={[
                      {
                        x: calibration.points
                          .filter((p) => p.pwf_predicted_psia !== null)
                          .map((p) => p.pwf_measured_psia),
                        y: calibration.points
                          .filter((p) => p.pwf_predicted_psia !== null)
                          .map((p) => p.pwf_predicted_psia as number),
                        type: "scatter",
                        mode: "markers",
                        name: "Predicciones",
                        marker: { color: "#2563eb", size: 7 },
                      },
                      {
                        x: [
                          Math.min(...calibration.points.map((p) => p.pwf_measured_psia)) * 0.9,
                          Math.max(...calibration.points.map((p) => p.pwf_measured_psia)) * 1.1,
                        ],
                        y: [
                          Math.min(...calibration.points.map((p) => p.pwf_measured_psia)) * 0.9,
                          Math.max(...calibration.points.map((p) => p.pwf_measured_psia)) * 1.1,
                        ],
                        type: "scatter",
                        mode: "lines",
                        name: "1:1",
                        line: { color: "#ef4444", dash: "dash" },
                      },
                    ]}
                    layout={{
                      autosize: true,
                      height: 380,
                      margin: { l: 50, r: 20, t: 20, b: 40 },
                      xaxis: { title: "Pwf medido (psia)" },
                      yaxis: { title: "Pwf predicho (psia)" },
                      legend: { orientation: "h", y: 1.1 },
                    }}
                    config={{ responsive: true, displayModeBar: false }}
                    style={{ width: "100%" }}
                  />
                </div>

                <div className="bg-white rounded-lg border p-4">
                  <h2 className="font-semibold text-gray-800 mb-3">Delta vs fecha</h2>
                  <Plot
                    data={[
                      {
                        x: calibration.points.map((p) => p.date),
                        y: calibration.points.map((p) => p.delta_pct),
                        type: "bar",
                        name: "Delta (%)",
                        marker: { color: "#f59e0b" },
                      },
                    ]}
                    layout={{
                      autosize: true,
                      height: 300,
                      margin: { l: 50, r: 20, t: 20, b: 40 },
                      xaxis: { title: "Fecha" },
                      yaxis: { title: "Desvio (%)" },
                    }}
                    config={{ responsive: true, displayModeBar: false }}
                    style={{ width: "100%" }}
                  />
                </div>
              </>
            )}
          </div>
        )}

        {tab === "economia" && (
          <div className="space-y-6">
            <div className="bg-white rounded-lg border p-4">
              <h2 className="font-semibold text-gray-800 mb-3">Evaluacion de intervencion</h2>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-gray-400 text-xs">Intervencion</span>
                  <select
                    value={intervention}
                    onChange={(e) => setIntervention(e.target.value)}
                    className={inputCls}
                  >
                    <option value="velocity_string">Velocity string</option>
                    <option value="compression">Compresion</option>
                  </select>
                </div>
                {intervention === "velocity_string" ? (
                  <div>
                    <span className="text-gray-400 text-xs">Target tubing ID (in)</span>
                    <input
                      type="number"
                      value={targetTubing}
                      onChange={(e) => setTargetTubing(e.target.value)}
                      className={inputCls}
                      placeholder="ej. 1.9"
                    />
                  </div>
                ) : (
                  <div>
                    <span className="text-gray-400 text-xs">Target Pwh (psia)</span>
                    <input
                      type="number"
                      value={targetPwh}
                      onChange={(e) => setTargetPwh(e.target.value)}
                      className={inputCls}
                      placeholder="ej. 100"
                    />
                  </div>
                )}
                <div>
                  <span className="text-gray-400 text-xs">Precio gas ($/Mscf)</span>
                  <input
                    type="number"
                    value={gasPrice}
                    onChange={(e) => setGasPrice(e.target.value)}
                    className={inputCls}
                  />
                </div>
                <div>
                  <span className="text-gray-400 text-xs">Costo ($, opcional)</span>
                  <input
                    type="number"
                    value={costUsd}
                    onChange={(e) => setCostUsd(e.target.value)}
                    className={inputCls}
                    placeholder="default del catalogo"
                  />
                </div>
              </div>
              <button
                onClick={handleEconomics}
                disabled={econBusy || !forecast}
                className="mt-4 px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition"
              >
                {econBusy ? "Evaluando..." : "Evaluar"}
              </button>
              {econMsg && <p className="text-sm text-gray-600 mt-2">{econMsg}</p>}
            </div>

            {econ && (
              <>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                  {[
                    ["Intervencion", econ.label],
                    ["Gas incremental", `${econ.incremental_gas_mmscf.toFixed(1)} MMscf`],
                    ["Ingreso bruto", econFormat.format(econ.gross_revenue_usd)],
                    ["NPV", econFormat.format(econ.npv_usd)],
                    ["ROI", econ.roi_pct !== null ? `${econ.roi_pct.toFixed(0)}%` : "n/a"],
                    ["Payback", econ.payback_months !== null ? `${econ.payback_months} meses` : "n/a"],
                    ["Costo", econFormat.format(econ.cost_usd)],
                    ["Extension de vida", econ.life_extension_days !== null ? `${econ.life_extension_days.toFixed(0)} dias` : "n/a"],
                  ].map(([label, value]) => (
                    <div key={label} className="bg-white rounded-lg border p-3">
                      <span className="text-gray-400 text-xs">{label}</span>
                      <p className="font-mono font-medium">{value}</p>
                    </div>
                  ))}
                </div>

                <div className="bg-white rounded-lg border p-4">
                  <h2 className="font-semibold text-gray-800 mb-3">Produccion acumulada</h2>
                  <Plot
                    data={[
                      {
                        x: ["Base", "Con " + econ.intervention],
                        y: [econ.base_cum_mmscf, econ.intervention_cum_mmscf],
                        type: "bar",
                        marker: { color: ["#94a3b8", "#2563eb"] },
                      },
                    ]}
                    layout={{
                      autosize: true,
                      height: 300,
                      margin: { l: 50, r: 20, t: 20, b: 40 },
                      yaxis: { title: "Producido (MMscf)" },
                    }}
                    config={{ responsive: true, displayModeBar: false }}
                    style={{ width: "100%" }}
                  />
                </div>
              </>
            )}
          </div>
        )}

        {tab === "ingenieria" && (
          <div className="space-y-6">
            <h2 className="text-lg font-semibold text-gray-800">Ingenieria de fondo de pozo</h2>
            {[
              ["Perfil de temperatura", "temperature_profile"],
              ["Comparacion de modelos de carga", "multi_model_comparison"],
              ["Envolvente de Belfroid", "belfroid_envelope"],
              ["Velocidad erosional (API RP 14E)", "erosional_velocity"],
              ["Curva de hidratos", "hydrate_curve"],
              ["Curvas tipo de declinacion", "decline_type_curves"],
            ].map(([label, key]) => figBlock(key, label))}
            {!charts && (
              <div className="bg-white rounded-lg border p-6 text-center text-gray-400 text-sm">
                Figuras no disponibles para este pozo.
              </div>
            )}
          </div>
        )}

        {tab === "petroleo" && (
          <div className="space-y-6">
            <div className="bg-white rounded-lg border p-4">
              <h2 className="font-semibold text-gray-800 mb-3">IPR de petroleo (Vogel)</h2>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-400 text-xs">qo test (STB/D)</span>
                  <input
                    type="number"
                    value={qoTest}
                    onChange={(e) => setQoTest(e.target.value)}
                    className={inputCls}
                  />
                </div>
                <div>
                  <span className="text-gray-400 text-xs">Pwf test (psia)</span>
                  <input
                    type="number"
                    value={pwfTest}
                    onChange={(e) => setPwfTest(e.target.value)}
                    className={inputCls}
                  />
                </div>
              </div>
              <button
                onClick={handleOilIpr}
                disabled={oilBusy}
                className="mt-4 px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition"
              >
                {oilBusy ? "Calculando..." : "Calcular"}
              </button>
              {oilMsg && <p className="text-sm text-gray-600 mt-2">{oilMsg}</p>}
            </div>

            {oilIpr && (
              <>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                  {[
                    ["qo max", `${oilIpr.qo_max_stb_d.toFixed(0)} STB/D`],
                    ["Pb", oilIpr.p_bubble_psia !== null ? `${oilIpr.p_bubble_psia.toFixed(0)} psia` : "n/a"],
                    ["Rs", oilIpr.rs_at_p_res_scf_stb !== null ? `${oilIpr.rs_at_p_res_scf_stb.toFixed(0)} scf/STB` : "n/a"],
                    ["mu_o", oilIpr.mu_o_cp !== null ? `${oilIpr.mu_o_cp.toFixed(2)} cp` : "n/a"],
                  ].map(([label, value]) => (
                    <div key={label} className="bg-white rounded-lg border p-3">
                      <span className="text-gray-400 text-xs">{label}</span>
                      <p className="font-mono font-medium">{value}</p>
                    </div>
                  ))}
                </div>
                {oilIpr.warnings.length > 0 && (
                  <div className="px-4 py-3 bg-amber-50 border border-amber-300 rounded-lg text-sm text-amber-800">
                    {oilIpr.warnings.join("; ")}
                  </div>
                )}
                {oilIpr.curve.length > 0 && (
                  <div className="bg-white rounded-lg border p-4">
                    <h2 className="font-semibold text-gray-800 mb-3">Curva de afluencia (Vogel)</h2>
                    <Plot
                      data={[
                        {
                          x: oilIpr.curve.map((pt) => pt.qo_stb_d),
                          y: oilIpr.curve.map((pt) => pt.pwf_psia),
                          type: "scatter",
                          mode: "lines",
                          line: { color: "#2563eb" },
                        },
                      ]}
                      layout={{
                        autosize: true,
                        height: 360,
                        margin: { l: 50, r: 20, t: 20, b: 40 },
                        xaxis: { title: "qo (STB/D)", autorange: "reversed" },
                        yaxis: { title: "Pwf (psia)" },
                      }}
                      config={{ responsive: true, displayModeBar: false }}
                      style={{ width: "100%" }}
                    />
                  </div>
                )}
              </>
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