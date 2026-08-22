"""
Tests for math_engine.forecast (p/z material balance + well life).

Anchors: the synthetic depletion history used in the module demo
(Gp=[0,800,1800,2600] MMscf, P=[4200,3400,2700,2200] psia) must yield
a physically sensible OGIP and round-trip pressures.
"""

import pytest

from math_engine.forecast import (
    pz_from_p,
    fit_material_balance,
    pressure_at_cumulative,
    forecast_well_life,
)
from math_engine.nodal_helpers import (
    build_houpeurt_ipr_func,
    build_avg_tz_vlp_func,
)
from math_engine.liquid_loading import loading_assessment


T = 630.0
GG = 0.65

GP_HIST = [0.0, 800.0, 1800.0, 2600.0]
P_HIST = [4200.0, 3400.0, 2700.0, 2200.0]


@pytest.fixture(scope="module")
def mb_fit():
    return fit_material_balance(T, GG, GP_HIST, P_HIST)


class TestMaterialBalance:
    def test_ogip_plausible(self, mb_fit):
        _, _, G = mb_fit
        # History ends at 2600 of ~6000 produced -> mid-life well
        assert 5000 < G < 7000

    def test_intercept_positive_slope_negative(self, mb_fit):
        intercept, slope, _ = mb_fit
        assert intercept > 0
        assert slope < 0

    def test_pressure_roundtrip_at_history_point(self, mb_fit):
        intercept, slope, _ = mb_fit
        P = pressure_at_cumulative(2600.0, intercept, slope, T, GG)
        assert P == pytest.approx(2200.0, abs=30.0)

    def test_pressure_monotonic_declining_with_Gp(self, mb_fit):
        intercept, slope, _ = mb_fit
        Ps = [pressure_at_cumulative(g, intercept, slope, T, GG)
              for g in [1000.0, 2000.0, 3000.0, 4000.0]]
        assert Ps == sorted(Ps, reverse=True)

    def test_depleted_beyond_ogip_returns_zero(self, mb_fit):
        intercept, slope, G = mb_fit
        assert pressure_at_cumulative(G * 1.01, intercept, slope,
                                      T, GG) == 0.0

    def test_pz_over_z_identity(self):
        from math_engine.gas_properties import z_factor
        z = z_factor(2200.0, T, GG)
        assert pz_from_p(2200.0, T, GG) == pytest.approx(2200.0 / z)

    def test_bad_data_raises(self):
        with pytest.raises(ValueError):
            fit_material_balance(T, GG, [1.0, 2.0], [3000.0])  # no span
        with pytest.raises(ValueError):
            # Increasing pressures with increasing Gp -> positive slope
            fit_material_balance(T, GG, [0.0, 500.0], [2000.0, 2500.0])
        with pytest.raises(ValueError):
            fit_material_balance(T, GG, [0.0], [3000.0])  # too few


class TestForecastWellLife:
    def _make_funcs(self):
        ipr_factory = lambda Pr: build_houpeurt_ipr_func(Pr, 2000.0, 0.05)

        vlp = build_avg_tz_vlp_func(400.0, 560.0, 630.0, 8000.0,
                                    1.995, GG)

        def loading_check(q, Pr, pwf):
            r = loading_assessment(pwf, T, GG, 1.995, q)
            return bool(r["is_loading"])

        return ipr_factory, vlp, loading_check

    def test_forecast_produces_valid_history(self, mb_fit):
        intercept, slope, G = mb_fit
        ipr_f, vlp, lchk = self._make_funcs()
        history = forecast_well_life(intercept, slope, G, T, GG,
                                     ipr_f, vlp, lchk,
                                     Gp_start=2600.0,
                                     time_step_days=30, max_steps=12,
                                     q_min=1.0, q_max=20000.0)
        assert len(history) >= 1
        for row in history:
            assert {"day", "Gp", "Pr", "q_mscfd", "Pwf",
                    "status"} <= set(row)
            assert row["status"] in ("flowing", "loading_risk",
                                     "well_dead", "depleted")

    def test_rates_decline_or_stop(self, mb_fit):
        """Natural flow rate must never increase as the reservoir
        depletes (IPR shifts down; VLP constant)."""
        intercept, slope, G = mb_fit
        ipr_f, vlp, lchk = self._make_funcs()
        history = forecast_well_life(intercept, slope, G, T, GG,
                                     ipr_f, vlp, lchk,
                                     Gp_start=2600.0,
                                     time_step_days=30, max_steps=24,
                                     q_min=1.0, q_max=20000.0)
        qs = [row["q_mscfd"] for row in history if row["q_mscfd"] is not None]
        flowing = [q for q in qs if q > 0]
        assert all(q2 <= q1 + 1e-9
                   for q1, q2 in zip(flowing, flowing[1:]))

    def test_cumulative_advances_by_rate_times_dt(self, mb_fit):
        intercept, slope, G = mb_fit
        # Never-loading configuration (huge tubing -> low critical rate)
        vlp = build_avg_tz_vlp_func(150.0, 560.0, 630.0, 8000.0,
                                    1.995, GG)
        ipr_f = lambda Pr: build_houpeurt_ipr_func(Pr, 2000.0, 0.05)
        lchk = lambda q, Pr, pwf: False  # disable loading termination

        history = forecast_well_life(intercept, slope, G, T, GG,
                                     ipr_f, vlp, lchk,
                                     Gp_start=2600.0,
                                     time_step_days=30, max_steps=4)
        assert len(history) >= 2
        for prev, curr in zip(history, history[1:]):
            if curr["status"] in ("well_dead", "depleted"):
                break
            expected = prev["Gp"] + prev["q_mscfd"] * 30.0 / 1000.0
            assert curr["Gp"] == pytest.approx(expected, rel=1e-9)
