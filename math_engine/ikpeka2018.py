"""
math_engine.ikpeka2018
----------------------
Ikpeka et al. (2018) droplet-deformation drag correction (Fase 2, roadmap
2.5).

High gas density deforms entrained droplets from spheres toward flattened
discs, raising the drag coefficient Cd. Because the droplet
terminal-velocity constant scales with Cd^-1/2, the deformation LOWERS the
critical velocity with respect to the spherical (Turner) value:

    We    = rho_g * v_crit^2 * d_drop / sigma        (droplet Weber number)
    Cd_r  = Cd_eff / Cd_sphere = 1 + k * We / (We + We_ref)
    v_corr = v_crit / sqrt(Cd_r)   =>   C_eff = C_base / sqrt(Cd_r)

Defaults keep the correction inside [0.60, 1.0] of the base constant across
the operating envelope; k / We_ref are field-calibration hooks for high-P
wells.

Reference: Ikpeka et al. (2018) droplet-deformation model for liquid
loading in high-pressure gas wells.
"""

import math

_K_DEFORM = 2.5
_WE_REF = 40.0
_D_DROP_M = 0.003
_MIN_RATIO = 0.60
_LBM_FT3_TO_KG_M3 = 16.0185


def droplet_weber(rho_gas, v_crit_ft_s, sigma_dynecm, d_drop_m=_D_DROP_M):
    """Droplet Weber number built from the critical velocity itself."""
    rho_g = rho_gas * _LBM_FT3_TO_KG_M3
    sigma_n_m = sigma_dynecm * 1e-3          # dyne/cm -> N/m
    if rho_g <= 0 or sigma_n_m <= 0:
        return 0.0
    v = v_crit_ft_s * 0.3048                 # ft/s -> m/s
    return rho_g * v * v * d_drop_m / sigma_n_m


def deformation_constant_ratio(rho_gas, v_crit_ft_s, sigma_dynecm,
                               k_deform=None, we_ref=None):
    """
    C_eff / C_base <= 1.0, dropping as pressure (We) rises.

    :param rho_gas: In-situ gas density (lbm/ft3).
    :param v_crit_ft_s: Base (spherical-droplet) critical velocity (ft/s).
    :param sigma_dynecm: Surface tension (dyne/cm).
    :param k_deform: Deformation strength (field hook).
    :param we_ref: Weber reference scale (field hook).
    """
    kd = _K_DEFORM if k_deform is None else k_deform
    wr = _WE_REF if we_ref is None else we_ref
    we = droplet_weber(rho_gas, v_crit_ft_s, sigma_dynecm)
    cd_ratio = 1.0 + kd * we / (we + wr)
    ratio = 1.0 / math.sqrt(cd_ratio)
    return max(ratio, _MIN_RATIO)


def ikpeka_corrected_velocity(v_crit_ft_s, rho_gas, sigma_dynecm):
    """Deformed-droplet critical velocity (never above the base value)."""
    ratio = deformation_constant_ratio(rho_gas, v_crit_ft_s, sigma_dynecm)
    return v_crit_ft_s * ratio
