"""
math_engine.multiphase
----------------------
Two-phase (gas + liquid) pressure gradient calculation using the
Beggs & Brill (1973) correlation, with the flow-pattern-dependent
liquid holdup and inclination correction described in Brill &
Mukherjee, "Multiphase Flow in Wells".

Beggs-Brill is the most versatile of the classic multiphase
correlations because it was developed from horizontal/inclined/vertical
flume data, so it handles deviated and horizontal wells as well as
vertical ones.

Core steps (all performed at LOCAL P, T at each depth increment):
    1. Compute superficial gas & liquid velocities from actual rates.
    2. Compute no-slip liquid holdup, Froude number, liquid velocity number.
    3. Determine flow pattern (segregated / intermittent / distributed /
       transition) from empirical boundaries L1-L4.
    4. Compute horizontal liquid holdup EL(0) from regime-specific
       constants, then apply the inclination correction factor to get
       the actual in-situ liquid holdup EL(theta).
    5. Compute mixture density (using EL) and no-slip density (using
       input liquid fraction).
    6. Compute the two-phase friction factor via the friction factor
       ratio correlation, and evaluate the full pressure gradient
       (elevation + friction [+ acceleration term]).

Units: field units throughout (see CONTEXT.md).
    P (psia), T (R), depth (ft), diameter d (in)
    gas rate q_gas (Mscf/D), liquid rate q_liquid (bbl/D)
    surface tension sigma (dyne/cm), gc = 32.174 lbm-ft/(lbf-s^2)
"""

import math
from math_engine.gas_properties import z_factor, gas_density

GC = 32.174        # lbm-ft/(lbf-s^2)
G = 32.174         # ft/s^2 (numerically equal to gc in these units)
PSC = 14.696       # psia
TSC = 520.0        # R
BBL_TO_FT3 = 5.615


def superficial_velocities(P, T, Z, q_gas_mscfd, q_liquid_bpd, d_in):
    """
    Convert surface (standard-condition) gas and liquid rates into
    LOCAL superficial velocities (ft/s) at the given P, T.

    :return: (vsg, vsl) superficial gas and liquid velocities, ft/s.
    """
    d_ft = d_in / 12.0
    area_ft2 = math.pi / 4.0 * d_ft ** 2

    qg_scfd = q_gas_mscfd * 1000.0
    qg_actual_ft3s = qg_scfd * (PSC * T * Z) / (P * TSC) / 86400.0
    vsg = qg_actual_ft3s / area_ft2

    # Liquid is essentially incompressible - rate at surface ~= rate downhole
    ql_ft3s = q_liquid_bpd * BBL_TO_FT3 / 86400.0
    vsl = ql_ft3s / area_ft2

    return vsg, vsl


def flow_pattern(lambda_L, N_Fr):
    """
    Determine the Beggs-Brill horizontal flow pattern given the no-slip
    liquid holdup (lambda_L) and the mixture Froude number (N_Fr).

    :return: ('segregated'|'transition'|'intermittent'|'distributed',
              (L1, L2, L3, L4))
    """
    L1 = 316.0 * lambda_L ** 0.302
    L2 = 0.0009252 * lambda_L ** -2.4684
    L3 = 0.10 * lambda_L ** -1.4516
    L4 = 0.5 * lambda_L ** -6.738

    if (lambda_L < 0.01 and N_Fr < L1) or (lambda_L >= 0.01 and N_Fr < L2):
        return "segregated", (L1, L2, L3, L4)
    if lambda_L >= 0.01 and L2 <= N_Fr <= L3:
        return "transition", (L1, L2, L3, L4)
    if (0.01 <= lambda_L < 0.4 and L3 < N_Fr <= L1) or \
       (lambda_L >= 0.4 and L3 < N_Fr <= L4):
        return "intermittent", (L1, L2, L3, L4)
    return "distributed", (L1, L2, L3, L4)


# Horizontal liquid-holdup constants: EL0 = a * lambda_L^b / N_Fr^c
_HOLDUP_CONSTANTS = {
    "segregated":   (0.98, 0.4846, 0.0868),
    "intermittent": (0.845, 0.5351, 0.0173),
    "distributed":  (1.065, 0.5824, 0.0609),
}

# Inclination-correction constants for UPHILL flow:
# C = (1-lambda_L) * ln(d * lambda_L^e * N_Lv^f * N_Fr^g)
_INCLINATION_UPHILL = {
    "segregated":   (0.011, -3.768, 3.539, -1.614),
    "intermittent": (2.96, 0.305, -0.4473, 0.0978),
    "distributed":  None,  # no correction: psi = 1 always
}
# Downhill flow uses ONE set of constants regardless of pattern
_INCLINATION_DOWNHILL = (4.70, -0.3692, 0.1244, -0.5056)


def _holdup_horizontal(pattern, lambda_L, N_Fr):
    a, b, c = _HOLDUP_CONSTANTS[pattern]
    EL0 = a * lambda_L ** b / N_Fr ** c
    return max(EL0, lambda_L)  # EL0 cannot physically be less than lambda_L


def _inclination_factor(pattern, lambda_L, N_Lv, N_Fr, angle_deg, is_uphill):
    """
    Compute psi, the inclination correction multiplier applied to the
    horizontal holdup: EL(theta) = EL0 * psi.
    """
    if is_uphill:
        consts = _INCLINATION_UPHILL[pattern]
        if consts is None:  # distributed pattern uphill: no correction
            return 1.0
    else:
        consts = _INCLINATION_DOWNHILL

    d, e, f, g = consts
    inner = d * lambda_L ** e * N_Lv ** f * N_Fr ** g
    if inner <= 0:
        C = 0.0
    else:
        C = (1 - lambda_L) * math.log(inner)
    C = max(C, 0.0)

    theta_rad = math.radians(angle_deg)
    psi = 1 + C * (math.sin(1.8 * theta_rad) - (1.0 / 3.0) * math.sin(1.8 * theta_rad) ** 3)
    return psi


def liquid_holdup(lambda_L, N_Fr, N_Lv, angle_deg, is_uphill=True):
    """
    Compute the actual in-situ liquid holdup EL(theta) for the given
    conditions, handling the 'transition' regime by interpolating
    between the segregated and intermittent holdups.

    :return: (EL fraction 0-1, pattern str used)
    """
    pattern, (L1, L2, L3, L4) = flow_pattern(lambda_L, N_Fr)

    if pattern != "transition":
        EL0 = _holdup_horizontal(pattern, lambda_L, N_Fr)
        psi = _inclination_factor(pattern, lambda_L, N_Lv, N_Fr, angle_deg, is_uphill)
        EL = EL0 * psi
        return min(max(EL, lambda_L), 1.0), pattern

    # Transition regime: interpolate between segregated and intermittent
    A = (L3 - N_Fr) / (L3 - L2)
    A = min(max(A, 0.0), 1.0)

    EL0_seg = _holdup_horizontal("segregated", lambda_L, N_Fr)
    psi_seg = _inclination_factor("segregated", lambda_L, N_Lv, N_Fr, angle_deg, is_uphill)
    EL_seg = EL0_seg * psi_seg

    EL0_int = _holdup_horizontal("intermittent", lambda_L, N_Fr)
    psi_int = _inclination_factor("intermittent", lambda_L, N_Lv, N_Fr, angle_deg, is_uphill)
    EL_int = EL0_int * psi_int

    EL = A * EL_seg + (1 - A) * EL_int
    return min(max(EL, lambda_L), 1.0), pattern


def no_slip_friction_factor(N_Re):
    """
    Explicit approximation to the smooth-pipe (Fanning) friction factor
    as a function of Reynolds number, as used in the original
    Beggs-Brill correlation.
    """
    if N_Re < 1.0:
        N_Re = 1.0
    return 0.0056 + 0.5 / N_Re ** 0.32


def two_phase_friction_factor(fn, lambda_L, EL):
    """
    Two-phase friction factor via the Beggs-Brill friction-factor-ratio
    correlation:  ftp = fn * exp(S)
    """
    y = lambda_L / EL ** 2
    if 1.0 < y < 1.2:
        S = math.log(2.2 * y - 1.2)
    else:
        ln_y = math.log(y)
        denom = -0.0523 + 3.182 * ln_y - 0.8725 * ln_y ** 2 + 0.01853 * ln_y ** 4
        if denom == 0:
            S = 0.0
        else:
            S = ln_y / denom
    S = max(min(S, 10.0), -10.0)  # guard against numerical blow-up
    return fn * math.exp(S)


def beggs_brill_gradient(P, T, gamma_g, liquid_sg, q_gas_mscfd, q_liquid_bpd,
                         d_in, angle_deg=90.0, sigma_dynecm=30.0,
                         mu_liquid_cp=1.0, mu_gas_cp=0.015,
                         roughness_in=0.0006):
    """
    Compute the total pressure gradient (psi/ft) at a single point in
    the wellbore using the Beggs-Brill correlation.

    :param P, T: Local pressure (psia) and temperature (R).
    :param gamma_g: Gas specific gravity (air=1).
    :param liquid_sg: Liquid specific gravity (water=1).
    :param q_gas_mscfd: Surface gas rate (Mscf/D).
    :param q_liquid_bpd: Total liquid rate (bbl/D, water+condensate).
    :param d_in: Tubing inside diameter, inches.
    :param angle_deg: Inclination from horizontal, degrees (90 = vertical,
                      0 = horizontal). Positive assumed uphill (producers).
    :param sigma_dynecm: Gas-liquid interfacial tension, dyne/cm.
    :param mu_liquid_cp, mu_gas_cp: Liquid and gas viscosities, cp.
    :param roughness_in: Pipe absolute roughness, inches.
    :return: (dPdh psi/ft [positive going deeper], diagnostics dict)
    """
    Z = z_factor(P, T, gamma_g)
    rho_g = gas_density(P, T, gamma_g, Z)     # lbm/ft3
    rho_l = liquid_sg * 62.4                  # lbm/ft3

    vsg, vsl = superficial_velocities(P, T, Z, q_gas_mscfd, q_liquid_bpd, d_in)
    vm = vsg + vsl
    if vm <= 0:
        raise ValueError("Total mixture velocity must be positive (check rates).")

    lambda_L = vsl / vm  # no-slip liquid holdup
    d_ft = d_in / 12.0

    N_Fr = vm ** 2 / (G * d_ft)
    N_Lv = 1.938 * vsl * (rho_l / sigma_dynecm) ** 0.25

    is_uphill = angle_deg >= 0
    EL, pattern = liquid_holdup(lambda_L, N_Fr, N_Lv, angle_deg, is_uphill)

    rho_m = rho_l * EL + rho_g * (1 - EL)               # in-situ mixture density
    rho_ns = rho_l * lambda_L + rho_g * (1 - lambda_L)  # no-slip density
    mu_ns = mu_liquid_cp * lambda_L + mu_gas_cp * (1 - lambda_L)

    N_Re = 1488.0 * rho_ns * vm * d_ft / mu_ns
    fn = no_slip_friction_factor(N_Re)
    ftp = two_phase_friction_factor(fn, lambda_L, EL)

    theta_rad = math.radians(angle_deg)

    elevation_grad = rho_m * math.sin(theta_rad) / 144.0              # psi/ft
    friction_grad = (ftp * rho_ns * vm ** 2) / (2 * GC * d_ft) / 144.0  # psi/ft

    # Kinetic-energy (acceleration) correction term - usually small except
    # at high velocity / low pressure; included for completeness.
    Ek = (rho_m * vm * vsg) / (GC * P * 144.0)
    Ek = min(Ek, 0.9)  # guard against near-singular behavior

    dPdh = (elevation_grad + friction_grad) / (1.0 - Ek)

    diagnostics = {
        "pattern": pattern,
        "EL": EL,
        "lambda_L": lambda_L,
        "vsg_ft_s": vsg,
        "vsl_ft_s": vsl,
        "vm_ft_s": vm,
        "N_Fr": N_Fr,
        "N_Lv": N_Lv,
        "N_Re": N_Re,
        "rho_m": rho_m,
        "rho_ns": rho_ns,
        "fn": fn,
        "ftp": ftp,
        "Ek": Ek,
        "Z": Z,
    }
    return dPdh, diagnostics


def multiphase_traverse(P_surface, T_surface, T_bottomhole, depth_ft,
                        gamma_g, liquid_sg, q_gas_mscfd, q_liquid_bpd,
                        d_in, angle_deg=90.0, n_segments=50, **bb_kwargs):
    """
    March down the wellbore computing the Beggs-Brill pressure gradient
    at each step (RK2 / midpoint scheme, matching bhp_dry_gas.py).

    :return: (P_bottomhole psia,
              profile list of dicts with depth/P/T + BB diagnostics)
    """
    dh = depth_ft / n_segments
    profile = [{"depth_ft": 0.0, "P": P_surface, "T": T_surface}]
    P = P_surface

    for i in range(n_segments):
        h1 = i * dh
        h2 = (i + 1) * dh
        T1 = T_surface + (T_bottomhole - T_surface) * (h1 / depth_ft)
        T2 = T_surface + (T_bottomhole - T_surface) * (h2 / depth_ft)
        T_mid = 0.5 * (T1 + T2)

        k1, _ = beggs_brill_gradient(P, T1, gamma_g, liquid_sg, q_gas_mscfd,
                                     q_liquid_bpd, d_in, angle_deg, **bb_kwargs)
        P_mid_est = P + k1 * (dh / 2.0)
        k2, diag = beggs_brill_gradient(P_mid_est, T_mid, gamma_g, liquid_sg,
                                        q_gas_mscfd, q_liquid_bpd, d_in,
                                        angle_deg, **bb_kwargs)

        P = P + k2 * dh
        entry = {"depth_ft": h2, "P": P, "T": T2}
        entry.update(diag)
        profile.append(entry)

    return P, profile
