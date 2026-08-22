"""
math_engine.ipr
---------------
Gas well Inflow Performance Relationship (IPR) - how much gas the
RESERVOIR can deliver to the wellbore at a given flowing bottomhole
pressure. One side of the Nodal Analysis equation; the other side is
the wellbore's Tubing Performance (VLP) curve.

Two formulations are implemented:

1. Rawlins & Schellhardt (1935) empirical backpressure equation
   ("C, n" deliverability equation):

        q = C * (Pr^2 - Pwf^2)^n

   Fit from a multi-point ("four-point") backpressure test via log-log
   linear regression. Purely empirical - simple and fast, but does not
   extrapolate well outside the tested range.

2. Pseudopressure (real-gas potential) formulation:

        m(P) = 2 * INTEGRAL[P_ref to P] ( P' / (mu_g * Z) ) dP'
        m(Pr) - m(Pwf) = a*q + b*q^2

   The rigorous approach when Z and viscosity vary significantly over
   the drawdown range. 'a' = laminar (Darcy) resistance,
   'b' = non-Darcy (turbulent/inertial) resistance near the wellbore.

Units: field units (see CONTEXT.md).
"""

import math
from math_engine.gas_properties import z_factor, gas_viscosity_lee


# ---------------------------------------------------------------------------
# 1. Rawlins-Schellhardt (C, n) backpressure equation
# ---------------------------------------------------------------------------

def fit_rawlins_schellhardt(Pr, Pwf_list, q_list):
    """
    Fit q = C * (Pr^2 - Pwf^2)^n from multi-point test data via
    log-log linear regression: log(q) = log(C) + n*log(Pr^2 - Pwf^2)

    :param Pr: Average reservoir pressure at time of test, psia.
    :param Pwf_list: Stabilized flowing BH pressures per test point, psia.
    :param q_list: Corresponding stabilized gas rates, Mscf/D.
    :return: (C, n) fitted flow coefficient and turbulence exponent.
             Physically n should fall between 0.5 (fully turbulent)
             and 1.0 (fully laminar/Darcy flow).
    """
    if len(Pwf_list) != len(q_list) or len(Pwf_list) < 2:
        raise ValueError("Need at least 2 matched (Pwf, q) test points.")

    x = [math.log10(Pr ** 2 - pwf ** 2) for pwf in Pwf_list]
    y = [math.log10(q) for q in q_list]

    n_pts = len(x)
    x_mean = sum(x) / n_pts
    y_mean = sum(y) / n_pts

    num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    den = sum((xi - x_mean) ** 2 for xi in x)
    if den == 0:
        raise ValueError("Test points do not span a range of drawdowns.")

    n_exp = num / den          # slope = turbulence exponent n
    log_C = y_mean - n_exp * x_mean
    C = 10 ** log_C

    return C, n_exp


def rawlins_schellhardt_rate(Pr, Pwf, C, n):
    """Gas rate (Mscf/D) predicted by the fitted C,n equation at a given Pwf."""
    drawdown_sq = Pr ** 2 - Pwf ** 2
    if drawdown_sq < 0:
        return 0.0
    return C * drawdown_sq ** n


def absolute_open_flow(Pr, C, n):
    """
    Absolute Open Flow potential (AOF): theoretical rate at Pwf = 0.
    Single-number "deliverability" benchmark; producing at AOF is
    neither achievable nor good practice.
    """
    return rawlins_schellhardt_rate(Pr, 0.0, C, n)


# ---------------------------------------------------------------------------
# 2. Pseudopressure, m(P)
# ---------------------------------------------------------------------------

def pseudopressure(P, T, gamma_g, P_ref=14.696, n_steps=200):
    """
    Numerically evaluate the real-gas pseudopressure via Simpson's rule:

        m(P) = 2 * INTEGRAL[P_ref to P] ( P' / (mu_g(P') * Z(P')) ) dP'

    :param P: Upper integration limit (pressure of interest), psia.
    :param T: Reservoir temperature, R (constant over the integral).
    :param gamma_g: Gas specific gravity.
    :param P_ref: Lower integration limit, psia (nonzero avoids the
                  singularity at exactly P=0; negligible impact).
    :param n_steps: Simpson intervals (forced even).
    :return: Pseudopressure, psia^2/cp.
    """
    if n_steps % 2 != 0:
        n_steps += 1
    if P <= P_ref:
        return 0.0

    h = (P - P_ref) / n_steps

    def integrand(Pp):
        Z = z_factor(Pp, T, gamma_g)
        mu = gas_viscosity_lee(Pp, T, gamma_g, Z)
        return Pp / (mu * Z)

    total = integrand(P_ref) + integrand(P)
    for i in range(1, n_steps):
        Pp = P_ref + i * h
        coeff = 4 if i % 2 == 1 else 2
        total += coeff * integrand(Pp)

    integral = (h / 3.0) * total
    return 2 * integral


def fit_pseudopressure_ipr(Pr, T, gamma_g, Pwf_list, q_list):
    """
    Fit the Darcy + non-Darcy pseudopressure IPR:
        m(Pr) - m(Pwf) = a*q + b*q^2
    via regression of [m(Pr)-m(Pwf)]/q = a + b*q.

    :return: (a, b, m_Pr)
        a : laminar coefficient
        b : turbulent/inertial coefficient
        m_Pr : pseudopressure at reservoir pressure (psia^2/cp)
    """
    m_Pr = pseudopressure(Pr, T, gamma_g)
    m_Pwf_list = [pseudopressure(pwf, T, gamma_g) for pwf in Pwf_list]

    x = list(q_list)
    y = [(m_Pr - m_pwf) / q for m_pwf, q in zip(m_Pwf_list, q_list)]

    n_pts = len(x)
    x_mean = sum(x) / n_pts
    y_mean = sum(y) / n_pts
    num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    den = sum((xi - x_mean) ** 2 for xi in x)
    if den == 0:
        # Only one distinguishable rate - can't separate a and b reliably;
        # assume pure Darcy flow (b=0) as a fallback.
        b = 0.0
        a = y_mean
    else:
        b = num / den
        a = y_mean - b * x_mean

    return a, b, m_Pr


def pseudopressure_rate(Pwf, T, gamma_g, a, b, m_Pr):
    """
    Solve b*q^2 + a*q - (m_Pr - m(Pwf)) = 0 for q at a target Pwf.
    """
    m_Pwf = pseudopressure(Pwf, T, gamma_g)
    delta_m = m_Pr - m_Pwf
    if delta_m <= 0:
        return 0.0

    if b == 0:
        return delta_m / a

    disc = a ** 2 + 4 * b * delta_m
    if disc < 0:
        return 0.0
    q = (-a + math.sqrt(disc)) / (2 * b)
    return max(q, 0.0)
