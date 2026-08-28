"""Physics analyses over stored wells: loading, nodal, traverse,
forecast, calibration, economics, PDF report."""

import datetime
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api import crud, engines, models
from api.auth import get_current_key, owns_well, require_tier
from api.database import get_db
from math_engine import economics as econ_engine
from math_engine import oil_pvt
from math_engine.artificial_lift import rod_pump_check, size_esp
from math_engine.charts import (
    plot_operating_envelope,
    plot_vcrit_vs_pressure,
    plot_vcrit_vs_temperature,
    plot_vcrit_vs_diameter,
)

router = APIRouter(prefix="/api/wells/{well_id}/analysis", tags=["analysis"])


def _well_or_404(db: Session, well_id: int, key: models.ApiKey):
    well = crud.get_well(db, well_id)
    if well is None or not owns_well(well, key):
        raise HTTPException(404, "well {} not found".format(well_id))
    return well


class LoadingOut(BaseModel):
    is_loading: bool
    margin_pct: Optional[float] = None
    severity: str
    headline: str
    first_action: Optional[str] = None
    bhfp_psia: Optional[float] = None
    v_actual_ft_s: float
    v_crit_ft_s: float
    q_crit_mscfd: float
    metastable_regime: str = "stable"
    q_min_stable_mscfd: Optional[float] = None
    film_reynolds: Optional[float] = None


class Intersection(BaseModel):
    q_mscfd: float
    Pwf_psia: float


class NodalOut(BaseModel):
    ipr_source: str
    ipr_params: dict
    natural_q_mscfd: Optional[float] = None
    natural_pwf_psia: Optional[float] = None
    all_intersections: List[Intersection] = []
    instability_note: Optional[str] = None
    flows_naturally: bool


class TraverseOut(BaseModel):
    depths_ft: List[float]
    P_dry_gas_psia: List[float]
    bhfp_dry_gas_psia: float
    P_beggs_brill_psia: Optional[List[float]] = None
    bhfp_beggs_brill_psia: Optional[float] = None
    bb_flow_patterns: Optional[dict] = None


class ChartFigure(BaseModel):
    """Plotly figure serialized as JSON (data + layout keys)."""
    data: list
    layout: dict


class ChartsOut(BaseModel):
    well_id: int
    operating_envelope: ChartFigure
    vcrit_vs_pressure: ChartFigure
    vcrit_vs_temperature: ChartFigure
    vcrit_vs_diameter: ChartFigure


class ForecastIn(BaseModel):
    gp_mmscf: List[float] = Field(min_length=2)
    p_psia: List[float] = Field(min_length=2)
    time_step_days: int = Field(default=30, ge=1, le=365)
    max_steps: int = Field(default=36, ge=2, le=240)


class ForecastRow(BaseModel):
    day: float
    Gp: float
    Pr: float
    q_mscfd: float
    Pwf: Optional[float] = None
    status: str


class ForecastOut(BaseModel):
    ogip_mmscf: float
    pi_over_zi_psia: float
    mb_slope: float
    days_to_risk: Optional[int] = None
    history: List[ForecastRow]
    preview: Optional[bool] = False
    note: Optional[str] = None


class CalibrationPoint(BaseModel):
    date: str
    q_gas_mscfd: float
    pwf_measured_psia: float
    pwf_predicted_psia: Optional[float] = None
    delta_pct: Optional[float] = None


class CalibrationOut(BaseModel):
    """VLP calibration check: engine BHFP vs measured BHFP."""
    n_points: int
    bias_pct: Optional[float] = None   # mean (pred - meas)/meas * 100
    mae_pct: Optional[float] = None
    points: List[CalibrationPoint] = []
    note: Optional[str] = None


class EconomicsIn(BaseModel):
    gp_mmscf: List[float] = Field(min_length=2)
    p_psia: List[float] = Field(min_length=2)
    intervention: str = "velocity_string"
    target_tubing_id_in: Optional[float] = Field(default=None, gt=0.5,
                                                 lt=3.0)
    target_p_wh_psia: Optional[float] = Field(default=None, gt=0)
    gas_price_usd_mcf: float = Field(default=3.5, gt=0, le=50)
    cost_usd: Optional[float] = Field(default=None, gt=0)
    time_step_days: int = Field(default=30, ge=1, le=365)


class EconomicsOut(BaseModel):
    intervention: str
    label: str
    cost_usd: float
    base_death_day: Optional[float] = None
    intervention_death_day: Optional[float] = None
    life_extension_days: Optional[float] = None
    base_cum_mmscf: float
    intervention_cum_mmscf: float
    incremental_gas_mmscf: float
    gross_revenue_usd: float
    npv_usd: float
    roi_pct: Optional[float] = None
    payback_months: Optional[int] = None


@router.get("/loading", response_model=LoadingOut)
def loading(well_id: int,
            q_gas_mscfd: Optional[float] = None,
            key: models.ApiKey = Depends(get_current_key),
            db: Session = Depends(get_db)):
    """Turner/Coleman verdict; defaults to the well's nominal rate."""
    well = _well_or_404(db, well_id, key)
    q = q_gas_mscfd if q_gas_mscfd is not None else \
        (well.q_gas_nominal_mscfd or 0.0)
    if q <= 0:
        raise HTTPException(422,
                            "no gas rate available (pass ?q_gas_mscfd=)")
    return engines.loading_snapshot(well, q)


@router.get("/nodal", response_model=NodalOut)
def nodal(well_id: int, key: models.ApiKey = Depends(require_tier("pro")),
          db: Session = Depends(get_db)):
    """IPR/VLP intersections - flags the liquid-loading J-curve signature."""
    well = _well_or_404(db, well_id, key)
    result, spec = engines.natural_flow_point(db, well)
    out = NodalOut(ipr_source=spec[0], ipr_params=spec[1],
                   flows_naturally=result is not None)
    if result:
        out.natural_q_mscfd = result["q_mscfd"]
        out.natural_pwf_psia = result["Pwf_psia"]
        out.all_intersections = [
            Intersection(q_mscfd=p["q_mscfd"], Pwf_psia=p["Pwf_psia"])
            for p in result["all_intersections"]]
        if "note" in result:
            out.instability_note = result["note"]
    return out


@router.get("/traverse", response_model=TraverseOut)
def traverse(well_id: int, q_gas_mscfd: Optional[float] = None,
             n_segments: int = 40,
             key: models.ApiKey = Depends(get_current_key),
             db: Session = Depends(get_db)):
    """Pressure vs depth profile at the given (or nominal) rate."""
    well = _well_or_404(db, well_id, key)
    if not (5 <= n_segments <= 200):
        raise HTTPException(422, "n_segments must be in [5, 200]")
    q = q_gas_mscfd if q_gas_mscfd is not None else \
        (well.q_gas_nominal_mscfd or 0.0)
    if q <= 0:
        raise HTTPException(422,
                            "no gas rate available (pass ?q_gas_mscfd=)")
    return engines.pressure_traverse(well, q, n_segments=n_segments)


@router.get("/charts", response_model=ChartsOut)
def charts(well_id: int, q_gas_mscfd: Optional[float] = None,
           key: models.ApiKey = Depends(get_current_key),
           db: Session = Depends(get_db)):
    """The four liquid-loading drill-down charts as Plotly figures.

    Each figure serializes to ``{"data": [...], "layout": {...}}`` so
    react-plotly.js can consume it directly.
    """
    well = _well_or_404(db, well_id, key)
    q = q_gas_mscfd if q_gas_mscfd is not None else \
        (well.q_gas_nominal_mscfd or 0.0)
    if q <= 0:
        raise HTTPException(422,
                            "no gas rate available (pass ?q_gas_mscfd=)")
    t_res_r = float(well.t_res_f) + 460.0
    result, _spec = engines.natural_flow_point(db, well)
    bhp_eval = result["Pwf_psia"] if result else \
        float(well.p_wh if well.p_wh else 200.0)

    def _fig(fig):
        payload = json.loads(fig.to_json())
        return ChartFigure(data=payload["data"], layout=payload["layout"])

    return ChartsOut(
        well_id=well.id,
        operating_envelope=_fig(plot_operating_envelope(
            float(well.p_res), t_res_r, float(well.gamma_g),
            float(well.tubing_id_in), q_actual=q,
            liquid_type="water", method=well.load_method)),
        vcrit_vs_pressure=_fig(plot_vcrit_vs_pressure(
            t_res_r, float(well.gamma_g), float(well.tubing_id_in),
            "water", well.load_method)),
        vcrit_vs_temperature=_fig(plot_vcrit_vs_temperature(
            bhp_eval, float(well.gamma_g), float(well.tubing_id_in),
            "water", well.load_method)),
        vcrit_vs_diameter=_fig(plot_vcrit_vs_diameter(
            bhp_eval, t_res_r, float(well.gamma_g),
            "water", well.load_method)),
    )


@router.post("/forecast", response_model=ForecastOut)
def forecast(well_id: int, payload: ForecastIn,
             key: models.ApiKey = Depends(require_tier("pro")),
             db: Session = Depends(get_db)):
    """p/z material-balance decline + days-until-loading health score."""
    well = _well_or_404(db, well_id, key)
    if len(payload.gp_mmscf) != len(payload.p_psia):
        raise HTTPException(422,
                            "gp_mmscf and p_psia must have equal length")
    if any(p2 >= p1 for p1, p2 in zip(payload.p_psia,
                                      payload.p_psia[1:])):
        raise HTTPException(422,
                            "p_psia must be strictly decreasing")
    try:
        result = engines.forecast_from_history(
            db, well, payload.gp_mmscf, payload.p_psia,
            time_step_days=payload.time_step_days,
            max_steps=payload.max_steps)
    except ValueError as exc:
        raise HTTPException(422, "material balance fit failed: {}".format(exc))
    return ForecastOut(**result)


@router.get("/forecast-view", response_model=ForecastOut)
def forecast_view(well_id: int, max_steps: int = 60,
                  key: models.ApiKey = Depends(require_tier("pro")),
                  db: Session = Depends(get_db)):
    """Dashboard preview declaration built from the well's own parameters
    (no p/z history required). Same physics as POST /forecast."""
    well = _well_or_404(db, well_id, key)
    if not (30 <= max_steps <= 240):
        raise HTTPException(422, "max_steps must be in [30, 240]")
    return engines.forecast_view(db, well, max_steps=max_steps)


@router.get("/calibration", response_model=CalibrationOut)
def calibration(well_id: int,
                key: models.ApiKey = Depends(require_tier("pro")),
                db: Session = Depends(get_db)):
    """
    Compare the engine's VLP against measured BHFPs from history rows
    that carry a pwf column (CSV alias: pwf/p_wf/bhfp/presion_fondo).
    bias > 0 means the correlation over-predicts the required BHFP.
    """
    well = _well_or_404(db, well_id, key)
    recs = [r for r in crud.list_production(db, well.id) if r.pwf_psia]
    if not recs:
        return CalibrationOut(
            n_points=0,
            note="no measured Pwf rows - upload history CSV with a "
                 "pwf_psia column to calibrate")

    vlp = engines.build_vlp_func(well)
    points, deltas = [], []
    for r in recs:
        try:
            pred = vlp(float(r.q_gas_mscfd))
        except Exception:
            pred = None
        delta = ((pred - r.pwf_psia) / r.pwf_psia * 100.0
                 if pred is not None else None)
        if delta is not None:
            deltas.append(delta)
        points.append(CalibrationPoint(
            date=r.date, q_gas_mscfd=r.q_gas_mscfd,
            pwf_measured_psia=float(r.pwf_psia),
            pwf_predicted_psia=pred, delta_pct=delta))

    return CalibrationOut(
        n_points=len(points),
        bias_pct=sum(deltas) / len(deltas) if deltas else None,
        mae_pct=(sum(abs(d) for d in deltas) / len(deltas)
                 if deltas else None),
        points=points)


@router.post("/economics", response_model=EconomicsOut)
def economics(well_id: int, payload: EconomicsIn,
              key: models.ApiKey = Depends(require_tier("pro")),
              db: Session = Depends(get_db)):
    """
    What-if economics of an intervention, re-running the full physics
    forecast on the modified completion:

        velocity_string -> smaller tubing ID (higher velocity)
        compression     -> lower wellhead pressure (more drawdown)

    Incremental gas vs the do-nothing baseline is valued at
    gas_price_usd_mcf and discounted against the intervention cost.
    """
    well = _well_or_404(db, well_id, key)
    if len(payload.gp_mmscf) != len(payload.p_psia):
        raise HTTPException(422, "gp_mmscf and p_psia length mismatch")
    if any(p2 >= p1 for p1, p2 in zip(payload.p_psia,
                                      payload.p_psia[1:])):
        raise HTTPException(422, "p_psia must be strictly decreasing")

    params = {
        "p_wh": float(well.p_wh),
        "t_wh_f": float(well.t_wh_f),
        "t_res_f": float(well.t_res_f),
        "tvd_ft": float(well.tvd_ft),
        "tubing_id_in": float(well.tubing_id_in),
        "gamma_g": float(well.gamma_g),
        "q_water_bpd": float(well.q_water_bpd or 0.0),
        "liquid_sg": float(well.liquid_sg),
        "vlp_model": well.vlp_model,
        "load_method": well.load_method,
        "friction_multiplier":
            float(getattr(well, "friction_multiplier", None) or 1.0),
        "q_gas_nominal_mscfd": float(well.q_gas_nominal_mscfd or 0.0),
        "ipr": engines.ipr_spec(db, well),
    }
    try:
        result = econ_engine.evaluate_intervention(
            params, payload.gp_mmscf, payload.p_psia, payload.intervention,
            gas_price_usd_mcf=payload.gas_price_usd_mcf,
            cost_usd=payload.cost_usd,
            time_step_days=float(payload.time_step_days),
            target_tubing_id_in=payload.target_tubing_id_in,
            target_p_wh_psia=payload.target_p_wh_psia)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return EconomicsOut(**result)


def _csv_floats(text: Optional[str]) -> Optional[List[float]]:
    if not text:
        return None
    try:
        vals = [float(x) for x in
                str(text).replace(";", ",").split(",") if x.strip()]
    except ValueError:
        return None
    return vals if len(vals) >= 2 else None


@router.get("/report.pdf")
def report_pdf(well_id: int,
               gp: Optional[str] = Query(default=None,
                                         description="comma Gp MMscf"),
               p: Optional[str] = Query(default=None,
                                        description="comma P psia"),
               key: models.ApiKey = Depends(require_tier("pro")),
               db: Session = Depends(get_db)):
    """One-page PDF summary (loading verdict, nodal, forecast)."""
    from math_engine.reporting import build_report

    well = _well_or_404(db, well_id, key)
    sections = [("Datos del pozo", [
        "Tag: {}   Nombre: {}".format(well.tag, well.name or "-"),
        "P_res {:.0f} psia | T_res {:.0f} F | gamma_g {:.2f}".format(
            well.p_res, well.t_res_f, well.gamma_g),
        "TVD {:.0f} ft | ID {:.3f} in | P_wh {:.0f} psia | "
        "agua {:.0f} bbl/D".format(well.tvd_ft, well.tubing_id_in,
                                   well.p_wh, well.q_water_bpd or 0.0),
        "VLP {} | metodo {} | friccion x{:.2f}".format(
            well.vlp_model, well.load_method,
            float(getattr(well, "friction_multiplier", None) or 1.0)),
    ])]

    q_nom = well.q_gas_nominal_mscfd or 0.0
    if q_nom > 0:
        snap = engines.loading_snapshot(well, q_nom)
        margin = snap["margin_pct"]
        sections.append((
            "Liquid loading @ nominal {:.0f} Mscf/D".format(q_nom), [
                "Veredicto: {}".format("CARGANDO" if snap["is_loading"]
                                       else "Estable"),
                "Severidad: {} | margen: {}".format(
                    snap["severity"],
                    "{:.0f}%".format(margin) if margin is not None
                    else "n/a"),
                "v_actual {:.2f} vs v_critico {:.2f} ft/s | q_critico "
                "{:.0f} Mscf/D".format(snap["v_actual_ft_s"],
                                       snap["v_crit_ft_s"],
                                       snap["q_crit_mscfd"]),
                "Accion sugerida: {}".format(snap["first_action"] or "-"),
            ]))

    try:
        result, _spec = engines.natural_flow_point(db, well)
        lines = []
        if result:
            lines.append("Punto natural: q={:.0f} Mscf/D @ Pwf={:.0f} psia"
                         .format(result["q_mscfd"], result["Pwf_psia"]))
            for itp in result["all_intersections"]:
                lines.append("Interseccion IPR-VLP: q={:.0f} Mscf/D @ "
                             "Pwf={:.0f} psia".format(itp["q_mscfd"],
                                                      itp["Pwf_psia"]))
            if "note" in result:
                lines.append("Nota: {}".format(result["note"]))
        else:
            lines.append("Sin flujo natural con la configuracion actual")
        sections.append(("Analisis nodal (IPR/VLP)", lines))
    except Exception as exc:
        sections.append(("Analisis nodal", ["no disponible: {}".format(exc)]))

    gp_list, p_list = _csv_floats(gp), _csv_floats(p)
    if gp_list and p_list and len(gp_list) == len(p_list):
        try:
            fc = engines.forecast_from_history(db, well, gp_list, p_list)
            lines = ["OGIP ~{:.0f} MMscf | Pi/Zi {:.0f} psia".format(
                fc["ogip_mmscf"], fc["pi_over_zi_psia"])]
            days = fc["days_to_risk"]
            lines.append("Dias hasta riesgo de loading: {}".format(
                days if days is not None else "sin muerte en horizonte"))
            step = max(1, len(fc["history"]) // 6)
            for row in fc["history"][::step][:6]:
                lines.append("dia {:5.0f} | Pr {:5.0f} psia | q {:5.0f} "
                             "Mscf/D -> {}".format(row["day"], row["Pr"],
                                                   row["q_mscfd"],
                                                   row["status"]))
            sections.append(("Pronostico p/z + health score", lines))
        except ValueError as exc:
            sections.append(("Pronostico p/z",
                             ["datos invalidos: {}".format(exc)]))

    pdf_bytes = build_report(
        "AeroLift Analytics - Reporte de pozo",
        "{} | generado {}".format(well.tag,
                                  datetime.date.today().isoformat()),
        sections)
    filename = "aerolift_well_{}.pdf".format(well_id)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition":
                             'inline; filename="{}"'.format(filename)})


# ------------------------------------------------------------------
# Oil wells (Fase I): Vogel IPR + artificial-lift screening
# ------------------------------------------------------------------
class OilIprIn(BaseModel):
    qo_test_stb_d: float = Field(gt=0)
    pwf_test_psia: float = Field(gt=0)


class OilCurvePoint(BaseModel):
    pwf_psia: float
    qo_stb_d: float


class OilIprOut(BaseModel):
    p_bubble_psia: Optional[float] = None
    rs_at_p_res_scf_stb: Optional[float] = None
    mu_o_cp: Optional[float] = None
    qo_max_stb_d: float
    curve: List[OilCurvePoint] = []
    warnings: List[str] = []


class EspIn(BaseModel):
    qo_test_stb_d: float = Field(gt=0)
    pwf_test_psia: float = Field(gt=0)
    target_rate_stb_d: float = Field(gt=0)
    water_cut: float = Field(ge=0.0, le=1.0)
    thp_psia: float = Field(default=100.0, ge=0)
    pump_depth_ft: Optional[float] = Field(default=None, gt=0)
    gor_scf_stb: float = Field(default=500.0, ge=0)


class EspOut(BaseModel):
    intake_psi: float
    discharge_psi: float
    dp_pump_psi: float
    tdh_ft: float
    stages: int
    hydraulic_hp: float
    motor_hp_required: float
    motor_hp_recommended: Optional[int] = None
    bo_rb_stb: float
    grad_psi_ft: float
    free_gas_fraction: float
    warnings: List[str] = []


class RodPumpIn(BaseModel):
    target_rate_stb_d: float = Field(gt=0)
    water_cut: float = Field(ge=0.0, le=1.0)
    pump_depth_ft: float = Field(gt=0)
    plunger_dia_in: float = Field(ge=1.06, le=3.75)
    stroke_len_in: float = Field(ge=12.0, le=300.0)
    spm: float = Field(ge=4.0, le=12.0)
    vol_efficiency: float = Field(default=0.8, ge=0.3, le=1.0)


class RodPumpCheckItem(BaseModel):
    check: str
    ok: bool
    note: str


class RodPumpOut(BaseModel):
    pump_displacement_bpd: float
    achievable_rate_bpd: float
    hydraulic_hp: float
    verdict: str
    checks: List[RodPumpCheckItem] = []


def _oil_well_or_404(db: Session, well_id: int,
                     key: models.ApiKey) -> models.Well:
    well = _well_or_404(db, well_id, key)
    if well.well_type != "oil" or not well.oil_api:
        raise HTTPException(
            422, "this endpoint requires an oil well "
                 "(create/update with well_type='oil' and oil_api)")
    return well


@router.post("/oil-ipr", response_model=OilIprOut)
def oil_ipr(well_id: int, payload: OilIprIn,
            key: models.ApiKey = Depends(require_tier("pro")),
            db: Session = Depends(get_db)):
    """Vogel IPR calibrated with one stabilized test point, plus
    Standing PVT at reservoir conditions."""
    well = _oil_well_or_404(db, well_id, key)
    try:
        qo_max = oil_pvt.vogel_qo_max(payload.qo_test_stb_d,
                                      payload.pwf_test_psia,
                                      well.p_res)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    rs_at_p = oil_pvt.standing_solution_gor(
        well.p_res, well.t_res_f, well.oil_api, well.gamma_g)
    pb = oil_pvt.standing_bubble_point(rs_at_p, well.t_res_f,
                                       well.oil_api, well.gamma_g)
    vis = oil_pvt.oil_viscosity(well.p_res, pb, well.t_res_f,
                                well.oil_api, well.gamma_g,
                                oil_sg=141.5 / (well.oil_api + 131.5))
    return OilIprOut(
        p_bubble_psia=round(pb, 1),
        rs_at_p_res_scf_stb=round(rs_at_p, 1),
        mu_o_cp=round(vis["mu_o_cp"], 3),
        qo_max_stb_d=round(qo_max, 1),
        curve=[OilCurvePoint(**pt) for pt in
               oil_pvt.vogel_curve(qo_max, well.p_res)],
        warnings=oil_pvt.validate_ranges(well.t_res_f, well.oil_api,
                                         rs_at_p))


@router.post("/esp-sizing", response_model=EspOut)
def esp_sizing(well_id: int, payload: EspIn,
               key: models.ApiKey = Depends(require_tier("pro")),
               db: Session = Depends(get_db)):
    """Simplified Gould-style ESP design for this oil well."""
    well = _oil_well_or_404(db, well_id, key)
    try:
        qo_max = oil_pvt.vogel_qo_max(payload.qo_test_stb_d,
                                      payload.pwf_test_psia,
                                      well.p_res)
        result = size_esp(
            {"p_res": well.p_res, "t_res_f": well.t_res_f,
             "tvd_ft": well.tvd_ft, "api_gravity": well.oil_api,
             "gamma_g": well.gamma_g,
             "gor_scf_stb": payload.gor_scf_stb},
            target_rate_stb_d=payload.target_rate_stb_d,
            qo_max_stb_d=qo_max,
            water_cut=payload.water_cut,
            thp_psia=payload.thp_psia,
            pump_depth_ft=payload.pump_depth_ft)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return EspOut(**result)


@router.post("/rod-pump", response_model=RodPumpOut)
def rod_pump(well_id: int, payload: RodPumpIn,
             key: models.ApiKey = Depends(require_tier("pro")),
             db: Session = Depends(get_db)):
    """Beam-pump feasibility screen (API RP 11L spirit)."""
    well = _oil_well_or_404(db, well_id, key)
    result = rod_pump_check(
        {"p_res": well.p_res, "t_res_f": well.t_res_f,
         "tvd_ft": well.tvd_ft, "api_gravity": well.oil_api,
         "gamma_g": well.gamma_g},
        target_rate_stb_d=payload.target_rate_stb_d,
        water_cut=payload.water_cut,
        pump_depth_ft=float(payload.pump_depth_ft),
        plunger_dia_in=float(payload.plunger_dia_in),
        stroke_len_in=float(payload.stroke_len_in),
        spm=float(payload.spm),
        vol_efficiency=float(payload.vol_efficiency))
    return RodPumpOut(**result)
