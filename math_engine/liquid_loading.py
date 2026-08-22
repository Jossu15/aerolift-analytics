"""
math_engine.liquid_loading
--------------------------
Liquid loading prediction using the Turner et al. (1969) critical
velocity model, plus the widely-used Coleman et al. (1991) modification.

Physical concept
----------------
A gas well continuously produces small liquid droplets (water and/or
condensate) entrained in the gas stream. As long as the gas velocity is
high enough, drag force on a droplet exceeds gravity and the droplet is
carried to surface. As reservoir pressure depletes, gas velocity falls;
once it drops below a "critical" velocity, droplets can no longer be
lifted, liquid accumulates at bottomhole, and the well eventually loads
up and dies - even though plenty of gas remains in the reservoir.

Turner's model balances drag against gravity at the maximum stable
droplet size (critical Weber number), giving:

    v_crit = 1.593 * [sigma * (rho_L - rho_g) / rho_g^2]^0.25   (ft/s)

Coleman et al. removed ~20% of Turner's conservatism (constant 1.3),
generally recommended for lower flowing bottomhole pressures
(roughly < 500-1000 psia).

Units (field units, see CONTEXT.md):
    Density rho (lbm/ft3), sigma (dyne/cm), v (ft/s), P (psia),
    T (R), diameter d (in), rate q (Mscf/D)
"""

import math
from math_engine.gas_properties import get_gas_properties, gas_fvf

# Liquid property defaults (Turner's original assumptions)
_LIQUID_DEFAULTS = {
    "water":      {"sigma": 60.0, "rho_L": 67.0},
    "condensate": {"sigma": 20.0, "rho_L": 45.0},
}

# Leading constants for each method
_METHOD_CONSTANTS = {
    "turner": 1.593,
    "coleman": 1.3,
}


def _liquid_properties(liquid_type, sigma=None, rho_L=None):
    """Resolve liquid surface tension / density from type or overrides."""
    if sigma is not None and rho_L is not None:
        return sigma, rho_L
    key = (liquid_type or "water").lower()
    if key not in _LIQUID_DEFAULTS:
        raise ValueError("liquid_type must be 'water' or 'condensate'")
    defaults = _LIQUID_DEFAULTS[key]
    return (sigma if sigma is not None else defaults["sigma"],
            rho_L if rho_L is not None else defaults["rho_L"])


def critical_velocity(method, rho_liquid, rho_gas, sigma_dynecm):
    """
    Critical gas velocity (ft/s) for continuous liquid removal.

        v_crit = C * [sigma * (rho_L - rho_g) / rho_g^2]^(1/4)

    :param method: 'turner' (C=1.593) or 'coleman' (C=1.3).
    :param rho_liquid: Liquid density, lbm/ft3.
    :param rho_gas: In-situ gas density, lbm/ft3.
    :param sigma_dynecm: Interfacial tension, dyne/cm.
    """
    if rho_gas <= 0 or rho_liquid <= rho_gas:
        raise ValueError("Densities must be positive with rho_liquid > rho_gas.")
    C = _METHOD_CONSTANTS[method.lower()]
    return C * ((sigma_dynecm * (rho_liquid - rho_gas)) / (rho_gas ** 2)) ** 0.25


def turner_critical_velocity(p: float, T: float, gamma_g: float,
                             liquid_type: str = 'water',
                             sigma: float = None, rho_L: float = None) -> float:
    """
    Turner et al. (1969) minimum critical gas velocity required to
    continuously remove liquid droplets (Eqs. 8.32-8.34).

    :param p: Flowing pressure (psia).
    :param T: Flowing temperature (Rankine).
    :param gamma_g: Gas specific gravity (air = 1.0).
    :param liquid_type: 'water' or 'condensate' (used if sigma/rho_L None).
    :param sigma: Optional interfacial tension override (dynes/cm).
    :param rho_L: Optional liquid density override (lbm/ft3).
    :return: Critical gas velocity (ft/sec).
    """
    props = get_gas_properties(p, T, gamma_g)
    rho_g = props['density_lbm_ft3']
    sigma_eff, rho_L_eff = _liquid_properties(liquid_type, sigma, rho_L)

    if rho_g >= rho_L_eff:
        return 0.0  # Physically impossible - gas heavier than liquid

    return critical_velocity('turner', rho_L_eff, rho_g, sigma_eff)


def coleman_critical_velocity(p: float, T: float, gamma_g: float,
                              liquid_type: str = 'water',
                              sigma: float = None, rho_L: float = None) -> float:
    """
    Coleman et al. (1991) critical velocity - removes ~20% of Turner's
    built-in conservatism; generally recommended for wells with low
    flowing bottomhole pressures (< ~500-1000 psia).

    Same parameters as turner_critical_velocity().
    :return: Critical gas velocity (ft/sec).
    """
    props = get_gas_properties(p, T, gamma_g)
    rho_g = props['density_lbm_ft3']
    sigma_eff, rho_L_eff = _liquid_properties(liquid_type, sigma, rho_L)

    if rho_g >= rho_L_eff:
        return 0.0

    return critical_velocity('coleman', rho_L_eff, rho_g, sigma_eff)


def actual_gas_velocity(q_g: float, p: float, T: float, gamma_g: float,
                        d: float) -> float:
    """
    Actual average gas velocity in the tubing.

    v_actual = q_actual(ft3/s) / Area(ft2), with
    Bg = 0.02827 * z * T / P (ft3/scf).

    :param q_g: Gas flow rate (Mscf/D).
    :param p: Flowing pressure (psia).
    :param T: Flowing temperature (Rankine).
    :param gamma_g: Gas specific gravity (air = 1.0).
    :param d: Tubing inner diameter (inches).
    :return: Actual gas velocity (ft/sec).
    """
    props = get_gas_properties(p, T, gamma_g)
    Bg = gas_fvf(p, T, props['z'])

    q_sc_sec = (q_g * 1000.0) / 86400.0
    q_actual_ft3_sec = q_sc_sec * Bg

    d_ft = d / 12.0
    area_ft2 = math.pi * (d_ft ** 2) / 4.0

    return q_actual_ft3_sec / area_ft2


def minimum_flow_rate(p: float, T: float, gamma_g: float, d: float,
                      liquid_type: str = 'water',
                      method: str = 'turner') -> float:
    """
    Minimum gas flow rate (Mscf/D) required to keep the well unloaded.

    :param p: Flowing pressure (psia).
    :param T: Flowing temperature (Rankine).
    :param gamma_g: Gas specific gravity (air = 1.0).
    :param d: Tubing inner diameter (inches).
    :param liquid_type: 'water' or 'condensate'.
    :param method: 'turner' or 'coleman'.
    :return: Minimum (critical) gas rate, Mscf/D.
    """
    props = get_gas_properties(p, T, gamma_g)
    rho_g = props['density_lbm_ft3']
    sigma, rho_L = _liquid_properties(liquid_type)

    if rho_g >= rho_L:
        return float('inf')

    v_crit = critical_velocity(method, rho_L, rho_g, sigma)
    Bg = gas_fvf(p, T, props['z'])

    d_ft = d / 12.0
    area_ft2 = math.pi * (d_ft ** 2) / 4.0

    q_min_actual_ft3_sec = v_crit * area_ft2
    q_min_sc_sec = q_min_actual_ft3_sec / Bg
    return (q_min_sc_sec * 86400.0) / 1000.0


def loading_assessment(P, T, gamma_g, d, q_actual_mscfd,
                       liquid_type='water', rho_liquid=None,
                       sigma_dynecm=None, method='turner'):
    """
    Full liquid-loading assessment at a single point (typically evaluated
    at bottomhole flowing conditions - usually the most restrictive point,
    since velocity is lowest where pressure is highest).

    :param P: Local pressure (psia) - typically BHFP.
    :param T: Local temperature (R).
    :param gamma_g: Gas specific gravity (air = 1).
    :param d: Tubing ID, inches.
    :param q_actual_mscfd: Actual current gas rate, Mscf/D.
    :param liquid_type: 'water' or 'condensate' (defaults unless overridden).
    :param rho_liquid: Optional liquid density override, lbm/ft3.
    :param sigma_dynecm: Optional interfacial tension override, dyne/cm.
    :param method: 'turner' or 'coleman'.
    :return: dict with velocities, critical rate, is_loading flag and margin.
    """
    method_key = (method or 'turner').lower()
    if method_key not in _METHOD_CONSTANTS:
        raise ValueError("method must be 'turner' or 'coleman'")

    props = get_gas_properties(P, T, gamma_g)
    Z = props['z']
    rho_g = props['density_lbm_ft3']
    sigma, rho_L = _liquid_properties(liquid_type, sigma_dynecm, rho_liquid)

    if rho_g >= rho_L:
        # Degenerate case - cannot compute a meaningful threshold.
        v_crit = 0.0
    else:
        v_crit = critical_velocity(method_key, rho_L, rho_g, sigma)

    d_ft = d / 12.0
    area_ft2 = math.pi / 4.0 * d_ft ** 2

    v_actual = actual_gas_velocity(q_actual_mscfd, P, T, gamma_g, d)

    Bg = gas_fvf(P, T, Z)
    q_crit_mscfd = v_crit * area_ft2 / Bg * 86400.0 / 1000.0

    is_loading = q_actual_mscfd < q_crit_mscfd
    margin = ((q_actual_mscfd - q_crit_mscfd) / q_crit_mscfd
              if q_crit_mscfd > 0 else float('nan'))

    return {
        "method": method_key,
        "Z": Z,
        "rho_gas": rho_g,
        "v_crit_ft_s": v_crit,
        "v_actual_ft_s": v_actual,
        "q_crit_mscfd": q_crit_mscfd,
        "q_actual_mscfd": q_actual_mscfd,
        "is_loading": is_loading,
        "margin_fraction": margin,
    }


def check_liquid_loading(q_g: float, p: float, T: float, gamma_g: float,
                         d: float, liquid_type: str = 'water',
                         method: str = 'turner') -> dict:
    """
    Comprehensive check to determine if a gas well is liquid loaded.

    :param q_g: Current gas flow rate (Mscf/D).
    :param p: Flowing pressure (psia).
    :param T: Flowing temperature (Rankine).
    :param gamma_g: Gas specific gravity (air = 1.0).
    :param d: Tubing inner diameter (inches).
    :param liquid_type: 'water' or 'condensate'.
    :param method: 'turner' or 'coleman'.
    :return: dict with velocities, critical/min rates, is_loaded flag,
             and margin fraction (backward-compatible keys preserved).
    """
    result = loading_assessment(p, T, gamma_g, d, q_g,
                                liquid_type=liquid_type, method=method)

    return {
        "actual_velocity_ft_sec": round(result["v_actual_ft_s"], 2),
        "critical_velocity_ft_sec": round(result["v_crit_ft_s"], 2),
        "minimum_flow_rate_Mscf_D": round(result["q_crit_mscfd"], 2),
        "margin_fraction": result["margin_fraction"],
        "q_actual_mscfd": result["q_actual_mscfd"],
        "is_loaded": result["is_loading"],
        "liquid_type": liquid_type,
        "method": result["method"],
    }
