"""
math_engine.bhp_dry_gas
-----------------------
Single-phase (dry gas, no liquids) bottomhole pressure calculation.

Method
------
Marches down the wellbore in many small depth steps and, at each step,
computes the pressure gradient directly from the mechanical energy
balance (Cullender-Smith physics):

    dP/dh = (gravity term) + (friction term)

    gravity term  (psi/ft) = rho_g / 144
    friction term (psi/ft) = f * rho_g * v^2 / (2 * gc * d_ft) / 144

where at each step:
    rho_g = real-gas density at the LOCAL P, T (via gas_properties), lbm/ft3
    v     = LOCAL in-situ gas velocity = Q_actual / A
    Q_actual (ft3/s) = Qsc(scf/d) * (Psc * T * Z) / (P * Tsc) / 86400
    A     = pipe cross-sectional area, ft2
    f     = Darcy-Weisbach friction factor (fully turbulent / Nikuradse)
    gc    = 32.174 lbm-ft/(lbf-s^2)

Integration: RK2 (midpoint) marching scheme with many sub-steps, with Z
and density recomputed at local conditions at every step.

Units (field units, see CONTEXT.md):
    P (psia), T (R), depth (ft), rate q (Mscf/D), diameter d (in)
"""

import math
from math_engine.gas_properties import z_factor, gas_density

GC = 32.174   # lbm-ft/(lbf-s^2)
PSC = 14.696  # psia, standard pressure
TSC = 520.0   # R, standard temperature (60 F)


def friction_factor(d_in, roughness_in=0.0006):
    """
    Fully-turbulent (rough-pipe) Darcy-Weisbach friction factor via the
    Nikuradse correlation:

        1/sqrt(f) = 1.74 - 2*log10(2*e/d)

    :param d_in: Tubing inside diameter, inches.
    :param roughness_in: Absolute pipe roughness, inches
                         (0.0006 in is typical for new steel tubing).
    :return: Darcy-Weisbach friction factor (dimensionless).
    """
    inv_sqrt_f = 1.74 - 2 * math.log10(2 * roughness_in / d_in)
    return 1.0 / inv_sqrt_f ** 2


def _dPdh(P, T, gamma_g, q_mscfd, d_in, f):
    """
    Local pressure gradient (psi/ft): gravity term + friction term,
    both evaluated at the LOCAL P, T using real-gas properties.
    """
    Z = z_factor(P, T, gamma_g)
    rho = gas_density(P, T, gamma_g, Z)  # lbm/ft3

    gravity_grad = rho / 144.0  # psi/ft

    friction_grad = 0.0
    if q_mscfd > 0:
        qsc_scfd = q_mscfd * 1000.0
        q_actual_ft3s = qsc_scfd * (PSC * T * Z) / (P * TSC) / 86400.0

        d_ft = d_in / 12.0
        area_ft2 = math.pi / 4.0 * d_ft ** 2
        v = q_actual_ft3s / area_ft2  # ft/s

        friction_grad = (f * rho * v ** 2) / (2 * GC * d_ft) / 144.0  # psi/ft

    return gravity_grad + friction_grad


def cullender_smith_bhp(P_surface, T_surface, T_bottomhole, depth_ft,
                        gamma_g, q_mscfd=0.0, d_in=2.441, n_segments=50):
    """
    Compute bottomhole pressure from a known surface (wellhead) pressure,
    marching down the well in n_segments using an RK2 (midpoint) scheme
    on dP/dh = gravity term + friction term, with Z and density recomputed
    at local conditions at every step.

    :param P_surface: Surface (wellhead) pressure, psia. Use shut-in
                      wellhead pressure for BHSP (static), or flowing
                      wellhead pressure for BHFP (flowing).
    :param T_surface: Surface temperature, R.
    :param T_bottomhole: Bottomhole temperature, R.
    :param depth_ft: True vertical depth, ft.
    :param gamma_g: Gas specific gravity (air = 1).
    :param q_mscfd: Gas flow rate, Mscf/D. Use 0 for the static case.
    :param d_in: Tubing inside diameter, inches.
    :param n_segments: Number of depth steps (30-50 is plenty typically).
    :return: (P_bottomhole psia, profile list of (depth, P, T) tuples)
    """
    if n_segments < 1:
        raise ValueError("n_segments must be >= 1")

    dh = depth_ft / n_segments
    f = friction_factor(d_in)

    profile = [(0.0, P_surface, T_surface)]
    P = P_surface

    for i in range(n_segments):
        h1 = i * dh
        h2 = (i + 1) * dh
        T1 = T_surface + (T_bottomhole - T_surface) * (h1 / depth_ft)
        T2 = T_surface + (T_bottomhole - T_surface) * (h2 / depth_ft)
        T_mid = 0.5 * (T1 + T2)

        # RK2 (midpoint method):
        k1 = _dPdh(P, T1, gamma_g, q_mscfd, d_in, f)
        P_mid_est = P + k1 * (dh / 2.0)
        k2 = _dPdh(P_mid_est, T_mid, gamma_g, q_mscfd, d_in, f)

        P = P + k2 * dh
        profile.append((h2, P, T2))

    return P, profile
