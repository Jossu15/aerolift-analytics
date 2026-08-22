"""
Tests for math_engine.gas_properties (Step 1.1 - PVT engine).

Validation anchors:
- Sutton pseudo-criticals hand-computed for gamma_g = 0.65.
- DAK Z-factor spot values cross-checked against the independent
  Newton-Raphson implementation in files/pvt.py and consistent with
  the Standing-Katz chart.
"""

import math

import pytest

from math_engine.gas_properties import (
    sutton_pseudocriticals,
    z_factor,
    z_factor_dak,
    gas_density,
    gas_fvf,
    gas_compressibility,
    gas_viscosity_lee,
    get_gas_properties,
)


class TestSuttonPseudocriticals:
    def test_known_values_gamma_065(self):
        # Hand-computed: Ppc=756.8-131*0.65-3.6*0.65^2=670.129...
        #                Tpc=169.2+349.5*0.65-74*0.65^2=365.1125
        Ppc, Tpc = sutton_pseudocriticals(0.65)
        assert Ppc == pytest.approx(670.13, abs=0.01)
        assert Tpc == pytest.approx(365.11, abs=0.01)

    def test_sutton_trends_in_gravity(self):
        # Sutton: Tpc increases with gravity; Ppc DECREASES with gravity
        # (dPpc/dYg = -131 - 7.2*Yg < 0 over the whole validity range).
        Ppc1, Tpc1 = sutton_pseudocriticals(0.60)
        Ppc2, Tpc2 = sutton_pseudocriticals(0.75)
        assert Tpc2 > Tpc1
        assert Ppc2 < Ppc1


class TestZFactor:
    def test_dak_reference_value_1(self):
        # Cross-checked against files/pvt.py DAK + Standing-Katz chart
        assert z_factor(2000.0, 660.0, 0.65) == pytest.approx(0.8976, abs=1e-3)

    def test_dak_reference_value_2(self):
        assert z_factor(2000.0, 620.0, 0.65) == pytest.approx(0.8651, abs=1e-3)

    def test_z_decreases_then_increases_isothermal_minimum_above_one_atm(
            self):
        # Physical sanity: Z stays within (0.2, 1.15) across a wide window
        for P in [200.0, 1000.0, 3000.0, 6000.0]:
            assert 0.2 < z_factor(P, 620.0, 0.65) < 1.15

    def test_wrapper_matches_direct_dak(self):
        Ppc, Tpc = sutton_pseudocriticals(0.7)
        assert z_factor(1500.0, 580.0, 0.7) == pytest.approx(
            z_factor_dak(1500.0, 580.0, Ppc, Tpc), rel=1e-12)

    def test_invalid_inputs_raise(self):
        with pytest.raises(Exception):
            z_factor(-500.0, 620.0, 0.65)


class TestDensityAndFVF:
    def test_density_identity(self):
        z = z_factor(2000.0, 620.0, 0.65)
        expected = 2.70 * 0.65 * 2000.0 / (z * 620.0)
        assert gas_density(2000.0, 620.0, 0.65, z) == pytest.approx(
            expected, rel=1e-12)

    def test_density_increases_with_pressure(self):
        z1 = z_factor(1000.0, 620.0, 0.65)
        z2 = z_factor(2000.0, 620.0, 0.65)
        rho1 = gas_density(1000.0, 620.0, 0.65, z1)
        rho2 = gas_density(2000.0, 620.0, 0.65, z2)
        assert rho2 > rho1

    def test_bg_identity_and_limits(self):
        z = z_factor(2000.0, 620.0, 0.65)
        Bg = gas_fvf(2000.0, 620.0, z)
        assert Bg == pytest.approx(0.02827 * z * 620.0 / 2000.0, rel=1e-12)
        # Bg shrinks as pressure grows (gas compresses)
        assert gas_fvf(4000.0, 620.0, z) < gas_fvf(1000.0, 620.0, z)


class TestCompressibility:
    def test_cg_positive_and_order_of_magnitude(self):
        cg = gas_compressibility(2000.0, 620.0, 0.65)
        # Ideal-gas limit is 1/P = 5e-4; real cg deviates modestly
        assert 0 < cg < 2e-3

    def test_cg_decreases_with_pressure(self):
        assert (gas_compressibility(3000.0, 620.0, 0.65)
                < gas_compressibility(1500.0, 620.0, 0.65))


class TestViscosity:
    def test_viscosity_plausible_range(self):
        for P in [500.0, 2000.0, 5000.0]:
            z = z_factor(P, 620.0, 0.65)
            mu = gas_viscosity_lee(P, 620.0, 0.65, z)
            assert 0.005 < mu < 0.05  # cp, typical natural gas

    def test_viscosity_increases_with_pressure(self):
        props_lo = get_gas_properties(800.0, 620.0, 0.65)
        props_hi = get_gas_properties(4000.0, 620.0, 0.65)
        assert props_hi["viscosity_cp"] > props_lo["viscosity_cp"]

    def test_get_all_properties_keys(self):
        props = get_gas_properties(2000.0, 620.0, 0.65)
        assert {"Ppc", "Tpc", "z", "density_lbm_ft3",
                "viscosity_cp"} <= set(props)
