"""Fase 3 - portfolio ranking + budget knapsack (pure math, no DB)."""

import pytest

from math_engine.budget import optimize_budget
from math_engine.portfolio import INTERVENTIONS, \
    portfolio_summary, rank_portfolio, well_intervention_options

DEMO_PARAMS = {
    "p_wh": 200.0, "t_wh_f": 100.0, "t_res_f": 170.0,
    "tvd_ft": 8000.0, "tubing_id_in": 1.995, "gamma_g": 0.65,
    "q_water_bpd": 30.0, "liquid_sg": 1.0,
    "vlp_model": "beggs_brill", "load_method": "turner",
    "friction_multiplier": 1.0, "q_gas_nominal_mscfd": 900.0,
    "ipr": ("rs", {"C": 0.0837, "n": 0.652}),
}
MB = ([0.0, 800.0, 1800.0, 2600.0], [4200.0, 3400.0, 2700.0, 2200.0])


def _well(wid, tag, at_risk=True, q=900.0, **params_kw):
    params = dict(DEMO_PARAMS, **params_kw)
    return {
        "well_id": wid, "tag": tag, "params": params,
        "gp_list": MB[0], "p_list": MB[1],
        "q_nominal_mscfd": q, "at_risk": at_risk,
    }


# ------------------------------------------------------------------
# well_intervention_options
# ------------------------------------------------------------------
class TestWellOptions:
    def test_generates_default_targets_and_runs_both(self):
        opts = well_intervention_options(DEMO_PARAMS, MB[0], MB[1],
                                         well_id=7, tag="T-7")
        assert {o["intervention"] for o in opts} == set(INTERVENTIONS)
        for o in opts:
            assert o["well_id"] == 7 and o["tag"] == "T-7"
            assert o["incremental_gas_mmscf"] >= 0.0
            assert o["cost_usd"] > 0

    def test_sorted_best_npv_first(self):
        opts = well_intervention_options(DEMO_PARAMS, MB[0], MB[1])
        npvs = [o["npv_usd"] for o in opts]
        assert npvs == sorted(npvs, reverse=True)

    def test_costs_override_applies(self):
        opts = well_intervention_options(
            DEMO_PARAMS, MB[0], MB[1],
            costs_usd={"velocity_string": 1000.0})
        vs = next(o for o in opts
                  if o["intervention"] == "velocity_string")
        assert vs["cost_usd"] == 1000.0

    def test_invalid_target_skipped_not_fatal(self):
        opts = well_intervention_options(
            DEMO_PARAMS, MB[0], MB[1],
            targets={"target_tubing_id_in": 9.0})  # bigger than ID
        assert all(o["intervention"] != "velocity_string" for o in opts)


# ------------------------------------------------------------------
# rank_portfolio
# ------------------------------------------------------------------
class TestRankPortfolio:
    def test_ranks_two_wells_and_tags_reports(self):
        rows = rank_portfolio([_well(1, "W-1"), _well(2, "W-2")])
        assert len(rows) == 2
        ids = {r["well_id"] for r in rows}
        assert ids == {1, 2}
        for r in rows:
            assert r["tag"]
            assert r["option_count"] == len(INTERVENTIONS)
            assert r["best_option"] is not None

    def test_sorted_by_best_npv_desc(self):
        rows = rank_portfolio([_well(1, "W-1"), _well(2, "W-2")])
        npvs = [r["best_option"]["npv_usd"] for r in rows]
        assert npvs == sorted(npvs, reverse=True)

    def test_preserves_q_and_at_risk_flags(self):
        rows = rank_portfolio([_well(1, "W-1", at_risk=True, q=500.0),
                               _well(2, "W-2", at_risk=False, q=0.0)])
        by_id = {r["well_id"]: r for r in rows}
        assert by_id[1]["at_risk"] is True
        assert by_id[1]["q_nominal_mscfd"] == 500.0
        assert by_id[2]["at_risk"] is False


# ------------------------------------------------------------------
# portfolio_summary
# ------------------------------------------------------------------
class TestPortfolioSummary:
    def test_aggregates_field_kpis(self):
        rows = rank_portfolio([_well(1, "W-1", at_risk=True, q=600.0),
                               _well(2, "W-2", at_risk=True, q=400.0),
                               _well(3, "W-3", at_risk=False, q=0.0)])
        s = portfolio_summary(rows)
        assert s["wells_total"] == 3
        assert s["wells_at_risk"] == 2
        assert s["gas_at_risk_mscfd"] == 1000.0
        assert s["wells_actionable"] == 3
        assert s["positive_npv_usd"] > 0
        assert s["positive_incremental_gas_mmscf"] > 0
        assert s["wells_positive_npv"] >= 1


# ------------------------------------------------------------------
# optimize_budget (toy-exact knapsack cases)
# ------------------------------------------------------------------
class TestBudgetKnapsack:
    def _offers(self):
        return [
            {"well_id": 1, "tag": "W-1", "intervention": "velocity_string",
             "cost_usd": 100000.0, "npv_usd": 80000.0,
             "incremental_gas_mmscf": 60.0},
            {"well_id": 2, "tag": "W-2", "intervention": "compression",
             "cost_usd": 60000.0, "npv_usd": 60000.0,
             "incremental_gas_mmscf": 50.0},
            {"well_id": 3, "tag": "W-3", "intervention": "velocity_string",
             "cost_usd": 50000.0, "npv_usd": 30000.0,
             "incremental_gas_mmscf": 30.0},
        ]

    def test_exact_toy_knapsack_under_budget(self):
        res = optimize_budget(self._offers(), budget_usd=120000.0)
        # W-2 + W-3 (110k cost, 90k npv) beats W-1 alone (100k, 80k)
        chosen = {(o["well_id"], o["intervention"]) for o in res["chosen"]}
        assert chosen == {(2, "compression"), (3, "velocity_string")}
        assert res["total_cost_usd"] == 110000.0
        assert res["total_npv_usd"] == 90000.0
        assert res["utilization_pct"] == pytest.approx(
            100.0 * 110000 / 120000.0, abs=0.01)

    def test_unconstrained_picks_all_positive(self):
        res = optimize_budget(self._offers(), budget_usd=1e9)
        assert len(res["chosen"]) == 3
        assert res["total_npv_usd"] == 170000.0

    def test_empty_or_zero_budget_yields_nothing(self):
        assert optimize_budget([], 50000.0)["chosen"] == []
        assert optimize_budget(self._offers(), 0.0)["chosen"] == []
        assert optimize_budget(self._offers(), -5.0)["chosen"] == []

    def test_negative_npv_never_selected(self):
        offers = self._offers() + [
            {"well_id": 9, "tag": "W-9", "intervention": "beam_pump",
             "cost_usd": 70000.0, "npv_usd": -20000.0,
             "incremental_gas_mmscf": 5.0},
        ]
        res = optimize_budget(offers, 1e9)
        assert all(o.get("well_id") != 9 for o in res["chosen"])

    def test_one_per_well_keeps_best_npv(self):
        offers = [
            {"well_id": 1, "tag": "W-1", "intervention": "velocity_string",
             "cost_usd": 100000.0, "npv_usd": 80000.0,
             "incremental_gas_mmscf": 60.0},
            {"well_id": 1, "tag": "W-1", "intervention": "compression",
             "cost_usd": 60000.0, "npv_usd": 50000.0,
             "incremental_gas_mmscf": 40.0},
        ]
        res = optimize_budget(offers, 1e9, one_per_well=True)
        assert len(res["chosen"]) == 1
        assert res["chosen"][0]["intervention"] == "velocity_string"

    def test_one_per_well_false_selects_both(self):
        offers = [
            {"well_id": 1, "tag": "W-1", "intervention": "velocity_string",
             "cost_usd": 100000.0, "npv_usd": 80000.0,
             "incremental_gas_mmscf": 60.0},
            {"well_id": 1, "tag": "W-1", "intervention": "compression",
             "cost_usd": 60000.0, "npv_usd": 50000.0,
             "incremental_gas_mmscf": 40.0},
        ]
        res = optimize_budget(offers, 1e9, one_per_well=False)
        assert res["wells_selected"] == 1
        assert len(res["chosen"]) == 2