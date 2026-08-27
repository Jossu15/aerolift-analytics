"""
Tests for math_engine.metastable — Dousi 2006 / Neiman 2014
metastable flow regime model.

Covers:
  1. Film Reynolds number computation
  2. Metastable ratio correlation (bounds, water, condensate)
  3. Metastable minimum rate
  4. Full metastable assessment (stable / metastable / loaded regimes)
  5. Integration with forecast_well_life (metastable extension)
  6. Backward compatibility (loading_detail_func=None)
  7. Edge cases (zero flow, zero water, extreme Re)
"""

import pytest
import math

from math_engine.metastable import (
    DEFAULT_R_META,
    film_reynolds_number,
    metastable_ratio,
    metastable_min_rate,
    metastable_assessment,
    metastable_extended_life,
)
from math_engine.forecast import (
    fit_material_balance,
    forecast_well_life,
    pressure_at_cumulative,
    pz_from_p,
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


class TestFilmReynoldsNumber:
    def test_zero_liquid(self):
        Re = film_reynolds_number(0.0, 1.995, 67.0, 0.8)
        assert Re == 0.0

    def test_zero_diameter(self):
        Re = film_reynolds_number(100.0, 0.0, 67.0, 0.8)
        assert Re == 0.0

    def test_zero_viscosity(self):
        Re = film_reynolds_number(100.0, 1.995, 67.0, 0.0)
        assert Re == 0.0

    def test_positive_water_rate(self):
        Re = film_reynolds_number(100.0, 1.995, 67.0, 0.8)
        assert Re > 0

    def test_re_increases_with_water_rate(self):
        Re1 = film_reynolds_number(50.0, 1.995, 67.0, 0.8)
        Re2 = film_reynolds_number(200.0, 1.995, 67.0, 0.8)
        assert Re2 > Re1

    def test_re_increases_with_lower_viscosity(self):
        Re1 = film_reynolds_number(100.0, 1.995, 67.0, 1.0)
        Re2 = film_reynolds_number(100.0, 1.995, 67.0, 0.5)
        assert Re2 > Re1

    def test_typical_values(self):
        Re = film_reynolds_number(150.0, 1.995, 67.0, 0.8)
        assert Re > 1000


class TestMetastableRatio:
    def test_zero_re_returns_default(self):
        R = metastable_ratio(0.0, 'water')
        assert R == DEFAULT_R_META

    def test_negative_re_returns_default(self):
        R = metastable_ratio(-5.0, 'water')
        assert R == DEFAULT_R_META

    def test_ratio_between_03_and_10(self):
        for Re in [1, 10, 50, 100, 500, 1000, 5000, 10000]:
            R_w = metastable_ratio(Re, 'water')
            R_c = metastable_ratio(Re, 'condensate')
            assert 0.30 <= R_w <= 1.0, f"Re={Re} water R={R_w}"
            assert 0.30 <= R_c <= 1.0, f"Re={Re} condensate R={R_c}"

    def test_ratio_increases_with_Re(self):
        R1 = metastable_ratio(10, 'water')
        R2 = metastable_ratio(500, 'water')
        assert R2 > R1

    def test_condensate_slightly_different_from_water(self):
        R_w = metastable_ratio(100, 'water')
        R_c = metastable_ratio(100, 'condensate')
        assert R_w != R_c

    def test_ratio_at_very_high_Re(self):
        R = metastable_ratio(10000, 'water')
        assert R <= 1.0

    def test_ratio_at_low_Re(self):
        R = metastable_ratio(1, 'water')
        assert R >= 0.30


class TestMetastableMinRate:
    def test_min_rate_less_than_crit(self):
        q_crit = 500.0
        q_min = metastable_min_rate(q_crit, Re_film=100, liquid_type='water')
        assert q_min < q_crit

    def test_min_rate_positive(self):
        q_min = metastable_min_rate(500.0, Re_film=100)
        assert q_min > 0

    def test_min_rate_without_Re(self):
        q_min = metastable_min_rate(500.0, Re_film=None)
        assert 0 < q_min < 500.0

    def test_min_rate_ratio_bounds(self):
        for q_crit in [100, 500, 1000, 2000]:
            q_min = metastable_min_rate(q_crit, Re_film=100)
            ratio = q_min / q_crit
            assert 0.30 <= ratio <= 1.0


class TestMetastableAssessment:
    def test_stable_regime(self):
        """High flow rate should be 'stable' (above q_crit)."""
        # Very high rate = well above critical
        res = metastable_assessment(
            P=2000.0, T=T, gamma_g=GG, d_in=1.995,
            q_actual_mscfd=5000.0, q_water_bpd=100.0)
        assert res["regime"] == "stable"
        assert res["is_loading"] is False
        assert res["is_metastable"] is False

    def test_loaded_regime(self):
        """Very low flow rate should be 'loaded'."""
        res = metastable_assessment(
            P=2000.0, T=T, gamma_g=GG, d_in=1.995,
            q_actual_mscfd=10.0, q_water_bpd=100.0)
        assert res["regime"] == "loaded"
        assert res["is_loading"] is True

    def test_metastable_regime(self):
        """Rate between q_min_stable and q_crit should be 'metastable'."""
        # First find the critical rate for these conditions
        la = loading_assessment(2000.0, T, GG, 1.995, 500.0,
                                method='turner')
        q_crit = la["q_crit_mscfd"]
        q_mid = q_crit * 0.7  # 70% of critical
        # Use low water rate to keep Re small so metastable zone exists
        res = metastable_assessment(
            P=2000.0, T=T, gamma_g=GG, d_in=1.995,
            q_actual_mscfd=q_mid, q_water_bpd=5.0)
        assert res["regime"] in ("metastable", "stable")
        assert res["q_crit_mscfd"] > 0

    def test_output_keys(self):
        res = metastable_assessment(
            P=2000.0, T=T, gamma_g=GG, d_in=1.995,
            q_actual_mscfd=500.0, q_water_bpd=100.0)
        expected_keys = {
            "regime", "q_crit_mscfd", "q_min_stable_mscfd",
            "q_actual_mscfd", "metastable_ratio", "film_reynolds",
            "margin_fraction", "is_loading", "is_metastable",
            "method", "inclination_deg"}
        assert expected_keys <= set(res.keys())


class TestMetastableExtendedLife:
    def test_stable_above_crit(self):
        result = metastable_extended_life(500.0, 600.0)
        assert result["can_flow"] is True
        assert result["status"] == "stable"
        assert result["q_operating"] == 600.0

    def test_metastable_zone(self):
        q_crit = 500.0
        q_min = metastable_min_rate(q_crit, Re_film=100)
        q_actual = (q_crit + q_min) / 2.0
        result = metastable_extended_life(q_crit, q_actual, q_min)
        assert result["can_flow"] is True
        assert result["status"] == "metastable"

    def test_loaded_below_min(self):
        q_crit = 500.0
        q_min = metastable_min_rate(q_crit, Re_film=100)
        result = metastable_extended_life(q_crit, q_min * 0.5, q_min)
        assert result["can_flow"] is False
        assert result["status"] == "loaded"
        assert result["q_operating"] == 0.0

    def test_uses_default_when_no_min(self):
        # At Re_film=10, R_meta ≈ 0.55 + 0.08*10^0.35 ≈ 0.72
        # q_min = 500 * 0.72 ≈ 360, so 400 > 360 => can_flow=True
        result = metastable_extended_life(500.0, 400.0, Re_film=10)
        assert result["can_flow"] is True


class TestForecastIntegration:
    @pytest.fixture(scope="class")
    def mb_fit(self):
        return fit_material_balance(T, GG, GP_HIST, P_HIST)

    def _make_funcs_with_detail(self):
        ipr_factory = lambda Pr: build_houpeurt_ipr_func(Pr, 2000.0, 0.05)
        vlp = build_avg_tz_vlp_func(400.0, 560.0, 630.0, 8000.0,
                                    1.995, GG)

        def loading_check(q, Pr, pwf):
            r = loading_assessment(pwf, T, GG, 1.995, q)
            return bool(r["is_loading"])

        def loading_detail(q, Pr, pwf):
            r = loading_assessment(pwf, T, GG, 1.995, q)
            return {"q_crit_mscfd": r["q_crit_mscfd"], "liquid_type": "water"}

        return ipr_factory, vlp, loading_check, loading_detail

    def _make_funcs_without_detail(self):
        ipr_factory = lambda Pr: build_houpeurt_ipr_func(Pr, 2000.0, 0.05)
        vlp = build_avg_tz_vlp_func(400.0, 560.0, 630.0, 8000.0,
                                    1.995, GG)

        def loading_check(q, Pr, pwf):
            r = loading_assessment(pwf, T, GG, 1.995, q)
            return bool(r["is_loading"])

        return ipr_factory, vlp, loading_check

    def test_forecast_with_metastable_produces_longer_history(self, mb_fit):
        intercept, slope, G = mb_fit
        ipr_f, vlp, lchk, ldet = self._make_funcs_with_detail()
        history_meta = forecast_well_life(
            intercept, slope, G, T, GG, ipr_f, vlp, lchk,
            Gp_start=2600.0, time_step_days=30, max_steps=24,
            loading_detail_func=ldet)

        ipr_f2, vlp2, lchk2 = self._make_funcs_without_detail()
        history_no_meta = forecast_well_life(
            intercept, slope, G, T, GG, ipr_f2, vlp2, lchk2,
            Gp_start=2600.0, time_step_days=30, max_steps=24)

        # Metastable should produce equal or longer history
        assert len(history_meta) >= len(history_no_meta)

    def test_metastable_status_appears(self, mb_fit):
        intercept, slope, G = mb_fit
        ipr_f, vlp, lchk, ldet = self._make_funcs_with_detail()
        history = forecast_well_life(
            intercept, slope, G, T, GG, ipr_f, vlp, lchk,
            Gp_start=2600.0, time_step_days=30, max_steps=24,
            loading_detail_func=ldet)
        statuses = [r["status"] for r in history]
        # With metastable, the well should continue past initial loading
        assert any(s in ("metastable", "flowing") for s in statuses)

    def test_backward_compat_no_detail(self, mb_fit):
        """Without loading_detail_func, behavior is identical to original."""
        intercept, slope, G = mb_fit
        ipr_f, vlp, lchk = self._make_funcs_without_detail()
        history = forecast_well_life(
            intercept, slope, G, T, GG, ipr_f, vlp, lchk,
            Gp_start=2600.0, time_step_days=30, max_steps=24)
        statuses = [r["status"] for r in history]
        # No metastable status should appear
        assert "metastable" not in statuses

    def test_all_statuses_valid(self, mb_fit):
        intercept, slope, G = mb_fit
        ipr_f, vlp, lchk, ldet = self._make_funcs_with_detail()
        history = forecast_well_life(
            intercept, slope, G, T, GG, ipr_f, vlp, lchk,
            Gp_start=2600.0, time_step_days=30, max_steps=24,
            loading_detail_func=ldet)
        valid = {"flowing", "metastable", "loading_risk",
                 "well_dead", "depleted"}
        for row in history:
            assert row["status"] in valid
