"""
math_engine.nodal_helpers
-------------------------
Factory functions that wrap the built-in physics models into the
q -> Pwf callables consumed by math_engine.nodal_analysis. This keeps
the nodal solver agnostic of which correlation sits underneath:

    IPR options
        - Houpeurt pressure-squared (a, b coefficients)
        - Rawlins-Schellhardt inverted (C, n)  [build in caller via ipr]

    VLP options
        - Average T & z closed-form (Eq. 4.39)          [dry gas]
        - RK2 depth-marching (Cullender-Smith style)     [dry gas]
        - Full Beggs-Brill multiphase traverse           [gas + liquid]

Units: field units (see CONTEXT.md).
"""

from math_engine.hydraulics import calculate_pwf_vlp
from math_engine.bhp_dry_gas import cullender_smith_bhp
from math_engine.multiphase import multiphase_traverse


# ---------------------------------------------------------------------------
# IPR factories
# ---------------------------------------------------------------------------
def build_houpeurt_ipr_func(p_res, a, b):
    """
    Build a q -> Pwf callable from the Houpeurt quadratic deliverability
    equation: p_res^2 - p_wf^2 = a*q + b*q^2.

    :param p_res: Average reservoir pressure (psia).
    :param a: Laminar coefficient (psia^2/(Mscf/D)).
    :param b: Turbulent coefficient (psia^2/(Mscf/D)^2).
    """
    def ipr_pwf(q):
        delta = a * q + b * q * q
        val = p_res ** 2 - delta
        return val ** 0.5 if val > 0 else 0.0
    return ipr_pwf


def build_rawlins_schellhardt_ipr_func(Pr, C, n):
    """
    Build a q -> Pwf callable by inverting the Rawlins-Schellhardt
    backpressure equation q = C*(Pr^2 - Pwf^2)^n:

        Pwf = sqrt(Pr^2 - (q/C)^(1/n))
    """
    inv_n = 1.0 / n

    def ipr_pwf(q):
        if q <= 0:
            return float(Pr)
        val = Pr ** 2 - (q / C) ** inv_n
        return val ** 0.5 if val > 0 else 0.0
    return ipr_pwf


# ---------------------------------------------------------------------------
# VLP factories
# ---------------------------------------------------------------------------
def build_avg_tz_vlp_func(p_wh, T_wh, T_res, L, d, gamma_g, theta=0.0):
    """
    Dry-gas VLP via the average T&z closed form (Eq. 4.39), iterated
    internally on p_wf.
    """
    def vlp_pwf(q):
        if q <= 0:
            return float(p_wh)
        return calculate_pwf_vlp(q, p_wh, T_wh, T_res, L, d, gamma_g,
                                 theta=theta)
    return vlp_pwf


def build_dry_gas_vlp_func(P_surface, T_surface, T_bottomhole, depth_ft,
                           gamma_g, d_in, n_segments=40):
    """
    Dry-gas VLP via RK2 depth-marching (Cullender-Smith style physics:
    gravity + friction integrated with local real-gas properties).
    """
    def vlp_pwf(q):
        if q <= 0:
            return float(P_surface)
        P_bh, _ = cullender_smith_bhp(
            P_surface=P_surface,
            T_surface=T_surface,
            T_bottomhole=T_bottomhole,
            depth_ft=depth_ft,
            gamma_g=gamma_g,
            q_mscfd=q,
            d_in=d_in,
            n_segments=n_segments,
        )
        return P_bh
    return vlp_pwf


def build_beggs_brill_vlp_func(P_surface, T_surface, T_bottomhole, depth_ft,
                               gamma_g, liquid_sg, q_liquid_bpd, d_in,
                               angle_deg=90.0, n_segments=25,
                               friction_multiplier=1.0):
    """
    Two-phase VLP via the full Beggs-Brill multiphase traverse.
    Use when the well produces water and/or condensate - this is the
    model that produces the characteristic "J-shaped" tubing curve
    whose low-rate hump signals liquid-loading instability.
    """
    def vlp_pwf(q):
        if q <= 0:
            return None
        P_bh, _ = multiphase_traverse(
            P_surface=P_surface,
            T_surface=T_surface,
            T_bottomhole=T_bottomhole,
            depth_ft=depth_ft,
            gamma_g=gamma_g,
            liquid_sg=liquid_sg,
            q_gas_mscfd=q,
            q_liquid_bpd=q_liquid_bpd,
            d_in=d_in,
            angle_deg=angle_deg,
            n_segments=n_segments,
            friction_multiplier=friction_multiplier,
        )
        return P_bh
    return vlp_pwf
