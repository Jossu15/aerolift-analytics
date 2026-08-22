"""
Tests for math_engine.multiphase (Step 1.3 - Beggs & Brill).

Regression anchor: traverse validated against the independent
reference implementation in files/multiphase.py (matches <0.2 psia).
"""

import math

import pytest

from math_engine.multiphase import (
    flow_pattern,
    liquid_holdup,
    beggs_brill_gradient,
    multiphase_traverse,
    superficial_velocities,
)


DEMO = dict(P_surface=800.0, T_surface=560.0, T_bottomhole=630.0,
            depth_ft=8000.0, gamma_g=0.65, liquid_sg=1.0,
            q_gas_mscfd=800.0, q_liquid_bpd=40.0, d_in=2.441,
            angle_deg=90.0, n_segments=40)


class TestFlowPatternMap:
    def test_high_froude_low_liquid_is_distributed(self):
        # N_Fr must exceed L1 (~128 for lambda_L=0.05) for distributed
        pattern, _ = flow_pattern(0.05, 200.0)
        assert pattern == "distributed"

    def test_mid_froude_low_liquid_is_intermittent(self):
        pattern, _ = flow_pattern(0.05, 30.0)
        assert pattern == "intermittent"

    def test_low_froude_moderate_liquid_is_segregated(self):
        # lambda_L >= 0.01 and N_Fr below L2 boundary
        pattern, _ = flow_pattern(0.05, 1.0)
        assert pattern == "segregated"

    def test_returns_four_boundaries(self):
        _, bounds = flow_pattern(0.05, 5.0)
        assert len(bounds) == 4
        assert all(b > 0 for b in bounds)


class TestLiquidHoldup:
    def test_holdup_bounded_on_grid(self):
        for lam in [0.01, 0.05, 0.2, 0.45]:
            for fr in [0.5, 2.0, 10.0, 50.0]:
                EL, _ = liquid_holdup(lam, fr, 1.0, 90.0)
                assert lam <= EL <= 1.0

    def test_vertical_uphill_holdup_at_least_noslip(self):
        EL, _ = liquid_holdup(0.2, 1.0, 1.0, 90.0)
        assert EL >= 0.2


class TestGradient:
    def test_positive_uphill_gradient(self):
        dPdh, diag = beggs_brill_gradient(
            P=900.0, T=600.0, gamma_g=0.65, liquid_sg=1.0,
            q_gas_mscfd=800.0, q_liquid_bpd=40.0, d_in=2.441)
        assert dPdh > 0
        assert diag["pattern"] in ("segregated", "intermittent",
                                   "distributed", "transition")
        assert diag["EL"] <= 1.0

    def test_more_water_heavier_column(self):
        # BB is undefined at exactly zero liquid (lambda_L = 0), so
        # bracket with small vs large water rates instead.
        g_light, _ = beggs_brill_gradient(
            900.0, 600.0, 0.65, 1.0, 800.0, 5.0, 2.441)
        g_heavy, _ = beggs_brill_gradient(
            900.0, 600.0, 0.65, 1.0, 800.0, 60.0, 2.441)
        assert g_heavy > g_light

    def test_zero_rates_raise(self):
        with pytest.raises(ValueError):
            beggs_brill_gradient(900.0, 600.0, 0.65, 1.0,
                                 0.0, 0.0, 2.441)

    def test_superficial_velocity_scaling(self):
        Z = 0.9
        vsg, vsl = superficial_velocities(1000.0, 620.0, Z,
                                          1000.0, 50.0, 2.441)
        # Halving pressure (expanding gas) roughly doubles vsg
        vsg_lo, _ = superficial_velocities(500.0, 620.0, Z,
                                           1000.0, 50.0, 2.441)
        assert vsg_lo > vsg
        assert vsl > 0


class TestTraverse:
    def test_reference_traverse_case(self):
        P_bh, profile = multiphase_traverse(**DEMO)
        assert P_bh == pytest.approx(1946.0, abs=1.5)
        assert len(profile) == DEMO["n_segments"] + 1

    def test_pressure_monotonic_with_depth(self):
        _, profile = multiphase_traverse(**DEMO)
        Ps = [row["P"] for row in profile]
        assert all(p2 >= p1 - 1e-9 for p1, p2 in zip(Ps, Ps[1:]))

    def test_water_loads_the_column(self):
        light = dict(DEMO)
        heavy = dict(DEMO)
        light["q_liquid_bpd"] = 5.0
        heavy["q_liquid_bpd"] = 120.0
        P_light, _ = multiphase_traverse(**light)
        P_heavy, _ = multiphase_traverse(**heavy)
        assert P_heavy > P_light

    def test_higher_gas_rate_lowers_required_bhp(self):
        # At these rates the well is past the J-curve minimum: more gas
        # -> lighter effective column (lower holdup).
        P_low, _ = multiphase_traverse(q_gas_mscfd=300.0, **{
            k: v for k, v in DEMO.items() if k != "q_gas_mscfd"})
        P_high, _ = multiphase_traverse(q_gas_mscfd=2000.0, **{
            k: v for k, v in DEMO.items() if k != "q_gas_mscfd"})
        assert P_high < P_low


class TestFrictionMultiplier:
    """Field calibration knob on the BB friction gradient (Step 3.2)."""

    def test_default_is_identity(self):
        P_a, _ = multiphase_traverse(**DEMO)
        P_b, _ = multiphase_traverse(friction_multiplier=1.0, **DEMO)
        assert P_a == pytest.approx(P_b, abs=1e-9)

    def test_monotonic_in_multiplier(self):
        rough = dict(DEMO)
        smooth = dict(DEMO)
        rough["friction_multiplier"] = 2.5
        smooth["friction_multiplier"] = 0.4
        P_1, _ = multiphase_traverse(**DEMO)
        P_rough, _ = multiphase_traverse(**rough)
        P_smooth, _ = multiphase_traverse(**smooth)
        assert P_rough > P_1 > P_smooth

    def test_nonpositive_rejected(self):
        with pytest.raises(ValueError):
            beggs_brill_gradient(900.0, 600.0, 0.65, 1.0,
                                 800.0, 40.0, 2.441,
                                 friction_multiplier=0.0)

    def test_diagnostics_report_the_multiplier(self):
        _, diag = beggs_brill_gradient(
            900.0, 600.0, 0.65, 1.0, 800.0, 40.0, 2.441,
            friction_multiplier=1.7)
        assert diag["friction_multiplier"] == pytest.approx(1.7)
