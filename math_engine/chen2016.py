"""
math_engine.chen2016
--------------------
Chen et al. (2016) film-reversal inclination factor for deviated wells
(Fase 2, roadmap 2.3).

In a deviated well the film drains along the low side under the tangential
gravity component rho * g * sin(theta) (theta from horizontal, 90 deg =
vertical). The gas must overcome it; interfasial shear scales as
0.5 * fi * rhog * v^2 and balances the hold-down, so the required critical
velocity grows like 1 / sqrt(sin(theta)):

    v_crit(theta) = v_crit(vertical) * f_chen
    f_chen = 1 / sqrt(max(sin(theta), k_min))

f_chen(90 deg) = 1.0 and grows monotonically as the well deviates toward
horizontal, where unloading becomes practically impossible (divergence is
clamped so the multiplier stays bounded in engine-safe ranges).

The k_min / cap values are field-calibration hooks; the functional form is
the force-balance result.

Reference: Chen et al. (2016) film-reversal criterion for deviated gas
wells (inclination-aware critical velocity).
"""

import math

_MIN_SIN = 1e-4
_MAX_FACTOR = 12.0


def chen2016_inclination_factor(theta_from_horizontal_deg):
    """
    Critical-velocity multiplier for a deviated well.

    :param theta_from_horizontal_deg: Deviation angle, 0-90° (90 = vertical).
    :return: Multiplier >= 1.0 (1.0 at vertical).
    """
    theta = max(0.0, min(90.0, float(theta_from_horizontal_deg)))
    sin_t = math.sin(math.radians(theta))
    if sin_t <= 0:
        return _MAX_FACTOR
    factor = 1.0 / math.sqrt(max(sin_t, _MIN_SIN))
    return min(factor, _MAX_FACTOR)
