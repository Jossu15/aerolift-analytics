"""
math_engine.nodal_analysis
--------------------------
Nodal Analysis: find the well's "Natural Flow Point" - the operating
rate and bottomhole pressure where the reservoir's ability to DELIVER
gas (IPR curve) exactly matches the wellbore's requirement to LIFT that
gas to surface (VLP / Tubing Performance curve).

Concept
-------
Pick the bottomhole as the "solution node". For a series of assumed
rates q:
    - IPR tells you what Pwf the RESERVOIR would deliver at rate q.
    - VLP tells you what Pwf the WELLBORE requires at the given
      wellhead pressure to lift rate q to surface.
As q increases, IPR's required Pwf falls (more drawdown) while VLP
typically rises at low rates (liquid holdup dominates) before falling,
then rising again at high rates (friction) - the classic "J-shaped"
VLP curve. The natural flow point is where the curves cross:
IPR(q) = VLP(q).

Why ALL intersections matter: a liquid-loading-prone well commonly
shows TWO crossings - a low-rate one (UNSTABLE equilibrium: drift below
it and the well dies) and a high-rate one (the STABLE natural flow
point). Reporting only the first-found crossing would badly understate
deliverability, so this module finds every crossing and lets the caller
prefer the physically relevant one.

This module treats VLP and IPR as user-supplied callables (q -> Pwf),
keeping it independent of which correlation sits underneath. Factory
helpers below wire in the built-ins (Houpeurt IPR, average T&z VLP,
RK2 dry-gas marching, or full Beggs-Brill).

Units: field units (see CONTEXT.md).
"""

import math

from math_engine.nodal_helpers import (
    build_houpeurt_ipr_func,
    build_avg_tz_vlp_func,
    build_dry_gas_vlp_func,
    build_beggs_brill_vlp_func,
)

# Re-exported building blocks (kept here for backward compatibility)
from math_engine.hydraulics import (
    calculate_friction_factor,
    calculate_pwf_vlp,
)
from math_engine.ipr import rawlins_schellhardt_rate


def calculate_pwf_ipr(q_g, p_res, a, b):
    """
    Houpeurt pressure-squared IPR: BHFP the reservoir delivers at rate q.

        p_res^2 - p_wf^2 = a*q + b*q^2

    :param q_g: Gas rate (Mscf/D).
    :param p_res: Average reservoir pressure (psia).
    :param a: Laminar flow coefficient (psia^2 / (Mscf/D)).
    :param b: Turbulent/inertial coefficient (psia^2 / (Mscf/D)^2).
    :return: p_wf (psia); 0.0 if the reservoir cannot sustain this rate.
    """
    delta_p_sq = a * q_g + b * (q_g ** 2)
    p_wf_sq = (p_res ** 2) - delta_p_sq

    if p_wf_sq < 0:
        return 0.0  # Reservoir cannot sustain this rate

    return math.sqrt(p_wf_sq)


def _bisect(diff_func, q_lo, q_hi, tol, max_iter):
    """Root-find diff_func between brackets via bisection."""
    d_lo = diff_func(q_lo)
    for _ in range(max_iter):
        q_mid = 0.5 * (q_lo + q_hi)
        d_mid = diff_func(q_mid)
        if abs(d_mid) < tol:
            return q_mid
        if d_lo * d_mid < 0:
            q_hi = q_mid
        else:
            q_lo, d_lo = q_mid, d_mid
    return 0.5 * (q_lo + q_hi)


def find_all_intersections(ipr_pwf_func, vlp_pwf_func, q_min=1.0, q_max=None,
                           n_scan=80, tol=1.0, max_iter=60):
    """
    Find ALL rate intersections between the IPR and VLP curves in the
    scanned range, not just the first one encountered.

    :param ipr_pwf_func: callable q -> Pwf (psia) delivered by reservoir.
    :param vlp_pwf_func: callable q -> Pwf (psia) required by wellbore.
    :param q_min, q_max: Rate scan range, Mscf/D.
    :param n_scan: Bracketing scan points (80-150 recommended when the
                   VLP has a pronounced loading hump).
    :param tol: Convergence tolerance on Pwf difference, psia.
    :param max_iter: Max bisection iterations per crossing.
    :return: list of {'q_mscfd', 'Pwf_psia'} sorted by ascending q.
    """
    if q_max is None:
        q_max = 50000.0

    qs = [q_min + (q_max - q_min) * i / (n_scan - 1) for i in range(n_scan)]

    def diff(q):
        return ipr_pwf_func(q) - vlp_pwf_func(q)

    prev_q = qs[0]
    try:
        prev_diff = diff(prev_q)
    except Exception:
        prev_diff = None

    intersections = []
    for q in qs[1:]:
        try:
            d = diff(q)
        except Exception:
            prev_q, prev_diff = q, None
            continue
        if prev_diff is not None and prev_diff * d < 0:
            q_solution = _bisect(diff, prev_q, q, tol, max_iter)
            pwf_solution = 0.5 * (ipr_pwf_func(q_solution) +
                                  vlp_pwf_func(q_solution))
            intersections.append({"q_mscfd": q_solution,
                                  "Pwf_psia": pwf_solution})
        prev_q, prev_diff = q, d

    return intersections


def find_natural_flow_point(ipr_pwf_func, vlp_pwf_func, q_min=1.0, q_max=None,
                            n_scan=80, tol=1.0, max_iter=60,
                            prefer="highest_rate"):
    """
    Find the physically relevant intersection of the IPR and VLP curves.

    :param ipr_pwf_func: callable q -> Pwf (reservoir inflow).
    :param vlp_pwf_func: callable q -> Pwf (tubing performance).
    :param prefer: 'highest_rate' (STABLE operating point - default;
                   what the well settles at in normal operation) or
                   'lowest_rate' (UNSTABLE point - exposed for study).
    :return: dict {'q_mscfd', 'Pwf_psia', 'all_intersections': [...]}
             plus 'note' flagging the two-crossing loading-instability
             signature when present; None if no intersection exists
             (well cannot flow naturally across the range - dead/loaded).
    """
    intersections = find_all_intersections(ipr_pwf_func, vlp_pwf_func,
                                           q_min, q_max, n_scan, tol, max_iter)
    if not intersections:
        return None

    chosen = intersections[-1] if prefer == "highest_rate" else intersections[0]
    result = dict(chosen)
    result["all_intersections"] = intersections
    result["converged"] = True
    if len(intersections) > 1:
        result["note"] = (
            "{} intersections found - classic signature of a well near its "
            "liquid-loading limit (low-rate UNSTABLE point plus high-rate "
            "STABLE point). Returning the {}-rate solution per 'prefer'."
            .format(len(intersections),
                    "highest" if prefer == "highest_rate" else "lowest")
        )
    return result


def find_well_flow_point(p_res, a, b, p_wh, T_wh, T_res, L, d, gamma_g,
                         q_min=0.1, q_max=10000.0, n_scan=80,
                         prefer="highest_rate"):
    """
    Convenience wrapper (backward-compatible entry point): builds the
    built-in Houpeurt IPR and average T&z VLP callables and runs the
    multi-intersection solver.

    :return: dict with 'q_opt' (Mscf/D), 'p_wf_opt' (psia),
             'converged' (bool), plus intersection details when found.
    """
    ipr_func = build_houpeurt_ipr_func(p_res, a, b)
    vlp_func = build_avg_tz_vlp_func(p_wh, T_wh, T_res, L, d, gamma_g)

    result = find_natural_flow_point(ipr_func, vlp_func, q_min=q_min,
                                     q_max=q_max, n_scan=n_scan,
                                     prefer=prefer)
    if result is None:
        return {'q_opt': 0.0, 'p_wf_opt': 0.0, 'converged': False,
                'message': 'No intersection found in range.'}

    result['q_opt'] = result['q_mscfd']
    result['p_wf_opt'] = result['Pwf_psia']
    return result


def generate_curve(func, q_min, q_max, n_points=30):
    """
    Utility: evaluate a q->Pwf function over a rate range for plotting.

    :return: (qs list, pwfs list [None where evaluation failed])
    """
    qs = [q_min + (q_max - q_min) * i / (n_points - 1) for i in range(n_points)]
    pwfs = []
    for q in qs:
        try:
            pwfs.append(func(q))
        except Exception:
            pwfs.append(None)
    return qs, pwfs
