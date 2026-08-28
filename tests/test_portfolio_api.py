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


class TestReportPdf:
    def test_report_pdf_is_a_pdf(self, client, pf_well):
        r = client.get("/api/portfolio/report.pdf")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 1000

    def test_report_pdf_accepts_budget(self, client, pf_well):
        r = client.get("/api/portfolio/report.pdf",
                       params={"budget_usd": 300000.0,
                               "max_steps": 120})
        assert r.status_code == 200
        assert r.content[:5] == b"%PDF-"

    def test_report_pdf_requires_pro(self, basic_client):
        assert (basic_client.get("/api/portfolio/report.pdf").status_code
                == 403)


class TestBatchRuns:
    def test_full_run_lifecycle(self, client, pf_well):
        from api import portfolio_batch
        r = client.post("/api/portfolio/runs",
                        json={"gas_price_usd_mcf": 3.5, "max_steps": 90})
        assert r.status_code == 202, r.text
        body = r.json()
        run_id = body["id"]
        assert body["status"] in ("queued", "running", "done")

        status = portfolio_batch.wait_for_run(run_id, timeout_seconds=300)
        assert status == "done", portfolio_batch.current_status(run_id)

        d = client.get("/api/portfolio/runs/{}".format(run_id))
        assert d.status_code == 200
        detail = d.json()
        assert detail["status"] == "done"
        assert detail["summary"]["wells_total"] >= 1
        assert len(detail["items"]) >= 1
        row = next(i for i in detail["items"] if i["well_id"] == pf_well)
        assert row["tag"]
        assert row["npv_usd"] is not None

    def test_list_runs_after_batch(self, client, pf_well):
        from api import portfolio_batch
        r = client.post("/api/portfolio/runs",
                        json={"gas_price_usd_mcf": 3.5, "max_steps": 90})
        run_id = r.json()["id"]
        portfolio_batch.wait_for_run(run_id, timeout_seconds=300)

        listing = client.get("/api/portfolio/runs").json()
        assert any(x["id"] == run_id for x in listing)
        head = next(x for x in listing if x["id"] == run_id)
        assert head["status"] == "done"
        assert head["wells_actionable"] >= 1

    def test_run_isolation_other_operator(self, client, extra_client,
                                          pf_well):
        from api import portfolio_batch
        r = client.post("/api/portfolio/runs",
                        json={"gas_price_usd_mcf": 3.5, "max_steps": 90})
        run_id = r.json()["id"]
        portfolio_batch.wait_for_run(run_id, timeout_seconds=300)
        assert (extra_client.get("/api/portfolio/runs/{}".format(run_id))
                .status_code == 404)
        assert extra_client.get("/api/portfolio/runs").json() == []

    def test_runs_require_pro(self, basic_client):
        assert basic_client.get("/api/portfolio/runs").status_code == 403
        assert (basic_client.post("/api/portfolio/runs",
                                  json={"max_steps": 60})
                .status_code == 403)