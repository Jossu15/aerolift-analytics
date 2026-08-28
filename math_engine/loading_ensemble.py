"""
math_engine.loading_ensemble
----------------------------
Regime-aware liquid-loading ensemble (Fase 2, roadmap 2.6).

Instead of the "max of all applicable criteria" heuristic, the ensemble
uses the Barnea (1986) flow-pattern selector to decide WHICH mechanism
binds for the well's operating regime:

    annular / mist  -> droplet family binds  (Turner, Ikpeka high-P
                       deformation, Belfroid when deviated)
    slug / churn    -> film family binds     (Wallis grand scale,
                       Liu-2018 film reversal, Li droplet + Belfroid as
                       a lower guard)
    bubble          -> conservatively droplet (well not loading yet)

The film family is always kept as an upper guard for large tubing and the
droplet family as a lower guard, so the output stays monotone and
conservative.

The pattern is classified at the critical (self-consistent) gas velocity,
so the mechanism reflects the regime that matters at the onset of loading.

Uncertainty band (roadmap 2.6): the ML residual correction is expressed in
pressure (psi); for the rate axis we map it proportionally:

    band -> q_crit * (1 +/- sig_q),  sig_q = (|mean| + std) / P_flow

    Uncertainty helpers
    -------------------
    loading_margin / residual_rate_band
"""

from math_engine import barnea, chen2016, ikpeka2018, liu2018
from math_engine.liquid_loading import (belfroid_correction, critical_velocity,
                                        film_flow_criterion, _liquid_properties)

_IKPEKA_P_PSIA = 3000.0        # droplet deformation becomes significant above
_BELFOID_THETA = 70.0          # deviated-wells correction threshold


def ensemble_critical_velocity(p, T, gamma_g, d, liquid_type='water',
                               sigma=None, rho_L=None,
                               inclination_deg=90.0,
                               correct_sigma_temp=False,
                               q_liquid_bbl_d=1.0):
    """
    Regime-aware ensemble critical velocity (ft/s) with full breakdown.

    :param p: Flowing pressure (psia).
    :param T: Flowing temperature (Rankine).
    :param gamma_g: Gas specific gravity.
    :param d: Tubing inner diameter (inches).
    :param liquid_type: 'water' or 'condensate'.
    :param sigma: Surface tension override (dyne/cm).
    :param rho_L: Liquid density override (lbm/ft3).
    :param inclination_deg: Angle from horizontal (0-90°).
    :param correct_sigma_temp: Apply sigma-T correction (only if no sigma
        override is given).
    :param q_liquid_bbl_d: Liquid flux used to resolve the flow pattern.
    :return: dict with v_crit_ft_s, regime, mechanism, alpha and the two
        candidate families.
    """
    from math_engine.liquid_loading import sigma_temperature_correction
    from math_engine.gas_properties import get_gas_properties

    props = get_gas_properties(p, T, gamma_g)
    rho_g = props['density_lbm_ft3']
    sigma_eff, rho_L_eff = _liquid_properties(liquid_type, sigma, rho_L)
    if correct_sigma_temp and sigma is None:
        sigma_eff = sigma_temperature_correction(
            sigma_eff, T, liquid_type=liquid_type)

    if rho_g >= rho_L_eff:
        return {"v_crit_ft_s": 0.0, "regime": "annular",
                "mechanism": "droplet", "alpha": 1.0,
                "droplet_v_ft_s": 0.0, "film_v_ft_s": 0.0,
                "models": []}

    # --- droplet family -------------------------------------------------
    v_base = critical_velocity('turner', rho_L_eff, rho_g, sigma_eff)
    if p > _IKPEKA_P_PSIA:
        v_base = ikpeka2018.ikpeka_corrected_velocity(
            v_base, rho_g, sigma_eff)
    v_droplet = v_base
    if inclination_deg < _BELFOID_THETA:
        v_droplet *= belfroid_correction(inclination_deg)
    v_li = critical_velocity('li', rho_L_eff, rho_g, sigma_eff)
    if inclination_deg < _BELFOID_THETA:
        v_li *= belfroid_correction(inclination_deg)

    # --- film family ----------------------------------------------------
    v_film = max(
        film_flow_criterion(d, rho_L_eff, rho_g)
        * chen2016.chen2016_inclination_factor(inclination_deg),
        liu2018.film_reversal_velocity(
            d, rho_L_eff, rho_g,
            theta_from_horizontal_deg=inclination_deg),
    )

    # --- regime decision at the critical gas velocity -------------------
    vsg_crit, vsl_crit = barnea.superficial_from_field(
        0.0, q_liquid_bbl_d, p, T, gamma_g, d)
    vsg_crit = v_droplet * 0.3048           # critical velocity as gas flux
    pattern = barnea.vertical_regime(vsg_crit, vsl_crit, d / 12.0 * 0.3048)

    if pattern["mechanism"] == "film":
        v_crit = max(v_film, v_li)
        models = ["liu2018-film", "wallis-film", "li-guard"]
        if inclination_deg < _BELFOID_THETA:
            models = models + ["chen2016-incl"]
    else:
        v_crit = v_droplet
        models = ["turner-droplet"]
        if p > _IKPEKA_P_PSIA:
            models[0] = "turner+ikpeka-droplet"
        if inclination_deg < _BELFOID_THETA:
            models = models + ["belfroid-incl"]
        # large tubing: film always guards the droplet prediction
        if d > 3.5:
            v_crit = max(v_crit, v_film)
            models = models + ["film-guard"]

    return {
        "v_crit_ft_s": round(float(v_crit), 4),
        "regime": pattern["regime"],
        "mechanism": pattern["mechanism"],
        "alpha": pattern["alpha"],
        "droplet_v_ft_s": round(float(v_droplet), 4),
        "film_v_ft_s": round(float(v_film), 4),
        "models": models,
    }


def loading_margin(q_actual_mscfd, q_crit_mscfd):
    """Rate margin fraction; negative means the well is loading."""
    if q_crit_mscfd <= 0:
        return float('nan')
    return (q_actual_mscfd - q_crit_mscfd) / q_crit_mscfd


def residual_rate_band(q_crit_mscfd, p_flow_psia,
                       residual_mean_psi=0.0, residual_std_psi=0.0):
    """
    Map the ML residual correction (psi) onto the critical rate axis.

    The residual statistics are pressure-domain; the dominant coupling
    between critical rate and pressure is quasi-linear, so the band is the
    proportional sigma = (|mean| + std) / P_flow, clamped to ±50 %.

    :return: dict with low/high critical rates and the sigma fraction.
    """
    sig = (abs(residual_mean_psi) + max(residual_std_psi, 0.0)) \
        / max(p_flow_psia, 1.0)
    sig = min(max(sig, 0.0), 0.5)
    return {
        "q_crit_low_mscfd": round(q_crit_mscfd * (1.0 - sig), 3),
        "q_crit_high_mscfd": round(q_crit_mscfd * (1.0 + sig), 3),
        "sigma_fraction": round(sig, 4),
    }
