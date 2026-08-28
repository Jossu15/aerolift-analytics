"""
math_engine.barnea
------------------
Barnea (1986) vertical flow-pattern selector, powering the liquid-loading
ensemble's mechanism decision (Fase 2, roadmap 2.2).

Barnea unified the transition boundaries for the whole pipe-inclination
range using drift-flux void fraction. For the loading question we only
need the boundary between the two loading mechanisms:

    droplet lift   binds in annular / mist flow     (high void fraction)
    film reversal  binds in slug / churn flow       (intermediate alpha)

Drift-flux void fraction (Nicklin C0 = 1.2, Barnea v_drift for slug flow):

    alpha = vsg / (C0 * vm + v_drift)
    v_drift = 0.35 * sqrt(g * D)

Classification thresholds (classic holdup bands, vertical pipe):

    alpha < 0.25          -> bubble        (mechanism: film)
    0.25 <= alpha < 0.52  -> slug         (mechanism: film)
    0.52 <= alpha < 0.80  -> churn        (mechanism: film)
    alpha >= 0.80         -> annular/mist (mechanism: droplet)

Reference: Barnea, D. (1986) "Transition from annular flow and from
dispersed bubble flow -- unified models for the whole range of pipe
inclinations", Int. J. Multiphase Flow 12(5), 733-744.

Units: SI internally (m/s, m); `superficial_from_field` converts the
common field inputs to superficial velocities in m/s.
"""

import math

from math_engine.gas_properties import get_gas_properties, gas_fvf

_G = 9.81          # m/s2
_C0 = 1.2          # drift-flux profile constant (Zuber-Findlay / Nicklin)
_DRIFT_VEL_FACTOR = 0.35   # v_drift = K * sqrt(g * D), slug-flow drift
_BUBBLE_TOP = 0.25
_SLUG_TOP = 0.52   # void fraction above which bubbly flow cannot persist
_ANNULAR_TOP = 0.80


def drift_flux_alpha(vsg, vsl, d_m):
    """Void fraction alpha from superficial velocities (m/s, m)."""
    vm = vsg + vsl
    if vm <= 0:
        return 1.0
    v_drift = _DRIFT_VEL_FACTOR * math.sqrt(_G * d_m)
    v_gas = _C0 * vm + v_drift
    if v_gas <= 0:
        return 1.0
    return max(0.0, min(1.0, vsg / v_gas))


def vertical_regime(vsg, vsl, d_m):
    """
    Classify the vertical flow pattern and the binding loading mechanism.

    :param vsg: Gas superficial velocity (m/s).
    :param vsl: Liquid superficial velocity (m/s).
    :param d_m: Tubing inner diameter (m).
    :return: dict with regime, mechanism, alpha and the velocities used.
    """
    alpha = drift_flux_alpha(max(vsg, 0.0), max(vsl, 0.0), d_m)
    if vsl <= 1e-9 and vsg > 0:
        regime, mechanism = "annular", "droplet"
    elif alpha >= _ANNULAR_TOP:
        regime, mechanism = "annular", "droplet"
    elif alpha >= _SLUG_TOP:
        regime, mechanism = "churn", "film"
    elif alpha >= _BUBBLE_TOP:
        regime, mechanism = "slug", "film"
    else:
        regime, mechanism = "bubble", "film"
    return {
        "regime": regime,
        "mechanism": mechanism,
        "alpha": round(alpha, 4),
        "vsg_m_s": round(vsg, 4),
        "vsl_m_s": round(vsl, 4),
    }


def superficial_from_field(q_g_mscfd, q_l_bbl_d, p_psia, t_rankine,
                           gamma_g, d_in):
    """
    Superficial velocities (m/s) from field inputs.
    :return: tuple (vsg_m_s, vsl_m_s).
    """
    d_ft = d_in / 12.0
    area_ft2 = math.pi * (d_ft ** 2) / 4.0

    props = get_gas_properties(p_psia, t_rankine, gamma_g)
    bg = gas_fvf(p_psia, t_rankine, props['z'])
    q_gas_ft3_s = (max(q_g_mscfd, 0.0) * 1000.0) / 86400.0 * bg
    vsg_ft_s = q_gas_ft3_s / area_ft2

    q_liq_ft3_s = (max(q_l_bbl_d, 0.0) * 5.615) / 86400.0
    vsl_ft_s = q_liq_ft3_s / area_ft2

    return vsg_ft_s * 0.3048, vsl_ft_s * 0.3048
