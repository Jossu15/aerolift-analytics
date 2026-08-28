"""Fase 2.2-2.6: Barnea regime, Chen / Liu / Ikpeka physics and the
regime-aware loading ensemble."""

import pytest

from math_engine import barnea, chen2016, ikpeka2018, liu2018, loading_ensemble
from math_engine.liquid_loading import \
    loading_assessment, minimum_flow_rate

WATER_SIGMA = 60.0
WATER_RHO = 67.0


def _make_barnea_well(client, tag):
    from tests.conftest import DEMO_WELL
    payload = dict(DEMO_WELL, tag=tag, load_method="barnea")
    created = client.post("/api/wells", json=payload)
    assert created.status_code == 201, created.text
    return created.json()["id"]


# ---------------------------------------------------------------------------
# Barnea (1986) regime selector
# ---------------------------------------------------------------------------
class TestBarnea:
    def test_high_gas_annular_droplet(self):
        out = barnea.vertical_regime(15.0, 0.01, 0.076)
        assert out["regime"] == "annular"
        assert out["mechanism"] == "droplet"

    def test_intermittent_film(self):
        out = barnea.vertical_regime(2.0, 1.0, 0.076)
        assert out["mechanism"] == "film"
        assert out["regime"] in ("slug", "churn")

    def test_low_gas_bubble(self):
        out = barnea.vertical_regime(0.05, 1.0, 0.076)
        assert out["regime"] == "bubble"
        assert out["mechanism"] == "film"

    def test_alpha_monotonic_in_vsg(self):
        alphas = [barnea.drift_flux_alpha(v, 0.5, 0.076)
                  for v in (1.0, 3.0, 6.0, 12.0, 25.0)]
        assert alphas == sorted(alphas)
        assert alphas[-1] > alphas[0]

    def test_field_converter_magnitude(self):
        vsg, vsl = barnea.superficial_from_field(
            500.0, 10.0, 1500.0, 580.0, 0.62, 2.375)
        assert 0 < vsg < 120
        assert 0 < vsl < 2


# ---------------------------------------------------------------------------
# Chen (2016) inclination factor
# ---------------------------------------------------------------------------
class TestChen2016:
    def test_vertical_is_one(self):
        assert chen2016.chen2016_inclination_factor(90.0) == pytest.approx(1.0)

    def test_deviated_grows(self):
        f45 = chen2016.chen2016_inclination_factor(45.0)
        assert f45 > 1.0
        assert f45 < chen2016.chen2016_inclination_factor(15.0)

    def test_capped_horizontal(self):
        assert chen2016.chen2016_inclination_factor(0.0) == 12.0


# ---------------------------------------------------------------------------
# Liu (2018) film-reversal velocity
# ---------------------------------------------------------------------------
class TestLiu2018:
    def test_grows_with_diameter(self):
        v_small = liu2018.film_reversal_velocity(2.0, WATER_RHO, 4.0)
        v_large = liu2018.film_reversal_velocity(5.0, WATER_RHO, 4.0)
        assert v_large > v_small > 0

    def test_denser_gas_lowers_velocity(self):
        v_light = liu2018.film_reversal_velocity(3.0, WATER_RHO, 2.0)
        v_dense = liu2018.film_reversal_velocity(3.0, WATER_RHO, 6.0)
        assert v_dense < v_light

    def test_vertical_needs_most_velocity(self):
        v_vert = liu2018.film_reversal_velocity(
            3.0, WATER_RHO, 4.0, theta_from_horizontal_deg=90.0)
        v_dev = liu2018.film_reversal_velocity(
            3.0, WATER_RHO, 4.0, theta_from_horizontal_deg=45.0)
        assert v_vert > v_dev

    def test_unphysical_returns_zero(self):
        assert liu2018.film_reversal_velocity(3.0, 1.0, 10.0) == 0.0


# ---------------------------------------------------------------------------
# Ikpeka (2018) droplet deformation
# ---------------------------------------------------------------------------
class TestIkpeka2018:
    def test_high_pressure_lowers_velocity(self):
        v_hi = ikpeka2018.ikpeka_corrected_velocity(10.0, 8.0, WATER_SIGMA)
        v_lo = ikpeka2018.ikpeka_corrected_velocity(10.0, 3.0, WATER_SIGMA)
        assert v_hi < v_lo <= 10.0

    def test_ratio_bounded(self):
        for rho in (2.0, 4.0, 6.0, 12.0):
            ratio = ikpeka2018.deformation_constant_ratio(
                rho, 10.0, WATER_SIGMA)
            assert 0.6 <= ratio <= 1.0


# ---------------------------------------------------------------------------
# Loading ensemble (roadmap 2.6)
# ---------------------------------------------------------------------------
class TestLoadingEnsemble:
    def test_barnea_assessment_shape(self):
        out = loading_assessment(1500.0, 580.0, 0.62, 2.375, 2500.0,
                                 method='barnea')
        assert out["v_crit_ft_s"] > 0
        assert out["q_crit_mscfd"] > 0
        assert out["mechanism"] in ("film", "droplet")
        assert out["regime"] in ("bubble", "slug", "churn", "annular")
        assert isinstance(out["models"], list) and out["models"]

    def test_barnea_margin_sign_is_consistent(self):
        crit = loading_assessment(1500.0, 580.0, 0.62, 2.375, 100.0,
                                  method='barnea')["q_crit_mscfd"]
        above = loading_assessment(1500.0, 580.0, 0.62, 2.375,
                                   crit * 1.5, method='barnea')
        below = loading_assessment(1500.0, 580.0, 0.62, 2.375,
                                   crit * 0.5, method='barnea')
        assert above["margin_fraction"] > 0 and not above["is_loading"]
        assert below["margin_fraction"] < 0 and below["is_loading"]

    def test_ensemble_lower_guard_is_li_family(self):
        ens = loading_ensemble.ensemble_critical_velocity(
            1500.0, 580.0, 0.62, 2.375)
        assert ens["v_crit_ft_s"] > 0
        assert ens["droplet_v_ft_s"] > 0
        assert ens["film_v_ft_s"] > 0

    def test_minimum_flow_rate_barnea(self):
        q = minimum_flow_rate(1500.0, 580.0, 0.62, 2.375,
                              method='barnea')
        q_t = minimum_flow_rate(1500.0, 580.0, 0.62, 2.375,
                                method='turner')
        assert q > 0 and q_t > 0

    def test_residual_rate_band_clamped(self):
        band = loading_ensemble.residual_rate_band(
1000.0, 1500.0, residual_mean_psi=30.0, residual_std_psi=20.0)
        assert band["q_crit_low_mscfd"] < 1000.0 < band["q_crit_high_mscfd"]
        assert band["sigma_fraction"] == pytest.approx(50.0 / 1500.0,
                                                       abs=1e-3)

    def test_loading_margin(self):
        assert loading_ensemble.loading_margin(
            1200.0, 1000.0) == pytest.approx(0.2)
        assert loading_ensemble.loading_margin(
            800.0, 1000.0) == pytest.approx(-0.2)


# ---------------------------------------------------------------------------
# API integration (roadmap 2.6): a well whose load_method is 'barnea'
# flows through the ensemble in the analysis endpoint.
# ---------------------------------------------------------------------------
class TestBarneaApi:
    def test_well_load_method_barnea_accepted(self, client, unique_tag):
        wid = _make_barnea_well(client, unique_tag)
        try:
            load = client.get(
                "/api/wells/{}/analysis/loading".format(wid))
            assert load.status_code == 200, load.text
            body = load.json()
            assert body["v_crit_ft_s"] > 0
            assert body["method"] == "barnea"
        finally:
            client.delete("/api/wells/{}".format(wid))

    def test_well_update_load_method_barnea(self, client, unique_tag):
        from tests.conftest import DEMO_WELL
        created = client.post(
            "/api/wells", json=dict(DEMO_WELL, tag=unique_tag)).json()
        try:
            up = client.patch("/api/wells/{}".format(created["id"]),
                              json={"load_method": "barnea"})
            assert up.status_code == 200, up.text
            assert up.json()["load_method"] == "barnea"
            out = loading_assessment(1500.0, 580.0, 0.62, 2.375, 2500.0,
                                     method='barnea')
            assert out["mechanism"] in ("film", "droplet")
        finally:
            client.delete("/api/wells/{}".format(created["id"]))
