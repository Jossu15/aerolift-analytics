"""Intervention economics: toy-exact math + physics-based scenarios."""

import pytest

from math_engine.economics import CATALOG, evaluate_intervention, \
    project_economics

DEMO_PARAMS = {
    "p_wh": 200.0, "t_wh_f": 100.0, "t_res_f": 170.0,
    "tvd_ft": 8000.0, "tubing_id_in": 1.995, "gamma_g": 0.65,
    "q_water_bpd": 30.0, "liquid_sg": 1.0,
    "vlp_model": "beggs_brill", "load_method": "turner",
    "friction_multiplier": 1.0, "q_gas_nominal_mscfd": 900.0,
    "ipr": ("rs", {"C": 0.0837, "n": 0.652}),
}
MB = ([0.0, 800.0, 1800.0, 2600.0], [4200.0, 3400.0, 2700.0, 2200.0])


def test_project_economics_exact_toy_numbers():
    e = project_economics(incremental_mmscf=100.0, life_months=10,
                          gas_price_usd_mcf=3.0, cost_usd=100000.0,
                          discount_annual=0.0)
    assert e["gross_revenue_usd"] == pytest.approx(300000.0)
    assert e["npv_usd"] == pytest.approx(200000.0)
    assert e["roi_pct"] == pytest.approx(200.0)
    # 100k cost vs 30k/month revenue -> cumulative net turns positive
    # during month 4
    assert e["payback_months"] == 4


def test_discounting_lowers_npv_and_delays_payback():
    fast = project_economics(120.0, 12, 3.0, 200000.0, discount_annual=0.0)
    slow = project_economics(120.0, 12, 3.0, 200000.0, discount_annual=0.5)
    assert slow["npv_usd"] < fast["npv_usd"]
    assert slow["payback_months"] is None or \
        slow["payback_months"] >= fast["payback_months"]


def test_catalog_has_required_overrides():
    assert "target_tubing_id_in" in CATALOG["velocity_string"]["requires"]
    assert "target_p_wh_psia" in CATALOG["compression"]["requires"]


def test_velocity_string_scenario_runs_physics():
    res = evaluate_intervention(DEMO_PARAMS, MB[0], MB[1],
                                "velocity_string",
                                target_tubing_id_in=1.5)
    assert res["base_cum_mmscf"] > 0
    assert res["intervention_cum_mmscf"] > 0
    assert res["incremental_gas_mmscf"] >= 0.0
    assert isinstance(res["npv_usd"], float)


def test_velocity_string_needs_smaller_id():
    with pytest.raises(ValueError):
        evaluate_intervention(DEMO_PARAMS, MB[0], MB[1],
                              "velocity_string",
                              target_tubing_id_in=2.5)  # larger than 1.995


def test_compression_requires_target_pressure():
    with pytest.raises(ValueError):
        evaluate_intervention(DEMO_PARAMS, MB[0], MB[1], "compression")


def test_unknown_intervention_rejected():
    with pytest.raises(ValueError):
        evaluate_intervention(DEMO_PARAMS, MB[0], MB[1], "magic_box",
                              target_tubing_id_in=1.5)
