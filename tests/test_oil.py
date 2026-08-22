"""Oil-well extension: PVT correlations, Vogel IPR and lift screens."""

import pytest

from math_engine import oil_pvt
from math_engine.artificial_lift import rod_pump_check, size_esp
from tests.conftest import DEMO_WELL

OIL_PROPS = {"p_res": 2500.0, "t_res_f": 180.0, "tvd_ft": 8000.0,
             "api_gravity": 32.0, "gamma_g": 0.80,
             "gor_scf_stb": 500.0}


# ---------------- PVT ----------------
def test_standing_pb_gor_roundtrip():
    rs = oil_pvt.standing_solution_gor(2000.0, 180.0, 32.0, 0.80)
    pb = oil_pvt.standing_bubble_point(rs, 180.0, 32.0, 0.80)
    assert pb == pytest.approx(2000.0, rel=1e-6)


def test_bubble_point_increases_with_gor():
    pbs = [oil_pvt.standing_bubble_point(r, 180.0, 32.0, 0.80)
           for r in (100.0, 400.0, 800.0)]
    assert pbs[0] < pbs[1] < pbs[2]


def test_bo_above_one_and_viscosity_decreases_with_gas():
    bo = oil_pvt.standing_bo(400.0, 180.0, 0.80, 0.8655)
    assert 1.0 < bo < 2.0
    mu_dead = oil_pvt.beggs_robinson_dead_oil(180.0, 32.0)
    mu_live = oil_pvt.beggs_robinson_saturated(mu_dead, 400.0)
    assert mu_live < mu_dead


def test_viscosity_regimes():
    vis = oil_pvt.oil_viscosity(1500.0, 2000.0, 180.0, 32.0, 0.80,
                                oil_sg=0.8655)
    assert vis["regime"] == "saturated"
    unsat = oil_pvt.oil_viscosity(3000.0, 2000.0, 180.0, 32.0, 0.80,
                                  oil_sg=0.8655)
    assert unsat["regime"] == "undersaturated"
    # undersaturated oil thickens as pressure rises above Pb
    deeper = oil_pvt.oil_viscosity(3500.0, 2000.0, 180.0, 32.0, 0.80,
                                   oil_sg=0.8655)
    assert deeper["mu_o_cp"] >= unsat["mu_o_cp"]


def test_vogel_endpoints_and_inverse():
    # ratio at pwf/pr = 0.5: 1 - 0.2*0.5 - 0.8*0.25 = 0.70
    q_max = oil_pvt.vogel_qo_max(500.0, 1250.0, 2500.0)
    assert q_max == pytest.approx(500.0 / 0.70, rel=1e-9)
    assert oil_pvt.vogel_rate(q_max, 0.0, 2500.0) == \
        pytest.approx(q_max)
    assert oil_pvt.vogel_rate(q_max, 2500.0, 2500.0) == 0.0
    pwf = oil_pvt.vogel_pwf(q_max, 500.0, 2500.0)
    assert oil_pvt.vogel_rate(q_max, pwf, 2500.0) == \
        pytest.approx(500.0, rel=1e-6)
    assert oil_pvt.vogel_pwf(q_max, q_max * 1.01, 2500.0) is None


def test_vogel_calibration_rejects_bad_test_point():
    with pytest.raises(ValueError):
        oil_pvt.vogel_qo_max(-1.0, 1000.0, 2500.0)
    with pytest.raises(ValueError):
        oil_pvt.vogel_qo_max(500.0, 2600.0, 2500.0)


def test_validate_ranges_flags_outliers():
    ok = oil_pvt.validate_ranges(180.0, 32.0, 500.0)
    assert ok == []
    bad = oil_pvt.validate_ranges(60.0, 60.0, 10.0)
    assert len(bad) == 3


# ---------------- Artificial lift ----------------
def _qo_max():
    return oil_pvt.vogel_qo_max(500.0, 1250.0, 2500.0)


def test_esp_sizing_physical_consistency():
    res = size_esp(OIL_PROPS, target_rate_stb_d=600.0,
                   qo_max_stb_d=_qo_max(), water_cut=0.4,
                   thp_psia=150.0)
    assert res["intake_psi"] < res["discharge_psi"]
    assert res["stages"] >= 1
    assert res["motor_hp_recommended"] is None or \
        res["motor_hp_recommended"] >= res["motor_hp_required"]
    assert isinstance(res["warnings"], list)


def test_esp_rejects_impossible_target():
    with pytest.raises(ValueError):
        size_esp(OIL_PROPS, target_rate_stb_d=10_000_000.0,
                 qo_max_stb_d=_qo_max(), water_cut=0.0,
                 thp_psia=150.0)


def test_rod_pump_checklist_and_validation():
    res = rod_pump_check(OIL_PROPS, target_rate_stb_d=300.0,
                         water_cut=0.25, pump_depth_ft=5200.0,
                         plunger_dia_in=1.75, stroke_len_in=86.0,
                         spm=8.0)
    assert len(res["checks"]) >= 4
    assert res["achievable_rate_bpd"] > 0
    assert res["verdict"]
    with pytest.raises(ValueError):
        rod_pump_check(OIL_PROPS, 300.0, 0.25, 5200.0, 1.75, 86.0,
                       spm=30.0)


# ---------------- API contract ----------------
class TestOilApi:
    def _create_oil_well(self, client, tag):
        payload = dict(DEMO_WELL)
        payload.update({"tag": tag, "well_type": "oil",
                        "oil_api": 32.0})
        r = client.post("/api/wells", json=payload)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def test_create_oil_well_requires_api(self, client, unique_tag):
        payload = dict(DEMO_WELL)
        payload.update({"tag": "no-api-" + unique_tag,
                        "well_type": "oil"})
        assert client.post("/api/wells", json=payload).status_code == 422

    def test_oil_ipr_happy_path(self, client, tested_well_id):
        wid = self._create_oil_well(client, "oil-ipr-" + tested_well_id.__str__())
        r = client.post("/api/wells/{}/analysis/oil-ipr".format(wid),
                        json={"qo_test_stb_d": 500.0,
                              "pwf_test_psia": 1250.0})
        assert r.status_code == 200, r.text
        body = r.json()
        x = 1250.0 / DEMO_WELL["p_res"]
        ratio = 1.0 - 0.2 * x - 0.8 * x * x
        assert body["qo_max_stb_d"] == pytest.approx(
            500.0 / ratio, rel=0.01)
        assert body["p_bubble_psia"] > 0
        assert len(body["curve"]) >= 10

    def test_esp_on_gas_well_422(self, client, tested_well_id):
        r = client.post("/api/wells/{}/analysis/esp-sizing".format(
            tested_well_id),
            json={"qo_test_stb_d": 500.0, "pwf_test_psia": 1250.0,
                  "target_rate_stb_d": 600.0, "water_cut": 0.4,
                  "thp_psia": 150.0})
        assert r.status_code == 422

    def test_esp_sizing_on_oil_well(self, client, tested_well_id):
        wid = self._create_oil_well(client, "oil-esp-" + tested_well_id.__str__())
        r = client.post("/api/wells/{}/analysis/esp-sizing".format(wid),
                        json={"qo_test_stb_d": 500.0,
                              "pwf_test_psia": 1250.0,
                              "target_rate_stb_d": 600.0,
                              "water_cut": 0.4, "thp_psia": 150.0,
                              "gor_scf_stb": 500.0})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["stages"] >= 1
        assert body["intake_psi"] < body["discharge_psi"]

    def test_rod_pump_endpoint(self, client, tested_well_id):
        wid = self._create_oil_well(client, "oil-rod-" + tested_well_id.__str__())
        r = client.post("/api/wells/{}/analysis/rod-pump".format(wid),
                        json={"target_rate_stb_d": 300.0,
                              "water_cut": 0.25,
                              "pump_depth_ft": 5200.0,
                              "plunger_dia_in": 1.75,
                              "stroke_len_in": 86.0, "spm": 8.0})
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["checks"]) >= 4

    def test_basic_tier_blocked(self, basic_client, tested_well_id):
        wid = self._create_oil_well(basic_client,
                                    "oil-basic-" + tested_well_id.__str__())
        r = basic_client.post(
            "/api/wells/{}/analysis/oil-ipr".format(wid),
            json={"qo_test_stb_d": 500.0, "pwf_test_psia": 1250.0})
        assert r.status_code == 403
