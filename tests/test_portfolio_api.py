"""Fase 3 - portfolio API endpoints (ranking, budget, summary)."""

import pytest

from tests.conftest import DEMO_WELL


def _seed_well(client, tag, **overrides):
    payload = dict(DEMO_WELL, tag=tag, **overrides)
    r = client.post("/api/wells", json=payload)
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    return wid


@pytest.fixture()
def pf_well(client, unique_tag):
    wid = _seed_well(client, unique_tag)
    yield wid
    client.delete("/api/wells/{}".format(wid))


class TestRanking:
    def test_ranking_returns_one_row_per_well(self, client, pf_well):
        r = client.get("/api/portfolio/ranking")
        assert r.status_code == 200, r.text
        body = r.json()
        assert any(row["well_id"] == pf_well for row in body)
        row = next(row for row in body if row["well_id"] == pf_well)
        assert row["tag"]
        assert row["at_risk"] in (True, False)
        assert row["q_nominal_mscfd"] == 900.0
        assert row["npv_usd"] is not None

    def test_ranking_sorted_best_npv_first(self, client, pf_well):
        body = client.get("/api/portfolio/ranking").json()
        npvs = [row["npv_usd"] for row in body
                if row["npv_usd"] is not None]
        assert npvs == sorted(npvs, reverse=True)

    def test_ranking_requires_pro(self, basic_client):
        r = basic_client.get("/api/portfolio/ranking")
        assert r.status_code == 403

    def test_ranking_isolation_other_operator(self, extra_client, pf_well):
        body = extra_client.get("/api/portfolio/ranking").json()
        assert all(row["well_id"] != pf_well for row in body)


class TestBudget:
    def test_budget_plan_runs_knapsack(self, client, pf_well):
        r = client.post("/api/portfolio/budget", json={
            "budget_usd": 500000.0,
            "gas_price_usd_mcf": 3.5,
            "one_per_well": True,
            "max_steps": 120,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["budget_usd"] == 500000.0
        assert body["total_cost_usd"] <= 500000.0
        assert body["total_npv_usd"] >= 0.0
        assert body["utilization_pct"] <= 100.0
        assert body["wells_selected"] == len(body["chosen"])

    def test_budget_rejects_zero_budget(self, client, pf_well):
        r = client.post("/api/portfolio/budget", json={"budget_usd": 0})
        assert r.status_code == 422

    def test_budget_requires_pro(self, basic_client, pf_well):
        r = basic_client.post("/api/portfolio/budget",
                              json={"budget_usd": 100000.0})
        assert r.status_code == 403


class TestSummary:
    def test_summary_kpis_and_optional_budget(self, client, pf_well):
        r = client.get("/api/portfolio/summary")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["wells_total"] >= 1
        assert body["gas_at_risk_mscfd"] >= 0.0
        assert body["wells_actionable"] >= 1
        assert body["positive_npv_usd"] is not None
        assert body["budget"] is None

        r2 = client.get("/api/portfolio/summary",
                        params={"budget_usd": 400000.0})
        body2 = r2.json()
        assert body2["budget"] is not None
        assert body2["budget"]["total_cost_usd"] <= 400000.0

    def test_summary_requires_pro(self, basic_client):
        assert basic_client.get("/api/portfolio/summary").status_code == 403