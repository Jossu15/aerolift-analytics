"""
Tests for math_engine.nodal_analysis (Step 1.5b - natural flow point).

Key regression: the solver must find BOTH intersections of a synthetic
J-curve (the liquid-loading instability signature) and return the
high-rate STABLE point by default.
"""

import math

import pytest

from math_engine.nodal_analysis import (
    calculate_pwf_ipr,
    calculate_pwf_vlp,
    find_all_intersections,
    find_natural_flow_point,
    find_well_flow_point,
    generate_curve,
)
from math_engine.nodal_helpers import (
    build_houpeurt_ipr_func,
    build_avg_tz_vlp_func,
)


# Synthetic J-curve: IPR from inverted Rawlins-Schellhardt
# (Pr=3000, C=5e-3, n=0.85) against a VLP with a pronounced low-rate
# loading hump. Verified numerically to cross exactly twice:
#   unstable ~124 Mscf/D @ ~2975 psia, stable ~3476 Mscf/D @ ~1238 psia.
def ipr_jcurve(q):
    val = 3000.0 ** 2 - (q / 5e-3) ** (1.0 / 0.85)
    return val ** 0.5 if val > 0 else 0.0


def vlp_jcurve(q):
    return 1150.0 + 3.0e5 / (q + 40.0) + 2e-7 * q * q


class TestMultiIntersectionSolver:
    def test_finds_both_intersections(self):
        pts = find_all_intersections(ipr_jcurve, vlp_jcurve,
                                     q_min=10, q_max=5000, n_scan=150)
        assert len(pts) == 2

    def test_intersection_brackets(self):
        pts = find_all_intersections(ipr_jcurve, vlp_jcurve,
                                     q_min=10, q_max=5000, n_scan=150)
        lo, hi = pts[0], pts[1]
        assert 100 < lo["q_mscfd"] < 160
        assert 3300 < hi["q_mscfd"] < 3650

    def test_curves_actually_cross_at_solutions(self):
        pts = find_all_intersections(ipr_jcurve, vlp_jcurve,
                                     q_min=10, q_max=5000, n_scan=150)
        for p in pts:
            diff = ipr_jcurve(p["q_mscfd"]) - vlp_jcurve(p["q_mscfd"])
            assert abs(diff) < 2.0  # tol=1 psia on Pwf difference

    def test_default_prefers_stable_high_rate(self):
        res = find_natural_flow_point(ipr_jcurve, vlp_jcurve,
                                      q_min=10, q_max=5000, n_scan=150)
        assert res is not None
        assert res["converged"] is True
        assert 3300 < res["q_mscfd"] < 3650
        assert "note" in res          # flags the instability signature
        assert len(res["all_intersections"]) == 2

    def test_lowest_rate_preference_returns_unstable(self):
        res = find_natural_flow_point(ipr_jcurve, vlp_jcurve,
                                      q_min=10, q_max=5000, n_scan=150,
                                      prefer="lowest_rate")
        assert 100 < res["q_mscfd"] < 160

    def test_single_crossing_case(self):
        # VLP with no hump below IPR start -> exactly one intersection
        def vlp_simple(q):
            return 800.0 + 2e-6 * q * q
        pts = find_all_intersections(ipr_jcurve, vlp_simple,
                                     q_min=10, q_max=5000, n_scan=100)
        assert len(pts) == 1


class TestBuiltInPhysicsWiring:
    def test_houpeurt_ipr_callable(self):
        f = build_houpeurt_ipr_func(2000.0, 1.5e6, 5e3)
        assert f(0.0) == pytest.approx(2000.0)
        assert f(2.0) == pytest.approx(
            math.sqrt(2000.0 ** 2 - (1.5e6 * 2.0 + 5e3 * 4.0)), rel=1e-9)
        assert f(99999.0) == 0.0  # beyond AOF clamps at zero

    def test_avg_tz_vlp_reference_value(self):
        # Same case as test_nodal.py scenario: matches prior validated run
        vlp = build_avg_tz_vlp_func(1000.0, 535.0, 610.0, 6000.0,
                                    1.995, 0.65)
        assert vlp(2.0) == pytest.approx(1157.4, abs=2.0)

    def test_calculate_pwf_ipr_clamps(self):
        assert calculate_pwf_ipr(1e6, 2000.0, 1.5e6, 5e3) == 0.0


class TestBackwardCompatibleWrapper:
    def test_find_well_flow_point_converges(self):
        res = find_well_flow_point(2000.0, 1.5e6, 5e3, 1000.0,
                                   535.0, 610.0, 6000.0, 1.995, 0.65)
        assert res["converged"] is True
        assert res["q_opt"] > 0
        assert res["p_wf_opt"] > 1000.0

    def test_no_intersection_reports_failure(self):
        # Reservoir too weak to lift anything: IPR always below VLP
        res = find_well_flow_point(1050.0, 8e7, 1e4, 1000.0,
                                   535.0, 610.0, 6000.0, 1.995, 0.65)
        assert res["converged"] is False
        assert res["q_opt"] == 0.0


class TestGenerateCurve:
    def test_handles_raising_functions(self):
        def flaky(q):
            if q > 50:
                raise ValueError("boom")
            return 1000.0 + q
        qs, pwfs = generate_curve(flaky, 10, 100, n_points=10)
        assert len(qs) == len(pwfs) == 10
        assert all(p is None for p in pwfs[5:])
