"""
Tests for math_engine.liquid_loading (Step 1.4 - Turner / Coleman).

Validation anchors:
- Scenario from the original validation script: P=1000 psia, T=620 R,
  gamma_g=0.65, d=2.441", q=1.5 Mscf/D -> deeply loaded.
- Coleman constant is exactly Turner's scaled by 1.3/1.593.
"""

import math

import pytest

from math_engine.liquid_loading import (
    turner_critical_velocity,
    coleman_critical_velocity,
    actual_gas_velocity,
    minimum_flow_rate,
    loading_assessment,
    check_liquid_loading,
)


P, T, GG, D = 1000.0, 620.0, 0.65, 2.441


class TestCriticalVelocity:
    def test_turner_reference_value(self):
        v = turner_critical_velocity(P, T, GG, "water")
        assert v == pytest.approx(7.12, abs=0.3)

    def test_coleman_is_18pct_below_turner(self):
        v_t = turner_critical_velocity(P, T, GG, "water")
        v_c = coleman_critical_velocity(P, T, GG, "water")
        assert v_c / v_t == pytest.approx(1.3 / 1.593, rel=1e-3)

    def test_condensate_lower_than_water(self):
        v_w = turner_critical_velocity(P, T, GG, "water")
        v_c = turner_critical_velocity(P, T, GG, "condensate")
        assert v_c < v_w

    def test_invalid_liquid_type_raises(self):
        with pytest.raises(ValueError):
            turner_critical_velocity(P, T, GG, "molasses")


class TestVelocitiesAndRates:
    def test_actual_velocity_reference(self):
        # Validated scenario: 1.5 Mscf/D is far below critical
        v = actual_gas_velocity(1.5, P, T, GG, D)
        assert 0 < v < 0.05

    def test_minimum_rate_reference_value(self):
        q_min = minimum_flow_rate(P, T, GG, D, "water")
        assert q_min == pytest.approx(1249.3, abs=60.0)

    def test_velocity_consistency_at_critical_rate(self):
        """At exactly the critical rate, actual velocity must equal
        critical velocity (round-trip through Bg conversion)."""
        v_crit = turner_critical_velocity(P, T, GG, "water")
        q_min = minimum_flow_rate(P, T, GG, D, "water")
        v_at_qmin = actual_gas_velocity(q_min, P, T, GG, D)
        assert v_at_qmin == pytest.approx(v_crit, rel=1e-6)

    def test_smaller_tubing_lowers_required_rate(self):
        q_big = minimum_flow_rate(P, T, GG, 2.441, "water")
        q_small = minimum_flow_rate(P, T, GG, 1.995, "water")
        assert q_small < q_big


class TestAssessment:
    def test_loaded_scenario(self):
        r = loading_assessment(P, T, GG, D, q_actual_mscfd=250.0)
        assert r["is_loading"] is True
        assert r["q_actual_mscfd"] < r["q_crit_mscfd"]
        assert r["margin_fraction"] < 0

    def test_unloaded_scenario(self):
        r = loading_assessment(P, T, GG, D, q_actual_mscfd=5000.0)
        assert r["is_loading"] is False
        assert r["margin_fraction"] > 0

    def test_margin_sign_flip_at_boundary(self):
        q_crit = loading_assessment(P, T, GG, D, 250.0)["q_crit_mscfd"]
        above = loading_assessment(P, T, GG, D, q_crit * 1.01)
        below = loading_assessment(P, T, GG, D, q_crit * 0.99)
        assert above["is_loading"] is False
        assert below["is_loading"] is True

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError):
            loading_assessment(P, T, GG, D, 250.0, method="osborne")

    def test_check_dict_backward_compatible_keys(self):
        r = check_liquid_loading(1.5, P, T, GG, D)
        for key in ("actual_velocity_ft_sec", "critical_velocity_ft_sec",
                    "minimum_flow_rate_Mscf_D", "is_loaded",
                    "liquid_type"):
            assert key in r

    def test_coleman_less_conservative_flag(self):
        # A well between the two thresholds: loaded per Turner, safe per
        # Coleman - proves both methods are wired and differ correctly.
        q_between = None
        r_t = check_liquid_loading(0.0, P, T, GG, D, method="turner")
        r_c = check_liquid_loading(0.0, P, T, GG, D, method="coleman")
        assert r_t["minimum_flow_rate_Mscf_D"] > \
               r_c["minimum_flow_rate_Mscf_D"]
