"""Backtesting engine: synthetic ground truth + walk-forward accuracy."""

from math_engine.backtest import (DAYS_PER_MONTH, score_predictions,
                                  walk_forward)
from math_engine.synthetic import make_mature_gas_well

# Seeds verified to die inside the 30-month window with enough history.
DYING_SEEDS = (0, 3, 11)


def test_synthetic_well_is_deterministic_and_physical():
    a = make_mature_gas_well(seed=0)
    b = make_mature_gas_well(seed=0)
    assert a["rows"] == b["rows"]  # seeded RNG -> reproducible
    rows = a["rows"]
    assert len(rows) >= 10
    qs = [r["q_gas_mscfd"] for r in rows]
    ps = [r["P_psia"] for r in rows]
    assert qs[0] > qs[-1]          # decline
    assert ps[0] > ps[-1]          # depletion
    assert all(r["is_loading"] is False for r in rows[:-1])


def test_truth_death_day_inside_window():
    for s in DYING_SEEDS:
        w = make_mature_gas_well(seed=s)
        assert w["truth_death_day"] < 30 * DAYS_PER_MONTH
        assert len(w["rows"]) >= 8


def test_walk_forward_predicts_death_within_one_month():
    for s in DYING_SEEDS:
        w = make_mature_gas_well(seed=s)
        preds = walk_forward(w["params"], w["gp_list"], w["p_list"],
                             min_fit=8, step=2)
        sc = score_predictions(preds, w["truth_death_day"])
        assert sc["n_preds"] > 0
        # noise-free synthetic history -> tight convergence expected
        assert sc["mae_months"] <= 1.0
        assert sc["hit_rate"] >= 0.8


def test_score_predictions_metric_math():
    rows = [{"predicted_death_day": 300.0},
            {"predicted_death_day": 330.0},
            {"predicted_death_day": None}]
    sc = score_predictions(rows, truth_death_day=310.0, tol_months=2.0)
    assert sc["n_preds"] == 2
    # errors: 10 d and 20 d -> mean 15 d = ~0.49 month
    assert abs(sc["mae_months"] - 15.0 / DAYS_PER_MONTH) < 1e-9
    assert sc["hit_rate"] == 1.0   # both within +/-2 months


def test_walk_forward_rejects_short_history():
    w = make_mature_gas_well(seed=0)
    try:
        walk_forward(w["params"], [1.0, 2.0], [100.0, 90.0], min_fit=8)
        raised = False
    except ValueError:
        raised = True
    assert raised
