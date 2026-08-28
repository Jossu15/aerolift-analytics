"""
Bridge between stored Well records and math_engine callables.
Keeps routers thin; used by both /analysis and /scada endpoints.

IPR selection is expressed as an immutable 'spec':
    ("rs", {"C": .., "n": ..})      - Rawlins-Schellhardt fit of the test
    ("houpeurt", {"a": .., "b": ..}) - manual/implicit coefficients
so any layer can rebuild the IPR at any reservoir pressure.
"""

import math
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from math_engine.bhp_dry_gas import cullender_smith_bhp
from math_engine.forecast import (
    fit_material_balance,
    forecast_well_life,
    pressure_at_cumulative,
    pz_from_p,
)
from math_engine.ipr import absolute_open_flow, fit_rawlins_schellhardt
from math_engine.liquid_loading import loading_assessment
from math_engine.metastable import metastable_assessment
from math_engine.multiphase import multiphase_traverse
from math_engine.nodal_analysis import find_natural_flow_point
from math_engine.nodal_helpers import (
    build_avg_tz_vlp_func,
    build_beggs_brill_vlp_func,
    build_dry_gas_vlp_func,
    build_houpeurt_ipr_func,
    build_rawlins_schellhardt_ipr_func,
)
from math_engine.recommendations import classify_loading_severity, \
    recommend_interventions

DEFAULT_A = 2100.0
DEFAULT_B = 0.05


# ------------------------------------------------------------------
# VLP
# ------------------------------------------------------------------
def build_vlp_func(well, p_wh=None, q_water_bpd=None):
    """VLP callable honoring the well's stored model choice."""
    P_wh = float(p_wh if p_wh is not None else well.p_wh)
    T_wh = float(well.t_wh_f) + 460.0
    T_res = float(well.t_res_f) + 460.0
    q_w = float(q_water_bpd if q_water_bpd is not None
                else (well.q_water_bpd or 0.0))
    d = float(well.tubing_id_in)
    depth = float(well.tvd_ft)
    gg = float(well.gamma_g)
    fm = float(getattr(well, "friction_multiplier", None) or 1.0)

    use_bb = well.vlp_model == "beggs_brill" and q_w > 0
    if use_bb:
        return build_beggs_brill_vlp_func(
            P_surface=P_wh, T_surface=T_wh, T_bottomhole=T_res,
            depth_ft=depth, gamma_g=gg, liquid_sg=float(well.liquid_sg),
            q_liquid_bpd=q_w, d_in=d, angle_deg=90.0, n_segments=25,
            friction_multiplier=fm)
    if well.vlp_model == "avg_tz":
        return build_avg_tz_vlp_func(P_wh, T_wh, T_res, depth, d, gg)
    return build_dry_gas_vlp_func(P_wh, T_wh, T_res, depth, gg, d,
                                  n_segments=40)


# ------------------------------------------------------------------
# IPR as a portable spec
# ------------------------------------------------------------------
def ipr_spec(db: Session, well) -> Tuple[str, dict]:
    """
    Pick the best available IPR description for the well:
    R-S fit of the stored deliverability test when sane, else Houpeurt.
    """
    Pr = float(well.p_res)

    from api.crud import get_test
    row = get_test(db, well.id)
    if row is not None:
        pwf_list = [float(p["pwf_psia"]) for p in row.points]
        q_list = [float(p["q_mscfd"]) for p in row.points]
        if all(0 < p < Pr for p in pwf_list) and all(q > 0 for q in q_list):
            try:
                C_fit, n_fit = fit_rawlins_schellhardt(Pr, pwf_list, q_list)
                if 0.3 <= n_fit <= 1.2:
                    return "rs", {"C": C_fit, "n": n_fit}
            except Exception:
                pass

    a = float(well.a_coef) if well.a_coef else DEFAULT_A
    b = float(well.b_coef) if well.b_coef else DEFAULT_B
    return "houpeurt", {"a": a, "b": b}


def ipr_at(spec: Tuple[str, dict], Pr: float):
    """Rebuild the IPR callable at an arbitrary reservoir pressure."""
    kind, prm = spec
    if kind == "rs":
        return build_rawlins_schellhardt_ipr_func(Pr, prm["C"], prm["n"])
    return build_houpeurt_ipr_func(Pr, prm["a"], prm["b"])


def q_ceiling(spec: Tuple[str, dict], Pr: float) -> float:
    """Deliverability limit of the active IPR (scan upper bound)."""
    kind, prm = spec
    if kind == "rs":
        return absolute_open_flow(Pr, prm["C"], prm["n"])
    a, b = prm["a"], prm["b"]
    disc = a ** 2 + 4.0 * b * Pr ** 2
    return (-a + math.sqrt(disc)) / (2.0 * b)


def nodal_scan_range(spec, well) -> Tuple[float, float]:
    q_max = max(min(q_ceiling(spec, float(well.p_res)) * 1.05, 30000.0),
                20.0)
    q_nominal = float(well.q_gas_nominal_mscfd or 0.0)
    return max(q_nominal / 100.0, 5.0), q_max


# ------------------------------------------------------------------
# High-level analyses
# ------------------------------------------------------------------
def loading_snapshot(well, q_gas_mscfd, q_water_bpd=None, p_wh=None) -> dict:
    """Turner/Coleman verdict at bottomhole conditions + recommendations."""
    vlp = build_vlp_func(well, p_wh=p_wh, q_water_bpd=q_water_bpd)
    try:
        bhfp = vlp(float(q_gas_mscfd))
    except Exception:
        bhfp = None
    eval_p = bhfp if bhfp else float(
        p_wh if p_wh is not None else well.p_wh)
    t_res = float(well.t_res_f) + 460.0
    q_w = float(q_water_bpd if q_water_bpd is not None
                else (well.q_water_bpd or 0.0))

    res = loading_assessment(eval_p, t_res, float(well.gamma_g),
                             float(well.tubing_id_in),
                             q_actual_mscfd=float(q_gas_mscfd),
                             method=well.load_method)
    severity = classify_loading_severity(res["is_loading"],
                                         res["margin_fraction"],
                                         water_rate_bpd=q_w)
    advice = recommend_interventions(res["is_loading"],
                                     res["margin_fraction"],
                                     water_rate_bpd=q_w,
                                     d_in=float(well.tubing_id_in),
                                     q_actual_mscfd=res["q_actual_mscfd"],
                                     q_crit_mscfd=res["q_crit_mscfd"])
    actions = advice["actions"]
    margin = res["margin_fraction"]
    meta = metastable_assessment(eval_p, t_res, float(well.gamma_g),
                                 float(well.tubing_id_in),
                                 float(q_gas_mscfd),
                                 q_water_bpd=q_w,
                                 method=well.load_method)
    return {
        "is_loading": bool(res["is_loading"]),
        "margin_pct": margin * 100.0 if margin == margin else None,
        "severity": severity,
        "headline": advice["headline"],
        "first_action": (actions[0]["action"] if actions else None),
        "bhfp_psia": bhfp,
        "v_actual_ft_s": res["v_actual_ft_s"],
        "v_crit_ft_s": res["v_crit_ft_s"],
        "q_crit_mscfd": res["q_crit_mscfd"],
        "metastable_regime": meta["regime"],
        "q_min_stable_mscfd": meta["q_min_stable_mscfd"],
        "film_reynolds": meta["film_reynolds"],
        "method": res.get("method"),
        "mechanism": res.get("mechanism"),
        "regime": res.get("regime"),
        "models": res.get("models"),
    }


def natural_flow_point(db: Session, well):
    """IPR/VLP intersection(s); (None, spec) when the well cannot flow."""
    spec = ipr_spec(db, well)
    q_min, q_max = nodal_scan_range(spec, well)
    result = find_natural_flow_point(ipr_at(spec, float(well.p_res)),
                                     build_vlp_func(well),
                                     q_min=q_min, q_max=q_max,
                                     n_scan=90, prefer="highest_rate")
    return result, spec


def pressure_traverse(well, q_gas_mscfd, n_segments=40) -> dict:
    """Dry-gas and (when wet) Beggs-Brill profiles at the given rate."""
    P_wh = float(well.p_wh)
    T_wh = float(well.t_wh_f) + 460.0
    T_res = float(well.t_res_f) + 460.0
    depth = float(well.tvd_ft)
    gg = float(well.gamma_g)
    d = float(well.tubing_id_in)
    q_w = float(well.q_water_bpd or 0.0)

    _, prof_dry = cullender_smith_bhp(P_wh, T_wh, T_res, depth, gg,
                                      float(q_gas_mscfd), d, n_segments)
    out = {
        "depths_ft": [row[0] for row in prof_dry],
        "P_dry_gas_psia": [row[1] for row in prof_dry],
        "bhfp_dry_gas_psia": prof_dry[-1][1],
    }
    if q_w > 0:
        _, prof_wet = multiphase_traverse(
            P_surface=P_wh, T_surface=T_wh, T_bottomhole=T_res,
            depth_ft=depth, gamma_g=gg, liquid_sg=float(well.liquid_sg),
            q_gas_mscfd=float(q_gas_mscfd), q_liquid_bpd=q_w, d_in=d,
            angle_deg=90.0, n_segments=n_segments,
            friction_multiplier=float(
                getattr(well, "friction_multiplier", None) or 1.0))
        out["P_beggs_brill_psia"] = [row["P"] for row in prof_wet]
        patterns = {}
        for row in prof_wet[1:]:
            patterns[row.get("pattern", "-")] = \
                patterns.get(row.get("pattern", "-"), 0) + 1
        out["bb_flow_patterns"] = patterns
        out["bhfp_beggs_brill_psia"] = prof_wet[-1]["P"]
    return out


def forecast_from_history(db: Session, well, gp_list: List[float],
                          p_list: List[float], time_step_days=30,
                          max_steps=36) -> dict:
    """Material-balance decline forecast identical to the dashboard Tab 4."""
    t_res = float(well.t_res_f) + 460.0
    intercept, slope, G = fit_material_balance(t_res, float(well.gamma_g),
                                               gp_list, p_list)

    spec = ipr_spec(db, well)

    def loading_check(q, Pr, pwf):
        r = loading_assessment(pwf, t_res, float(well.gamma_g),
                               float(well.tubing_id_in), q,
                               method=well.load_method)
        return bool(r["is_loading"])

    def loading_detail(q, Pr, pwf):
        r = loading_assessment(pwf, t_res, float(well.gamma_g),
                               float(well.tubing_id_in), q,
                               method=well.load_method)
        return {"q_crit_mscfd": r["q_crit_mscfd"], "liquid_type": "water"}

    history = forecast_well_life(
        intercept, slope, G, t_res, float(well.gamma_g),
        ipr_pwf_func_factory=lambda Pr: ipr_at(spec, Pr),
        vlp_pwf_func=build_vlp_func(well),
        loading_check_func=loading_check,
        Gp_start=float(gp_list[-1]),
        time_step_days=time_step_days, max_steps=max_steps,
        q_min=max(float(well.q_gas_nominal_mscfd or 0.0) / 100.0, 5.0),
        q_max=30000.0,
        loading_detail_func=loading_detail)

    days_to_risk: Optional[int] = None
    if history and history[0]["status"] in ("flowing", "metastable"):
        bad = next((r for r in history
                    if r["status"] not in ("flowing", "metastable")), None)
        if bad is not None:
            days_to_risk = int(bad["day"])
    elif history:
        days_to_risk = 0

    return {
        "ogip_mmscf": G,
        "pi_over_zi_psia": intercept,
        "mb_slope": slope,
        "days_to_risk": days_to_risk,
        "history": history,
    }


def preview_decline_history(db: Session, well):
    """Synthesize a volumetric material-balance (gp, p) history estimate.

    Mature-gas-well estimate: OGIP ~ 10 years at 80% of the absolute
    open flow, sampled at cumulatives 0 / 5 / 10 / 15 % of OGIP.
    Returns (gp_mmscf_list, p_psia_list, walker) where walker maps a
    cumulative to a reservoir pressure on the fitted p/z line.
    """
    t_res = float(well.t_res_f) + 460.0
    gg = float(well.gamma_g)
    p_res = float(well.p_res)
    intercept = pz_from_p(p_res, t_res, gg)

    spec = ipr_spec(db, well)
    aof = q_ceiling(spec, p_res)
    g_est = max(2000.0, aof * 0.8 * 3650.0 / 1000.0)
    slope = -intercept / g_est

    gp_hist = [0.0, 0.05 * g_est, 0.10 * g_est, 0.15 * g_est]
    p_hist = [pressure_at_cumulative(g, intercept, slope, t_res, gg)
              for g in gp_hist]

    def walker(g):
        return pressure_at_cumulative(g, intercept, slope, t_res, gg)

    return gp_hist, p_hist, walker


def forecast_view(db: Session, well, time_step_days=30,
                  max_steps=60) -> dict:
    """Dashboard forecast for a well without a manually-uploaded p/z history.

    Builds an internally-consistent volumetric MB history from the well's
    stored reservoir pressure and deliverability (mature-gas-well estimate:
    OGIP ~ 10 years at 80% of the absolute open flow), then runs the exact
    same physics loop as forecast_from_history. The estimate is returned
    flagged as such so consumers can label it a preview.
    """
    gp_hist, p_hist, _ = preview_decline_history(db, well)

    result = forecast_from_history(db, well, gp_hist, p_hist,
                                   time_step_days=time_step_days,
                                   max_steps=max_steps)
    result["preview"] = True
    result["note"] = ("OGIP estimado a partir de la deliverabilidad "
                      "(sin historial p/z cargado) - vista de pronostico")
    return result


def _alert_days_to_risk(db, well):
    """Days until the forecast stops flowing (or None when unavailable).

    Reuses forecast_view so the semaphore carries the same health score
    as the forecast tab: the well's preview p/z + IPR/VLP loop reports
    the first day its status leaves flowing/metastable. Expensive enough
    to be bounded (60 steps) and never fatal: any failure -> None.
    """
    try:
        fv = forecast_view(db, well, max_steps=60)
        return fv.get("days_to_risk")
    except Exception:
        return None


def portfolio_alert(well, db=None) -> Optional[dict]:
    """Semaphore row for one well of the whole-portfolio dashboard.

    Evaluated at the nominal rate and mapped onto the green/yellow/
    orange/red semaphore used by the UI (loaded->red, metastable->
    orange, at_risk->yellow, stable->green). Wells without a nominal
    rate return None (can't be evaluated). When a DB session is passed,
    the row also carries days_to_risk from the p/z forecast; otherwise
    (and on any forecast failure) it stays None.
    """
    q = float(well.q_gas_nominal_mscfd or 0.0)
    if q <= 0:
        return None
    snap = loading_snapshot(well, q)
    margin = snap.get("margin_pct")
    threshold = float(getattr(well, "alert_margin_pct", None) or 20.0)
    if snap["is_loading"]:
        status, color, message = "loaded", "red", \
            "Cargado - colapsar sin intervencion"
    elif snap["metastable_regime"] == "metastable":
        status, color, message = "metastable", "orange", \
            "Estable solo en regimen metaestable (Dousi 2006)"
    elif margin is not None and margin < threshold:
        status, color, message = "at_risk", "yellow", \
            "En riesgo - margen bajo ({:.0f}% < {:.0f}%)".format(
                margin, threshold)
    else:
        status, color, message = "stable", "green", "Estable"
    return {
        "well_id": well.id,
        "tag": well.tag,
        "severity": color,
        "status": status,
        "message": message,
        "margin_pct": margin,
        "days_to_risk": _alert_days_to_risk(db, well) if db is not None
        else None,
        "v_actual_ft_s": snap.get("v_actual_ft_s"),
        "v_crit_ft_s": snap.get("v_crit_ft_s"),
        "q_crit_mscfd": snap.get("q_crit_mscfd"),
        "metastable_regime": snap.get("metastable_regime"),
        "q_min_stable_mscfd": snap.get("q_min_stable_mscfd"),
    }
