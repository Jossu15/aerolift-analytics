"""Tests: alert engine persistence, recompute endpoint, Slack fan-out."""

from api import alerts_engine, models
from api.database import SessionLocal


class TestRecomputeEndpoint:
    def test_recompute_persists_and_serves_snapshot(self, client,
                                                    tested_well_id):
        r = client.post("/api/wells/alerts/recompute")
        assert r.status_code == 200, r.text
        body = r.json()
        assert any(a["well_id"] == tested_well_id for a in body)
        one = next(a for a in body if a["well_id"] == tested_well_id)
        assert one["computed_at"]

        r2 = client.get("/api/wells/alerts")
        one2 = next(a for a in r2.json() if a["well_id"] == tested_well_id)
        assert one2["computed_at"] == one["computed_at"]

    def test_recompute_requires_pro(self, basic_client):
        r = basic_client.post("/api/wells/alerts/recompute")
        assert r.status_code == 403

    def test_alerts_without_snapshots_fallback_online(self, client,
                                                     tested_well_id):
        r = client.get("/api/wells/alerts")
        assert r.status_code == 200
        one = next(a for a in r.json() if a["well_id"] == tested_well_id)
        assert one["computed_at"] is None
        assert one["tag"] == "W-DEMO"
        assert one["severity"] in {"green", "yellow", "orange", "red"}
        assert one["status"] in {"stable", "at_risk", "metastable", "loaded"}


class TestAlertEngine:
    def test_compute_stores_snapshot_history(self, client, well_id):
        db = SessionLocal()
        try:
            well = db.query(models.Well).filter(
                models.Well.id == well_id).one()
            alerts_engine.compute_portfolio_alerts(db, wells=[well])
            alerts_engine.compute_portfolio_alerts(db, wells=[well])
            rows = db.query(models.WellAlert).filter(
                models.WellAlert.well_id == well_id).order_by(
                models.WellAlert.id).all()
        finally:
            db.close()
        assert len(rows) == 2
        assert {r.severity for r in rows} <= \
            {"green", "yellow", "orange", "red"}
        assert rows[0].source == "manual"

    def test_first_poll_notifies_modeless(self, client, well_id, monkeypatch):
        calls = []
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
        monkeypatch.setattr(alerts_engine, "send_slack_message",
                            lambda text: calls.append(text) or True)
        db = SessionLocal()
        try:
            well = db.query(models.Well).filter(
                models.Well.id == well_id).one()
            alerts_engine.compute_portfolio_alerts(db, wells=[well])
            alerts_engine.compute_portfolio_alerts(db, wells=[well])
            first = db.query(models.WellAlert).filter(
                models.WellAlert.well_id == well_id).first()
        finally:
            db.close()
        # Same severity on the second poll -> single notification total.
        assert len(calls) == 1
        assert first.last_notified_severity == first.severity

    def test_escalation_pings_slack_and_dedups(self, client, well_id,
                                               monkeypatch):
        calls = []
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
        monkeypatch.setattr(alerts_engine, "send_slack_message",
                            lambda text: calls.append(text) or True)
        db = SessionLocal()
        try:
            well = db.query(models.Well).filter(
                models.Well.id == well_id).one()
            alerts_engine.compute_portfolio_alerts(db, wells=[well])
            client.patch("/api/wells/{}".format(well_id),
                         json={"q_gas_nominal_mscfd": 1.0})
            loaded = db.query(models.Well).filter(
                models.Well.id == well_id).one()
            alerts_engine.compute_portfolio_alerts(db, wells=[loaded])
            alerts_engine.compute_portfolio_alerts(db, wells=[loaded])
            rows = db.query(models.WellAlert).filter(
                models.WellAlert.well_id == well_id).order_by(
                models.WellAlert.id).all()
        finally:
            db.close()
        assert [r.severity for r in rows] == ["green", "red", "red"]
        assert len(calls) == 2  # green baseline + red escalation only

    def test_snapshots_isolated_by_owner(self, client, extra_client,
                                         tested_well_id):
        client.post("/api/wells/alerts/recompute")
        r = extra_client.get("/api/wells/alerts")
        assert r.status_code == 200
        assert all(a["well_id"] != tested_well_id for a in r.json())

    def test_well_delete_cleans_snapshots(self, client, well_id):
        client.post("/api/wells/alerts/recompute")
        db = SessionLocal()
        try:
            assert db.query(models.WellAlert).filter(
                models.WellAlert.well_id == well_id).count() == 1
        finally:
            db.close()
        client.delete("/api/wells/{}".format(well_id))
        db = SessionLocal()
        try:
            assert db.query(models.WellAlert).filter(
                models.WellAlert.well_id == well_id).count() == 0
        finally:
            db.close()


class TestNotifications:
    def test_no_webhook_is_noop(self, monkeypatch):
        from api.notifications import send_slack_message
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        assert send_slack_message("hola") is False

    def test_scheduler_off_by_default(self, monkeypatch):
        from api.scheduler import scheduler_enabled
        monkeypatch.delenv("ALERT_SCHEDULER_ENABLED", raising=False)
        assert scheduler_enabled() is False
        monkeypatch.setenv("ALERT_SCHEDULER_ENABLED", "1")
        assert scheduler_enabled() is True