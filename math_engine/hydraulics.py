"""
math_engine.hydraulics
----------------------
Wellbore hydraulics building blocks for single-phase (dry) gas:

1. Reynolds number & Moody friction factor (explicit Swamee-Jain).
2. Tubing Performance (VLP) via the average temperature & z-factor
   closed-form equation (Lee & Wattenbarger, Eq. 4.39), iterated on
   the bottomhole pressure because z and mu depend on average pressure.

For a full depth-marching integration see math_engine.bhp_dry_gas
(RK2 / Cullender-Smith style), and math_engine.multiphase for the
two-phase Beggs-Brill traverse.

Units: field units (see CONTEXT.md).
    P (psia), T (R), L/depth (ft), rate q (Mscf/D), diameter d (in)
"""

import math

from math_engine.gas_properties import get_gas_properties


def calculate_reynolds_number(q_g, gamma_g, mu_g, d):
    """
    Gas well Reynolds number (Eq. 4.27):

        N_Re = (20 * gamma_g * q_g) / (mu_g * d)

    :param q_g: Gas flow rate (Mscf/D).
    :param gamma_g: Gas specific gravity.
    :param mu_g: Gas viscosity at average conditions (cp).
    :param d: Tubing inner diameter (inches).
    :return: N_Re (dimensionless). Laminar if <= 2000, turbulent > 4000.
    """
    return (20.0 * gamma_g * q_g) / (mu_g * d)


def calculate_friction_factor(q_g, d, gamma_g, mu_g, epsilon=0.0006):
    """
    Moody friction factor via the explicit Swamee-Jain equation.

    :param q_g: Gas flow rate (Mscf/D).
    :param d: Tubing inner diameter (inches).
    :param gamma_g: Gas specific gravity.
    :param mu_g: Gas viscosity (cp).
    :param epsilon: Absolute pipe roughness (inches); 0.0006 = new tubing.
    :return: Moody friction factor (dimensionless).
    """
    Re = calculate_reynolds_number(q_g, gamma_g, mu_g, d)

    if Re <= 2000:
        # Laminar flow
        f = 64.0 / Re
    else:
        # Turbulent: f = 0.25 / [log10(e/(3.7d) + 5.74/Re^0.9)]^2
        f = 0.25 / (math.log10((epsilon / (3.7 * d)) +
                               (5.74 / (Re ** 0.9))) ** 2)

    return f


# ==============================================================================
# VLP: VERTICAL LIFT PERFORMANCE (Average T & z Method)
# Reference: Lee & Wattenbarger, Eq. 4.39
# ==============================================================================
def calculate_pwf_vlp(q_g, p_wh, T_wh, T_res, L, d, gamma_g, theta=0.0,
                      max_iter=50, tolerance=0.1):
    """
    Bottomhole Flowing Pressure (BHFP) required to lift dry gas to
    surface at rate q_g, via the average T&z method:

        p_wf^2 = e^s * p_wh^2 + [6.67e-4 * f * T_avg^2 * z_avg^2 * q_g^2]
                 / (d^5 * cos(theta)) * (e^s - 1)
        s = (0.0375 * gamma_g * L * cos_theta) / (z_avg * T_avg)

    Iterated because z_avg and mu_avg depend on p_wf itself.

    :param q_g: Gas flow rate (Mscf/D).
    :param p_wh: Wellhead flowing pressure (psia).
    :param T_wh: Wellhead temperature (Rankine).
    :param T_res: Reservoir/bottomhole temperature (Rankine).
    :param L: Tubing length / TVD (ft).
    :param d: Tubing inner diameter (inches).
    :param gamma_g: Gas specific gravity.
    :param theta: Angle from vertical, degrees (0 = vertical well).
    :return: p_wf (psia).
    """
    theta_rad = math.radians(theta)
    cos_theta = math.cos(theta_rad)

    # Initial guess for p_wf
    p_wf = p_wh + 0.25 * (L / 100.0)

    for _ in range(max_iter):
        # Average pressure and temperature
        p_avg = (p_wh + p_wf) / 2.0
        T_avg = (T_wh + T_res) / 2.0

        # Gas properties at average conditions
        props = get_gas_properties(p_avg, T_avg, gamma_g)
        z_avg = props['z']
        mu_avg = props['viscosity_cp']

        # Friction factor
        f = calculate_friction_factor(q_g, d, gamma_g, mu_avg)

        # s parameter (Eq. 4.39)
        s = (0.0375 * gamma_g * L * cos_theta) / (z_avg * T_avg)

        term1 = math.exp(s) * (p_wh ** 2)

        if cos_theta == 0:
            term2 = 0.0
        else:
            numerator = 6.67e-4 * f * (T_avg ** 2) * (z_avg ** 2) * (q_g ** 2)
            denominator = (d ** 5) * cos_theta
            term2 = (numerator / denominator) * (math.exp(s) - 1.0)

        p_wf_new = math.sqrt(term1 + term2)

        if abs(p_wf_new - p_wf) < tolerance:
            return p_wf_new

        p_wf = p_wf_new

    return p_wf
