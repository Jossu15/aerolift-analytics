"""
math_engine.liu2018
-------------------
Liu et al. (2018) film-reversal critical velocity (Fase 2, roadmap 2.4).

Loading onset in low-rate / large-tubing wells is set by reversal of the
liquid film, not by droplet fallback. The gas shear at the interface
(0.5 * fi * rhog * v^2) must hold the film against the tangential gravity
component:

    film thickness (uniform annular layer):  delta = H_L_film * D / 4
    v_film = sqrt( 2 * (rho_l - rho_g) * g * delta * sin(theta)
                   / (fi * rhog) )

The critical velocity grows with tubing size (delta ~ D/4), matching the
field observation that large-diameter wells load at higher gas rates, and
is capped by the inclination term where film reversal is easier.

Units: field inputs (lbm/ft3, inches); returns ft/s.

References: Liu et al. (2018) film-reversal loading criterion for gas
wells; Wallis (1969) one-dimensional film-model geometry.
"""

import math

_G = 9.81            # m/s2
_LBM_FT3_TO_KG_M3 = 16.0185
_DEFAULT_HOLDUP = 0.10       # uniform film liquid hold-up fraction
_DEFAULT_FILM_FRICTION = 0.02


def _thin_film_thickness_m(d_in, h_l_film):
    d_m = (d_in / 12.0) * 0.3048
    return max(float(h_l_film), 1e-4) * d_m / 4.0


def film_reversal_velocity(d_in, rho_liquid, rho_gas,
                           theta_from_horizontal_deg=90.0,
                           h_l_film=_DEFAULT_HOLDUP,
                           film_friction=_DEFAULT_FILM_FRICTION):
    """
    Minimum gas velocity (ft/s) to hold the film (film reversal).

    :param d_in: Tubing inner diameter (inches).
    :param rho_liquid: Liquid density (lbm/ft3).
    :param rho_gas: In-situ gas density (lbm/ft3).
    :param theta_from_horizontal_deg: Deviation, 0-90° (90 = vertical).
    :param h_l_film: Film liquid hold-up fraction (0 < h <= 1).
    :param film_friction: Interfacial friction factor.
    :return: Critical velocity (ft/s); 0.0 if film cannot be sustained.
    """
    if rho_gas <= 0 or rho_liquid <= rho_gas or film_friction <= 0:
        return 0.0
    theta = max(1.0, min(90.0, float(theta_from_horizontal_deg)))
    sin_t = math.sin(math.radians(theta))
    delta_m = _thin_film_thickness_m(d_in, h_l_film)
    rho_l = rho_liquid * _LBM_FT3_TO_KG_M3
    rho_g = rho_gas * _LBM_FT3_TO_KG_M3
    v_m_s = math.sqrt(2.0 * (rho_l - rho_g) * _G * delta_m * sin_t
                      / (film_friction * rho_g))
    return v_m_s / 0.3048
