"""
math_engine.forecast
--------------------
Forecasting gas-well performance over time by combining:

    1. Volumetric Material Balance (p/z plot) - how average reservoir
       pressure declines as cumulative gas is produced.
    2. Nodal Analysis - the natural flow rate at each reservoir
       pressure, given the current IPR and VLP.
    3. Liquid Loading check - at each step, verify whether the natural
       flow rate keeps velocity above the critical (Turner/Coleman)
       threshold.

This answers the central business question: "Given where the well is
today, how many more days/months can it flow naturally before it loads
up and dies?"

Material Balance (p/z) background
---------------------------------
For a volumetric (no water influx) dry-gas reservoir, real-gas material
balance gives a straight line:

    P/Z = (Pi/Zi) * (1 - Gp/G)

where P,Z = current average reservoir pressure / Z-factor,
      Pi,Zi = initial values, Gp = cumulative gas produced,
      G = original gas in place (OGIP).

Units: field units (see CONTEXT.md). Gp and G in MMscf (or any
consistent unit), rates in Mscf/D.
"""

import math

from math_engine.gas_properties import z_factor
from math_engine.metastable import metastable_extended_life, DEFAULT_R_META


def pz_from_p(P, T, gamma_g):
    """Return P/Z at the given pressure/temperature (for a p/z plot)."""
    Z = z_factor(P, T, gamma_g)
    return P / Z


def fit_material_balance(T, gamma_g, Gp_list, P_list):
    """
    Fit the straight-line material balance from historical (Gp, P) data:

        y = P/Z, x = Gp  ->  y = intercept + slope * x
        intercept = Pi/Zi
        slope     = -(Pi/Zi)/G   =>   G = -intercept/slope

    :param T: Reservoir temperature, R.
    :param gamma_g: Gas gravity.
    :param Gp_list: Historical cumulative production, MMscf.
    :param P_list: Corresponding average reservoir pressures, psia.
    :return: (intercept psia, slope psia per MMscf, G MMscf)
    """
    if len(Gp_list) != len(P_list) or len(Gp_list) < 2:
        raise ValueError("Need at least 2 matched (Gp, P) data points.")

    y = [pz_from_p(p, T, gamma_g) for p in P_list]
    x = list(Gp_list)

    n = len(x)
    x_mean = sum(x) / n
    y_mean = sum(y) / n
    num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    den = sum((xi - x_mean) ** 2 for xi in x)
    if den == 0:
        raise ValueError("Gp values do not span a range - cannot fit a trend.")

    slope = num / den
    intercept = y_mean - slope * x_mean

    if slope >= 0:
        raise ValueError("Fitted slope is non-negative - data does not show "
                         "expected pressure depletion trend; check inputs.")

    G = -intercept / slope
    return intercept, slope, G


def pressure_at_cumulative(Gp, intercept, slope, T, gamma_g,
                           tol=1e-6, max_iter=50):
    """
    Solve for the average reservoir pressure P at a given cumulative
    production Gp:  P/Z(P) = intercept + slope*Gp.

    Since P/Z depends on P through Z(P), this requires a small
    Newton-Raphson solve with a numerical derivative.
    """
    target = intercept + slope * Gp
    if target <= 0:
        return 0.0

    P = target  # initial guess assuming Z~1
    for _ in range(max_iter):
        Z = z_factor(P, T, gamma_g)
        f = P / Z - target
        dP = 1e-2
        Z2 = z_factor(P + dP, T, gamma_g)
        f2 = (P + dP) / Z2 - target
        df = (f2 - f) / dP
        if df == 0:
            break
        P_new = P - f / df
        if P_new <= 0:
            P_new = P * 0.5
        if abs(P_new - P) < tol:
            P = P_new
            break
        P = P_new
    return P


def forecast_well_life(intercept, slope, G, T, gamma_g,
                       ipr_pwf_func_factory, vlp_pwf_func,
                       loading_check_func,
                       Gp_start, time_step_days=30, max_steps=240,
                       q_min=1.0, q_max=50000.0,
                       loading_detail_func=None):
    """
    Step forward in time; at each step:
      1. Compute current Pr from Gp (material balance).
      2. Rebuild the IPR curve at the new Pr (via factory).
      3. Find the natural flow point via Nodal Analysis.
      4. Check liquid loading at that flow point.
      5. If loading, check metastable regime (Dousi 2006 / Neiman 2014).
      6. Advance Gp by (natural flow rate * time step).

    :param intercept, slope, G: Fitted material-balance parameters
                                (see fit_material_balance).
    :param T, gamma_g: Reservoir temperature (R) and gas gravity.
    :param ipr_pwf_func_factory: callable Pr -> (callable q -> Pwf);
                                 rebuilds IPR as reservoir pressure declines.
    :param vlp_pwf_func: callable q -> Pwf (assumed constant over forecast).
    :param loading_check_func: callable (q, Pr, pwf) -> is_loading bool.
    :param Gp_start: Cumulative production at start of forecast (MMscf).
    :param time_step_days: Forecast step, days.
    :param max_steps: Max steps (guards against infinite loops).
    :param q_min, q_max: Nodal scan range, Mscf/D.
    :param loading_detail_func: optional callable (q, Pr, pwf) -> dict with
        keys 'q_crit_mscfd' and 'liquid_type'. When provided, enables the
        metastable flow extension (Dousi 2006). When None, metastable is
        skipped and the behavior is identical to the original model.
    :return: history list of dicts per step:
             day, Gp, Pr, q_mscfd, Pwf, is_loading, status.
             Stops when the well dies, loads up, or is depleted.
             Status values: 'flowing', 'metastable', 'loading_risk',
                            'well_dead', 'depleted'.
    """
    history = []
    Gp = Gp_start
    day = 0.0

    from math_engine.nodal_analysis import find_natural_flow_point

    for _step in range(max_steps):
        Pr = pressure_at_cumulative(Gp, intercept, slope, T, gamma_g)
        if Pr <= 0:
            history.append({"day": day, "Gp": Gp, "Pr": 0.0, "q_mscfd": 0.0,
                            "Pwf": None, "is_loading": True,
                            "status": "depleted"})
            break

        ipr_func = ipr_pwf_func_factory(Pr)
        result = find_natural_flow_point(ipr_func, vlp_pwf_func,
                                         q_min=q_min, q_max=q_max)

        if result is None:
            history.append({"day": day, "Gp": Gp, "Pr": Pr, "q_mscfd": 0.0,
                            "Pwf": None, "is_loading": True,
                            "status": "well_dead"})
            break

        q = result["q_mscfd"]
        pwf = result["Pwf_psia"]
        is_loading = loading_check_func(q, Pr, pwf)

        if is_loading and loading_detail_func is not None:
            detail = loading_detail_func(q, Pr, pwf)
            q_crit = detail.get("q_crit_mscfd", 0.0)
            liq_type = detail.get("liquid_type", "water")
            meta = metastable_extended_life(q_crit, q, liquid_type=liq_type)
            if meta["can_flow"]:
                status = "metastable"
                is_loading = False
            else:
                status = "loading_risk"
        else:
            status = "loading_risk" if is_loading else "flowing"

        history.append({"day": day, "Gp": Gp, "Pr": Pr, "q_mscfd": q,
                        "Pwf": pwf, "is_loading": is_loading,
                        "status": status})

        if is_loading:
            break

        # Advance: q [Mscf/D] * days / 1000 -> MMscf
        Gp += q * time_step_days / 1000.0
        day += time_step_days

    return history
