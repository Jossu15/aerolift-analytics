"""
math_engine.backtest
--------------------
Walk-forward backtesting of the liquid-loading death forecast.

The question we validate: "if I had only the first k months of
history, how accurately would the engine have predicted the month
the well loads up and dies?"

Method
------
For each cutoff k (min_fit .. n):
    1. Fit the p/z material balance on history[:k].
    2. Run forecast_well_life from that point.
    3. Record the predicted death day (first non-flowing step).

Metrics against a known truth (synthetic wells or post-mortems):
    MAE_months   - mean absolute error of predicted death day /30.44
    hit_rate_tol - fraction within +/- tol months of truth

Units: field units (CONTEXT.md).
"""

from typing import Dict, List, Optional, Tuple

from math_engine.forecast import fit_material_balance, forecast_well_life
from math_engine.liquid_loading import loading_assessment
from math_engine.nodal_helpers import (
    build_beggs_brill_vlp_func,
    build_dry_gas_vlp_func,
    build_houpeurt_ipr_func,
    build_rawlins_schellhardt_ipr_func,
)

DEFAULT_A = 2100.0
DEFAULT_B = 0.05
DAYS_PER_MONTH = 30.44


def _vlp_from_params(params: Dict):
    """Build the VLP callable honoring vlp_model + friction_multiplier."""
    common = dict(
        P_surface=float(params["p_wh"]),
        T_surface=float(params["t_wh_f"]) + 460.0,
        T_bottomhole=float(params["t_res_f"]) + 460.0,
        depth_ft=float(params["tvd_ft"]),
        d_in=float(params["tubing_id_in"]),
    )
    gg = float(params["gamma_g"])
    q_w = float(params.get("q_water_bpd") or 0.0)
    fm = float(params.get("friction_multiplier") or 1.0)
    if params.get("vlp_model", "beggs_brill") == "beggs_brill" and q_w > 0:
        return build_beggs_brill_vlp_func(
            gamma_g=gg, liquid_sg=float(params.get("liquid_sg", 1.0)),
            q_liquid_bpd=q_w, angle_deg=90.0, n_segments=20,
            friction_multiplier=fm, **common)
    return build_dry_gas_vlp_func(common["P_surface"], common["T_surface"],
                                  common["T_bottomhole"],
                                  common["depth_ft"], gg,
                                  common["d_in"], n_segments=40)


def _ipr_factory(params: Dict):
    spec = params.get("ipr") or ("houpeurt",
                                 {"a": DEFAULT_A, "b": DEFAULT_B})
    kind, prm = spec
    if kind == "rs":
        return lambda Pr: build_rawlins_schellhardt_ipr_func(
            Pr, prm["C"], prm["n"])
    return lambda Pr: build_houpeurt_ipr_func(Pr, prm["a"], prm["b"])


def predict_death_day(params: Dict, gp_list: List[float],
                      p_list: List[float], time_step_days=30,
                      max_steps=240) -> Tuple[Optional[float], List[Dict]]:
    """
    Fit MB on the given window and forecast until the well stops flowing.

    :return: (predicted_death_day or None, full forecast history)
    """
    t_res = float(params["t_res_f"]) + 460.0
    gg = float(params["gamma_g"])
    d = float(params["tubing_id_in"])
    method = params.get("load_method", "turner")

    intercept, slope, G = fit_material_balance(t_res, gg, gp_list, p_list)
    vlp = _vlp_from_params(params)

    def loading_check(q, Pr, pwf):
        res = loading_assessment(pwf, t_res, gg, d, q, method=method)
        return bool(res["is_loading"])

    def loading_detail(q, Pr, pwf):
        res = loading_assessment(pwf, t_res, gg, d, q, method=method)
        return {"q_crit_mscfd": res["q_crit_mscfd"], "liquid_type": "water"}

    q_nominal = float(params.get("q_gas_nominal_mscfd") or 500.0)

    Pr_init = float(p_list[-1])
    ipr_spec = params.get("ipr") or ("houpeurt", {"a": DEFAULT_A, "b": DEFAULT_B})
    if ipr_spec[0] == "rs":
        C_rs, n_rs = ipr_spec[1]["C"], ipr_spec[1]["n"]
        q_aof = C_rs * (Pr_init ** (2.0 * n_rs))
    else:
        q_aof = q_nominal * 5.0
    q_max_est = max(q_aof * 1.2, q_nominal * 2.0)

    history = forecast_well_life(
        intercept, slope, G, t_res, gg,
        ipr_pwf_func_factory=_ipr_factory(params),
        vlp_pwf_func=vlp,
        loading_check_func=loading_check,
        Gp_start=float(gp_list[-1]),
        time_step_days=time_step_days, max_steps=max_steps,
        q_min=max(q_nominal / 100.0, 5.0), q_max=q_max_est,
        loading_detail_func=loading_detail)

    bad = next((row for row in history if row["status"] != "flowing"
                and row["status"] != "metastable"), None)
    return (None if bad is None else float(bad["day"])), history


def walk_forward(params: Dict, gp_full: List[float],
                 p_full: List[float], min_fit: int = 8,
                 step: int = 3,
                 time_step_days: float = DAYS_PER_MONTH) -> List[Dict]:
    """
    Refit at successive cutoffs; each prediction uses ONLY data up to
    that cutoff (no peeking).

    predict_death_day() reports days relative to the END of its input
    window, so every prediction here is shifted by the elapsed time of
    the window (cutoff * time_step) to make it an absolute timeline
    comparable against a known truth.
    """
    n = min(len(gp_full), len(p_full))
    if min_fit < 2 or min_fit > n:
        raise ValueError("min_fit must be in [2, len(history)]")
    rows = []
    for k in range(min_fit, n + 1, step):
        try:
            rel, _ = predict_death_day(
                params, gp_full[:k], p_full[:k],
                time_step_days=time_step_days)
        except ValueError as exc:
            rows.append({"fit_points": k, "predicted_death_day": None,
                         "error": str(exc)})
            continue
        abs_day = None if rel is None else k * time_step_days + rel
        rows.append({"fit_points": k, "predicted_death_day": abs_day})
    return rows


def score_predictions(pred_rows: List[Dict], truth_death_day: float,
                      tol_months: float = 2.0) -> Dict:
    """MAE (months) and hit-rate within +/- tol months vs known truth."""
    preds = [r["predicted_death_day"] for r in pred_rows
             if r.get("predicted_death_day") is not None]
    if not preds:
        return {"n_preds": 0, "mae_months": None, "hit_rate": None}
    errs_days = [abs(p - truth_death_day) for p in preds]
    mae_months = sum(errs_days) / len(errs_days) / DAYS_PER_MONTH
    hits = sum(1 for e in errs_days
               if e <= tol_months * DAYS_PER_MONTH)
    return {"n_preds": len(preds),
            "mae_months": mae_months,
            "hit_rate": hits / len(preds)}
