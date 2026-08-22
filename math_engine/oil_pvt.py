"""
math_engine.oil_pvt
-------------------
Black-oil PVT and IPR correlations for the oil-well extension
(Fase I). Field units throughout:

    pressures psia, temperatures deg F, rates STB/D,
    GOR scf/STB, viscosities cp.

All correlations are the textbook standards:

- Solution GOR / Pb : Standing (1947)
- Dead-oil mu       : Beggs & Robinson (1975)
- Saturated mu      : Beggs & Robinson
- Undersaturated mu : Vasquez-Beggs exponential correction
- Bo                : Standing
- IPR               : Vogel (1968) for saturated reservoirs

Valid ranges follow the original papers; inputs outside them are still
computed but flagged by the caller-facing ``validate_ranges`` helper.
"""

import math
from typing import Dict, List, Optional


def standing_a_factor(api_gravity: float, t_f: float) -> float:
    """10**(0.0125*API - 0.00091*T) - the Standing GOR/Pb shared term."""
    return 10.0 ** (0.0125 * api_gravity - 0.00091 * t_f)


def standing_solution_gor(p_psia: float, t_res_f: float,
                          api_gravity: float,
                          gas_sg: float) -> float:
    """Rs at pressure <= Pb (saturated leg), scf/STB."""
    if p_psia <= 0:
        return 0.0
    return gas_sg * ((p_psia / 18.2 + 1.4)
                     * standing_a_factor(api_gravity, t_res_f)) ** 1.2048


def standing_bubble_point(rs_scf_stb: float, t_res_f: float,
                          api_gravity: float, gas_sg: float) -> float:
    """Pb (psia) from Standing, inverted analytically from his GOR eq."""
    base = (rs_scf_stb / gas_sg) ** (1.0 / 1.2048) \
        / standing_a_factor(api_gravity, t_res_f)
    return 18.2 * (base - 1.4)


def standing_bo(rs_scf_stb: float, t_res_f: float,
                gas_sg: float, oil_sg: float) -> float:
    """Oil formation volume factor (rb/STB), Standing."""
    f = rs_scf_stb * (gas_sg / max(oil_sg, 0.5)) ** 0.5 + 1.25 * t_res_f
    return 0.9759 + 0.00012 * f ** 1.2


def beggs_robinson_dead_oil(t_res_f: float, api_gravity: float) -> float:
    """Dead-oil viscosity (cp) at reservoir temperature."""
    x = 10.0 ** (3.0324 - 0.02023 * api_gravity) * t_res_f ** (-1.163)
    return 10.0 ** x - 1.0


def beggs_robinson_saturated(mu_dead_cp: float,
                             rs_scf_stb: float) -> float:
    """Saturated (at Pb) live-oil viscosity (cp)."""
    a = 10.715 * (rs_scf_stb + 100.0) ** -0.515
    b = 8.284 * (rs_scf_stb + 100.0) ** -0.542
    return a * mu_dead_cp ** b


def oil_viscosity(p_psia: float, p_bubble_psia: float, t_res_f: float,
                  api_gravity: float, gas_sg: float,
                  oil_sg: float) -> Dict[str, float]:
    """
    Full-leg viscosity (cp):

    - p < Pb : Beggs-Robinson saturated at the equivalent Rs(p)
    - p >= Pb: BR value at Pb scaled up by the Vasquez-Beggs
               undersaturated power law
    """
    mu_dead = beggs_robinson_dead_oil(t_res_f, api_gravity)
    rs_at_p = min(
        standing_solution_gor(min(p_psia, p_bubble_psia),
                              t_res_f, api_gravity, gas_sg),
        standing_solution_gor(p_bubble_psia,
                              t_res_f, api_gravity, gas_sg))
    mu_sat = beggs_robinson_saturated(mu_dead, rs_at_p)
    if p_psia <= p_bubble_psia:
        return {"mu_o_cp": mu_sat, "mu_dead_cp": mu_dead,
                "regime": "saturated"}
    # Vasquez-Beggs: m = 2.6 * P^0.187 * exp(-11.513 - 8.98e-5 * P)
    m = 2.6 * p_psia ** 0.187 * math.exp(-11.513 - 8.98e-5 * p_psia)
    mu_unsat = mu_sat * (p_psia / p_bubble_psia) ** m
    return {"mu_o_cp": mu_unsat, "mu_dead_cp": mu_dead,
            "regime": "undersaturated"}


def vogel_qo_max(qo_test_stb_d: float, pwf_test_psia: float,
                 p_res_psia: float) -> float:
    """
    Calibrate Vogel's qo_max from a single stabilized test point.
    Valid for pwf_test <= p_res; returns the absolute open flow (STB/D).
    """
    if p_res_psia <= 0:
        raise ValueError("p_res must be positive")
    if not 0.0 < pwf_test_psia <= p_res_psia:
        raise ValueError("test pwf must satisfy 0 < pwf <= p_res")
    if qo_test_stb_d <= 0:
        raise ValueError("test rate must be positive")
    ratio = (1.0 - 0.2 * (pwf_test_psia / p_res_psia)
             - 0.8 * (pwf_test_psia / p_res_psia) ** 2)
    if ratio <= 0.0:
        raise ValueError("test point too close to p_res to calibrate")
    return qo_test_stb_d / ratio


def vogel_rate(qo_max_stb_d: float, pwf_psia: float,
               p_res_psia: float) -> float:
    """Vogel inflow rate (STB/D) at a given bottomhole pressure."""
    x = pwf_psia / p_res_psia
    return qo_max_stb_d * (1.0 - 0.2 * x - 0.8 * x * x)


def vogel_pwf(qo_max_stb_d: float, qo_stb_d: float,
              p_res_psia: float) -> Optional[float]:
    """Bottomhole pressure required to deliver qo (STB/D). Inverts the
    quadratic; None when the rate exceeds the absolute open flow."""
    if qo_stb_d >= qo_max_stb_d:
        return None
    # q/qmax = 1 - 0.2x - 0.8x^2  ->  0.8x^2 + 0.2x + (q/qmax - 1) = 0
    c = qo_stb_d / qo_max_stb_d - 1.0
    disc = 0.04 - 4.0 * 0.8 * c
    x = (-0.2 + math.sqrt(disc)) / (2.0 * 0.8)
    return x * p_res_psia


def vogel_curve(qo_max_stb_d: float, p_res_psia: float,
                n_points: int = 25) -> List[Dict[str, float]]:
    """Discrete IPR curve for plotting/reporting."""
    pts = []
    for i in range(n_points + 1):
        frac = i / n_points
        pwf = p_res_psia * (1.0 - frac)
        pts.append({"pwf_psia": pwf,
                    "qo_stb_d": vogel_rate(qo_max_stb_d, pwf,
                                           p_res_psia)})
    return pts


def validate_ranges(t_res_f: float, api_gravity: float,
                    rs_scf_stb: float) -> List[str]:
    """Soft validity warnings for the Standing/BR correlation windows."""
    warns = []
    if not (100.0 <= t_res_f <= 300.0):
        warns.append("T fuera del rango Standing/BR (100-300 F)")
    if not (16.0 <= api_gravity <= 45.0):
        warns.append("API fuera del rango tipico (16-45)")
    if not (20.0 <= rs_scf_stb <= 1900.0):
        warns.append("Rs fuera del rango Standing (20-1900 scf/STB)")
    return warns
