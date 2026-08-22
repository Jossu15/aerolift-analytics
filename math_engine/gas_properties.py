import math
import typing
from functools import lru_cache

# ==============================================================================
# 1. PSEUDOCRITICAL PROPERTIES (Sutton's Correlation)
# Reference: CONTEXT.md / Chapter 1 (Eq 1.25 & 1.26)
# ==============================================================================
def sutton_pseudocriticals(gamma_g: float) -> typing.Tuple[float, float]:
    """
    Calculates pseudocritical pressure and temperature using Sutton's correlation.
    :param gamma_g: Gas specific gravity (air = 1.0)
    :return: Ppc (psia), Tpc (Rankine)
    """
    Ppc = 756.8 - 131.0 * gamma_g - 3.6 * (gamma_g ** 2)
    Tpc = 169.2 + 349.5 * gamma_g - 74.0 * (gamma_g ** 2)
    return Ppc, Tpc

# ==============================================================================
# 2. GAS DENSITY
# Reference: CONTEXT.md / Chapter 1 (Eq 1.58)
# ==============================================================================
def gas_density(P: float, T: float, gamma_g: float, z: float) -> float:
    """
    Calculates gas density using the real gas law.
    :param P: Pressure (psia)
    :param T: Temperature (Rankine)
    :param gamma_g: Gas specific gravity
    :param z: Gas compressibility factor
    :return: rho_g (lbm/ft^3)
    """
    return (2.70 * P * gamma_g) / (z * T)

# ==============================================================================
# 3. GAS VISCOSITY (Lee, Gonzalez, and Eakin)
# Reference: CONTEXT.md / Chapter 1 (Eq 1.63 to 1.67)
# ==============================================================================
def gas_viscosity_lee(P: float, T: float, gamma_g: float, z: float) -> float:
    """
    Calculates gas viscosity using the Lee, Gonzalez, and Eakin correlation.
    :return: mu_g (cp)
    """
    M = 28.96 * gamma_g  # Apparent molecular weight
    
    # Density in g/cm^3 for the viscosity correlation (Eq. 1.64)
    rho = 1.4935e-3 * (P * M) / (z * T)
    
    # Parameter K (Eq. 1.65)
    K = ((9.379 + 0.01607 * M) * (T ** 1.5)) / (209.2 + 19.26 * M + T)
    
    # Parameter X (Eq. 1.66)
    X = 3.448 + (986.4 / T) + 0.01009 * M
    
    # Parameter Y (Eq. 1.67)
    Y = 2.447 - 0.2224 * X
    
    # Viscosity (Eq. 1.63)
    mu_g = (1e-4) * K * math.exp(X * (rho ** Y))
    return float(mu_g)

# ==============================================================================
# 4. Z-FACTOR (Dranchuk and Abou-Kassem EOS)
# Reference: CONTEXT.md / Appendix A
# ==============================================================================
def z_factor_dak(P: float, T: float, Ppc: float, Tpc: float,
                 tol: float = 1e-8, max_iter: int = 100) -> float:
    """
    Calculates the gas compressibility factor (z) using the
    Dranchuk and Abou-Kassem Equation of State, solved by
    Newton-Raphson iteration on the reduced density.

    :param P: Pressure (psia)
    :param T: Temperature (Rankine)
    :param Ppc: Pseudo-critical pressure (psia)
    :param Tpc: Pseudo-critical temperature (R)
    :raises ValueError: if inputs are non-positive.
    """
    Ppr = P / Ppc
    Tpr = T / Tpc

    if Ppr <= 0 or Tpr <= 0:
        raise ValueError("Ppr and Tpr must be positive - check P, T inputs.")

    # Constants for DAK EOS (Appendix A)
    A1, A2, A3, A4, A5 = 0.3265, -1.0700, -0.5339, 0.01569, -0.05165
    A6, A7, A8, A9, A10, A11 = 0.5475, -0.7361, 0.1844, 0.1056, 0.6134, 0.7210

    def c1_c2_c3():
        c1 = A1 + A2 / Tpr + A3 / (Tpr ** 3) + A4 / (Tpr ** 4) + A5 / (Tpr ** 5)
        c2 = A6 + A7 / Tpr + A8 / (Tpr ** 2)
        c3 = A9 * (A7 / Tpr + A8 / (Tpr ** 2))
        return c1, c2, c3

    c1, c2, c3 = c1_c2_c3()

    def dak_z(rho_r):
        """DAK EOS expressed as Z(rho_r); solution satisfies dak_z(rho_r) == z."""
        return (1 + c1 * rho_r + c2 * rho_r ** 2 - c3 * rho_r ** 5
                + A10 * (1 + A11 * rho_r ** 2)
                * (rho_r ** 2 / Tpr ** 3) * math.exp(-A11 * rho_r ** 2))

    # Newton-Raphson on z with numerically differentiated residual
    z = 0.9
    for _ in range(max_iter):
        rho_r = 0.27 * Ppr / (z * Tpr)
        f = dak_z(rho_r) - z
        dz = 1e-6
        rho_r2 = 0.27 * Ppr / ((z + dz) * Tpr)
        f2 = dak_z(rho_r2) - (z + dz)
        dfdz = (f2 - f) / dz
        if dfdz == 0:
            break
        step = f / dfdz
        z_new = z - step
        if z_new <= 0:
            z_new = 0.3
        if abs(z_new - z) < tol:
            return float(z_new)
        z = z_new
    return float(z)


@lru_cache(maxsize=262144)
def _z_cached(P: float, T: float, gamma_g: float) -> float:
    Ppc, Tpc = sutton_pseudocriticals(gamma_g)
    return z_factor_dak(P, T, Ppc, Tpc)

# ==============================================================================
# HELPER FUNCTION: Get all properties at once
# ==============================================================================
def get_gas_properties(P: float, T: float, gamma_g: float) -> dict:
    """
    Calculates all major gas properties at given P and T.
    Returns native floats (no numpy scalars).
    """
    Ppc, Tpc = sutton_pseudocriticals(gamma_g)
    z = z_factor(P, T, gamma_g)
    rho = gas_density(P, T, gamma_g, z)
    mu = gas_viscosity_lee(P, T, gamma_g, z)

    return {
        "Ppc": float(Ppc),
        "Tpc": float(Tpc),
        "z": float(z),
        "density_lbm_ft3": float(rho),
        "viscosity_cp": float(mu)
    }

# ==============================================================================
# 5. CONVENIENCE WRAPPERS (Bg, cg, direct z-factor)
# Reference: Lee & Wattenbarger Chapter 1
# ==============================================================================
def z_factor(P: float, T: float, gamma_g: float) -> float:
    """
    Direct Z-factor from pressure/temperature/gravity (Sutton + DAK).
    Results are LRU-cached: repeated evaluations at similar conditions
    (nodal scans, traverses) become essentially free.

    :param P: Pressure (psia)
    :param T: Temperature (Rankine)
    :param gamma_g: Gas specific gravity (air = 1.0)
    :return: Gas compressibility factor z (dimensionless)
    """
    return _z_cached(round(float(P), 4), round(float(T), 2),
                     round(float(gamma_g), 4))


def gas_fvf(P: float, T: float, z: float) -> float:
    """
    Gas formation volume factor Bg in reservoir ft3 / scf (Eq. 1.53 form).

    :param P: Pressure (psia)
    :param T: Temperature (Rankine)
    :param z: Gas compressibility factor at (P, T)
    :return: Bg (ft3/scf)
    """
    return 0.02827 * z * T / P


def gas_compressibility(P: float, T: float, gamma_g: float, dP: float = 0.5) -> float:
    """
    Isothermal gas compressibility cg = 1/P - (1/z)(dz/dP), evaluated
    numerically with the DAK EOS. Used in pseudopressure and
    material-balance calculations.

    :param P: Pressure (psia)
    :param T: Temperature (Rankine)
    :param gamma_g: Gas specific gravity (air = 1.0)
    :param dP: Pressure perturbation for the numerical derivative (psia)
    :return: cg (1/psia)
    """
    z_plus = z_factor(P + dP, T, gamma_g)
    z_minus = z_factor(P - dP, T, gamma_g)
    z0 = z_factor(P, T, gamma_g)

    dzdP = (z_plus - z_minus) / (2.0 * dP)
    return 1.0 / P - (1.0 / z0) * dzdP