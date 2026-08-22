"""
Tests for math_engine.bhp_dry_gas (Step 1.2 - single-phase BHP).

Regression anchors: the ported RK2 marcher was validated against the
independent reference implementation in files/bhp_dry_gas.py and
matches to <0.2 psia on both static and flowing cases.
"""

import pytest

from math_engine.bhp_dry_gas import cullender_smith_bhp, friction_factor


class TestFrictionFactor:
    def test_typical_turbulent_range(self):
        f = friction_factor(2.441)
        # Nikuradse rough-pipe range for tubing
        assert 0.01 < f < 0.04

    def test_smaller_pipe_higher_friction(self):
        assert friction_factor(1.995) > friction_factor(2.992)


class TestStaticBHP:
    def test_reference_static_case(self):
        P, _ = cullender_smith_bhp(2000.0, 560.0, 660.0, 10000.0,
                                   0.65, q_mscfd=0.0, d_in=2.441,
                                   n_segments=50)
        assert P == pytest.approx(2533.1, abs=1.0)

    def test_implied_gradient_in_physical_band(self):
        P, _ = cullender_smith_bhp(2000.0, 560.0, 660.0, 10000.0,
                                   0.65, 0.0, 2.441, 50)
        gradient = (P - 2000.0) / 10000.0
        # Dry-gas static gradients typically 0.02-0.08 psi/ft
        assert 0.02 < gradient < 0.08

    def test_bhp_above_surface_pressure(self):
        P, _ = cullender_smith_bhp(2000.0, 560.0, 660.0, 10000.0,
                                   0.65, 0.0, 2.441, 50)
        assert P > 2000.0


class TestFlowingBHP:
    def test_reference_flowing_case(self):
        P, _ = cullender_smith_bhp(1800.0, 560.0, 660.0, 10000.0,
                                   0.65, q_mscfd=3000.0, d_in=2.441,
                                   n_segments=50)
        assert P == pytest.approx(2312.2, abs=1.0)

    def test_friction_adds_to_column_weight(self):
        # Same surface conditions: flowing must require more BH pressure
        P_static, _ = cullender_smith_bhp(1800.0, 560.0, 660.0, 10000.0,
                                          0.65, 0.0, 2.441, 50)
        P_flow, _ = cullender_smith_bhp(1800.0, 560.0, 660.0, 10000.0,
                                        0.65, 3000.0, 2.441, 50)
        assert P_flow > P_static

    def test_higher_rate_more_friction(self):
        P_lo, _ = cullender_smith_bhp(1800.0, 560.0, 660.0, 10000.0,
                                      0.65, 1000.0, 2.441, 50)
        P_hi, _ = cullender_smith_bhp(1800.0, 560.0, 660.0, 10000.0,
                                      0.65, 5000.0, 2.441, 50)
        assert P_hi > P_lo


class TestNumerics:
    def test_convergence_with_segment_count(self):
        P25, _ = cullender_smith_bhp(2000.0, 560.0, 660.0, 10000.0,
                                     0.65, 0.0, 2.441, 25)
        P120, _ = cullender_smith_bhp(2000.0, 560.0, 660.0, 10000.0,
                                      0.65, 0.0, 2.441, 120)
        assert abs(P25 - P120) < 5.0

    def test_profile_structure(self):
        n = 20
        P, profile = cullender_smith_bhp(2000.0, 560.0, 660.0, 10000.0,
                                         0.65, 500.0, 2.441, n)
        assert len(profile) == n + 1
        depths = [row[0] for row in profile]
        pressures = [row[1] for row in profile]
        assert depths == sorted(depths)
        assert pressures == sorted(pressures)          # monotonic increase
        assert profile[0][1] == pytest.approx(2000.0)   # starts at surface P
        assert profile[-1][1] == pytest.approx(P)

    def test_invalid_segments_raise(self):
        with pytest.raises(ValueError):
            cullender_smith_bhp(2000.0, 560.0, 660.0, 10000.0,
                                0.65, 0.0, 2.441, 0)
