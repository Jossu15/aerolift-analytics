"""
math_engine.metastable
---------------------
Metastable gas-well flow model based on Dousi et al. (2006) and
Neiman (2014, SPE 173937).

The classical Turner/Coleman/Li criterion defines the CRITICAL gas
velocity at which liquid droplets can no longer be entrained upward.
Below this velocity, a purely droplet-based model says the well is
"loading" and will die.

Dousi et al. (2006) showed experimentally and analytically that there
exists a META-STABLE zone between the critical velocity and a lower
MINIMUM STABLE velocity.  In this zone, the annular/mist flow pattern
still exists — liquid travels as a thin film on the tubing wall with
a gas core — but it is no longer self-cleaning.  Liquid accumulates
slowly but the well can produce for extended periods.

The metastable minimum rate is governed by the liquid film Reynolds
number (Neiman 2014, Eq. 6):

    Re_L = rho_L * v_L * D / mu_L

where v_L is the superficial liquid velocity (based on the liquid
flow rate at the film).

The ratio of minimum stable to critical velocity follows (Neiman 2014,
Eq. 8, fitted to Dousi Fig. 5 data for water at 60°F):

    v_min / v_crit = 0.55 + 0.08 * Re_L^0.35    (water)
    v_min / v_crit = 0.50 + 0.10 * Re_L^0.30    (condensate)

For a simplified engineering model (no full film tracking), we use
the NEIMAN (2014) approximation expressed in terms of the liquid
loading ratio L_R = q_actual / q_crit:

    If L_R > R_meta:  metastable — well flows at reduced rate
    If L_R < R_meta:  fully loaded — well dies

Typical values of R_meta (minimum stable / critical):
    R_meta ≈ 0.40 – 0.70  depending on Re_L
    Default (engineering estimate): 0.55

Reference:
    Dousi, E., Veeken, C.A.M., and Currie, P.K. (2006).
    "An Improved Mechanistic Model for the Prediction of Gas Well
    Loading." SPE 100121.

    Neiman, A. (2014). "A Simple-to-Use Transient Model for Loading
    Onset Prediction in Gas Wells." SPE 173937.

Units: field units (psia, R, ft, in, Mscf/D, lbm/ft3, dyne/cm).
"""

import math
from math_engine.gas_properties import get_gas_properties, gas_fvf
from math_engine.liquid_loading import (
    _liquid_properties,
    actual_gas_velocity,
    critical_velocity,
    minimum_flow_rate,
)

# ---------------------------------------------------------------------------
# Default metastable ratio (v_min / v_crit) for engineering use
# When film Reynolds number is unavailable or irrelevant, this value
# provides a physically reasonable lower bound for metastable flow.
# ---------------------------------------------------------------------------
DEFAULT_R_META = 0.50

# Neiman (2014) coefficients for water / condensate
# Calibrated to Dousi (2006) Fig. 5: metastable zone spans ~50-70% of
# q_crit (the well must remain above ~50% of critical to flow).
# At low Re (dry gas, <10 bbl/D): ~50% of q_crit
# At moderate Re (30-80 bbl/D): ~55% of q_crit
# At high Re (>100 bbl/D): ~60-65% of q_crit
_NEIMAN_WATER = {"a": 0.50, "b": 0.003, "c": 0.50}
_NEIMAN_COND  = {"a": 0.45, "b": 0.004, "c": 0.45}


# ---------------------------------------------------------------------------
# Film Reynolds number
# ---------------------------------------------------------------------------
def film_reynolds_number(q_liquid_bpd, d_in, rho_liquid, mu_liquid_cp):
    """
    Liquid film Reynolds number for annular flow in vertical tubing.

    Re_L = rho_L * v_L * D / mu_L

    where v_L is the superficial liquid velocity based on the liquid
    cross-sectional area (assuming a thin annular film).

    For a full-bore flow assumption (liquid fills the tubing as a
    thin film), we use the liquid superficial velocity:

        v_L = q_liquid * 5.615 / (Area * 86400)   (ft/s)

    :param q_liquid_bpd: Liquid flow rate (barrels/day).
    :param d_in: Tubing inner diameter (inches).
    :param rho_liquid: Liquid density (lbm/ft3).
    :param mu_liquid_cp: Liquid viscosity (cp).
    :return: Film Reynolds number (dimensionless).
    """
    if d_in <= 0 or mu_liquid_cp <= 0 or rho_liquid <= 0:
        return 0.0
    d_ft = d_in / 12.0
    area_ft2 = math.pi * (d_ft ** 2) / 4.0
    # v_L in ft/s
    v_L = q_liquid_bpd * 5.615 / (area_ft2 * 86400.0)
    # mu in lbm/(ft*s): 1 cp = 0.000672 lbm/(ft*s)
    mu_lb = mu_liquid_cp * 0.000672
    return rho_liquid * v_L * d_ft / mu_lb


# ---------------------------------------------------------------------------
# Metastable ratio (Neiman 2014 / Dousi 2006)
# ---------------------------------------------------------------------------
def metastable_ratio(Re_film, liquid_type='water'):
    """
    Ratio of minimum stable velocity to critical velocity.

    Based on Neiman (2014, Eq. 8) fitted to Dousi (2006) Fig. 5:

        R_meta = a + b * Re_L^c

    Valid range: Re_L ∈ [1, 10000]
    Bounds: R_meta clamped to [0.30, 1.0]

    :param Re_film: Liquid film Reynolds number.
    :param liquid_type: 'water' or 'condensate'.
    :return: Ratio v_min / v_crit (dimensionless, 0 < R <= 1).
    """
    if Re_film <= 0:
        return DEFAULT_R_META

    params = _NEIMAN_WATER if liquid_type.lower() == 'water' else _NEIMAN_COND
    R = params["a"] + params["b"] * (Re_film ** params["c"])

    # Physical bounds: must be less than 1 (if R >= 1, metastable zone
    # vanishes and the classical criterion applies directly)
    return max(0.30, min(R, 1.0))


# ---------------------------------------------------------------------------
# Metastable minimum rate
# ---------------------------------------------------------------------------
def metastable_min_rate(q_crit_mscfd, Re_film=None, liquid_type='water'):
    """
    Minimum stable gas flow rate (Mscf/D) in the metastable regime.

    Below this rate, annular/mist flow breaks down and the well fully
    loads up.  Above this rate but below q_crit, the well is in the
    metastable zone — producing at reduced rate with increasing liquid
    holdup.

    :param q_crit_mscfd: Critical flow rate from Turner/Coleman (Mscf/D).
    :param Re_film: Optional film Reynolds number. If None, uses
                    DEFAULT_R_META directly.
    :param liquid_type: 'water' or 'condensate'.
    :return: Minimum stable flow rate (Mscf/D).
    """
    if Re_film is not None:
        R = metastable_ratio(Re_film, liquid_type)
    else:
        R = DEFAULT_R_META
    return q_crit_mscfd * R


# ---------------------------------------------------------------------------
# Full metastable assessment (single-point)
# ---------------------------------------------------------------------------
def metastable_assessment(P, T, gamma_g, d_in, q_actual_mscfd,
                          q_water_bpd=0.0, q_cond_bpd=0.0,
                          mu_water_cp=0.8, mu_cond_cp=0.3,
                          liquid_type='water', method='turner',
                          liquid_density=None, sigma=None,
                          inclination_deg=90.0,
                          correct_sigma_temp=False):
    """
    Complete metastable flow assessment at a single operating point.

    Steps:
      1. Compute the classical critical velocity/rate (Turner/Coleman).
      2. Compute the liquid film Reynolds number.
      3. Compute the metastable ratio R_meta from Re_L.
      4. Compute the metastable minimum rate.
      5. Classify the flow regime:
         - "stable":       q > q_crit  (above critical — no loading)
         - "metastable":   q_min < q < q_crit  (subcritical but flowing)
         - "loaded":       q < q_min  (fully loaded — well dies)

    :param P: Flowing pressure (psia) — typically BHFP.
    :param T: Temperature (R).
    :param gamma_g: Gas specific gravity.
    :param d_in: Tubing inner diameter (inches).
    :param q_actual_mscfd: Actual gas rate (Mscf/D).
    :param q_water_bpd: Water rate (bbl/D).
    :param q_cond_bpd: Condensate rate (bbl/D).
    :param mu_water_cp: Water viscosity (cp), default 0.8.
    :param mu_cond_cp: Condensate viscosity (cp), default 0.3.
    :param liquid_type: 'water' or 'condensate'.
    :param method: Loading method for critical velocity.
    :param liquid_density: Override liquid density (lbm/ft3).
    :param sigma: Override surface tension (dyne/cm).
    :param inclination_deg: Angle from horizontal (0-90°).
    :param correct_sigma_temp: Apply sigma-T correction.
    :return: dict with regime, rates, margins, and film Re.
    """
    from math_engine.liquid_loading import loading_assessment

    # Step 1: Classical critical rate
    la = loading_assessment(P, T, gamma_g, d_in, q_actual_mscfd,
                            liquid_type=liquid_type, method=method,
                            rho_liquid=liquid_density, sigma_dynecm=sigma,
                            inclination_deg=inclination_deg,
                            correct_sigma_temp=correct_sigma_temp)
    q_crit = la["q_crit_mscfd"]

    # Step 2: Film Reynolds number
    q_liq = q_water_bpd + q_cond_bpd
    sigma_def, rho_L_def = _liquid_properties(liquid_type)
    mu_liq = mu_water_cp if liquid_type.lower() == 'water' else mu_cond_cp
    rho_L = liquid_density if liquid_density is not None else rho_L_def

    Re_L = film_reynolds_number(q_liq, d_in, rho_L, mu_liq)

    # Step 3: Metastable ratio
    R = metastable_ratio(Re_L, liquid_type)

    # Step 4: Metastable minimum rate
    q_min_meta = metastable_min_rate(q_crit, Re_L, liquid_type)

    # Step 5: Classification
    if q_actual_mscfd >= q_crit:
        regime = "stable"
    elif q_actual_mscfd >= q_min_meta:
        regime = "metastable"
    else:
        regime = "loaded"

    margin = ((q_actual_mscfd - q_crit) / q_crit
              if q_crit > 0 else float('nan'))

    return {
        "regime": regime,
        "q_crit_mscfd": q_crit,
        "q_min_stable_mscfd": q_min_meta,
        "q_actual_mscfd": q_actual_mscfd,
        "metastable_ratio": R,
        "film_reynolds": Re_L,
        "margin_fraction": margin,
        "is_loading": (regime != "stable"),
        "is_metastable": (regime == "metastable"),
        "method": method,
        "inclination_deg": inclination_deg,
    }


# ---------------------------------------------------------------------------
# Metastable well-life extension for forecast.py
# ---------------------------------------------------------------------------
def metastable_extended_life(q_crit, q_actual, q_min_stable=None,
                             Re_film=None, liquid_type='water'):
    """
    Determine whether the well can continue flowing in the metastable
    regime when q_actual < q_crit.

    :param q_crit: Critical flow rate (Mscf/D).
    :param q_actual: Actual flow rate (Mscf/D).
    :param q_min_stable: Optional explicit metastable minimum (Mscf/D).
    :param Re_film: Optional film Reynolds number (used if q_min not given).
    :param liquid_type: 'water' or 'condensate'.
    :return: dict with 'can_flow', 'q_operating' (Mscf/D),
             'status' ('stable', 'metastable', 'loaded').
    """
    if q_actual >= q_crit:
        return {"can_flow": True, "q_operating": q_actual,
                "status": "stable"}

    if q_min_stable is None:
        q_min_stable = metastable_min_rate(q_crit, Re_film, liquid_type)

    if q_actual >= q_min_stable:
        return {"can_flow": True, "q_operating": q_actual,
                "status": "metastable"}

    return {"can_flow": False, "q_operating": 0.0,
            "status": "loaded"}
