"""Tests: alert engine persistence, recompute endpoint, Slack fan-out."""

from api import alerts_engine, engines, models
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


class TestPortfolioDaysToRisk:
    """Fase 1.5.1 - the semaphore carries days_to_risk from the forecast."""

    def test_fallback_get_carries_days_to_risk(self, client, tested_well_id):
        r = client.get("/api/wells/alerts")
        one = next(a for a in r.json() if a["well_id"] == tested_well_id)
        assert "days_to_risk" in one

    def test_requires_db_for_forecast(self, client, well_id):
        db = SessionLocal()
        try:
            well = db.query(models.Well).filter(
                models.Well.id == well_id).one()
            without_db = engines.portfolio_alert(well, db=None)
        finally:
            db.close()
        # Without db there is no forecast to run -> explicit None.
        assert without_db["days_to_risk"] is None

    def test_days_to_risk_mirrors_forecast_view(self, client, well_id):
        """The semaphore carries exactly the forecast's health score."""
        db = SessionLocal()
        try:
            well = db.query(models.Well).filter(
                models.Well.id == well_id).one()
            alert = engines.portfolio_alert(well, db=db)
            fv = engines.forecast_view(db, well, max_steps=60)
        finally:
            db.close()
        assert alert["days_to_risk"] == fv.get("days_to_risk")

    def test_loaded_well_forecasts_death_on_day_zero(self, client, well_id,
                                                     monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        # High p_wh against a low p_res loads the natural flow point up
        # immediately -> the forecast dies on day 0 (deterministic).
        client.patch("/api/wells/{}".format(well_id),
                     json={"p_wh": 600.0, "p_res": 1500.0})
        db = SessionLocal()
        try:
            well = db.query(models.Well).filter(
                models.Well.id == well_id).one()
            alert = engines.portfolio_alert(well, db=db)
        finally:
            db.close()
        assert alert["severity"] == "red"
        assert alert["days_to_risk"] == 0

    def test_days_to_risk_persisted_on_recompute(self, client, well_id):
        client.patch("/api/wells/{}".format(well_id),
                     json={"p_wh": 600.0, "p_res": 1500.0})
        body = client.post("/api/wells/alerts/recompute").json()
        one = next(a for a in body if a["well_id"] == well_id)
        db = SessionLocal()
        try:
            row = db.query(models.WellAlert).filter(
                models.WellAlert.well_id == well_id).first()
        finally:
            db.close()
        assert row is not None
        assert row.days_to_risk == one["days_to_risk"] == 0


class TestAlertMarginPct:
    """Fase 1.5.2 - per-well threshold replaces the hardcoded 20%."""

    def test_patch_persists_margin(self, client, well_id):
        client.patch("/api/wells/{}".format(well_id),
                     json={"alert_margin_pct": 35.0})
        db = SessionLocal()
        try:
            well = db.query(models.Well).filter(
                models.Well.id == well_id).one()
        finally:
            db.close()
        assert well.alert_margin_pct == 35.0

    def test_margin_threshold_flips_semaphore(self, client, well_id):
        db = SessionLocal()
        try:
            well = db.query(models.Well).filter(
                models.Well.id == well_id).one()
            margin = engines.loading_snapshot(
                well, float(well.q_gas_nominal_mscfd))["margin_pct"]
            assert margin is not None

            # Threshold just above the margin -> at_risk (yellow).
            well.alert_margin_pct = min(margin + 1.0, 99.0)
            db.commit()
            tight = engines.portfolio_alert(db.get(models.Well, well.id),
                                            db=db)
            assert tight["severity"] == "yellow"
            assert tight["status"] == "at_risk"

            # Threshold below the margin -> back to stable (green).
            well.alert_margin_pct = max(margin - 1.0, 0.5)
            db.commit()
            loose = engines.portfolio_alert(db.get(models.Well, well.id),
                                            db=db)
            assert loose["severity"] == "green"
            assert loose["status"] == "stable"
        finally:
            db.close()

    def test_create_well_defaults_margin(self, client):
        body = {
            "tag": "W-MAR-1",
            "p_res": 1800.0, "t_res_f": 160.0, "gamma_g": 0.65,
            "p_wh": 150.0, "t_wh_f": 100.0,
            "tvd_ft": 7000.0, "tubing_id_in": 1.995,
            "q_water_bpd": 20.0, "q_gas_nominal_mscfd": 500.0,
        }
        r = client.post("/api/wells", json=body)
        assert r.status_code == 201, r.text
        assert r.json()["alert_margin_pct"] == 20.0

        r2 = client.post("/api/wells", json=dict(body, tag="W-MAR-2",
                                                 alert_margin_pct=8.0))
        assert r2.status_code == 201, r2.text
        assert r2.json()["alert_margin_pct"] == 8.0


class TestEmailNotifications:
    """Fase 1.5.3 - SMTP adapter (stdlib), no-op without EMAIL_* settings."""

    def test_no_config_is_noop(self, monkeypatch):
        from api.notifications import send_email_message
        monkeypatch.delenv("EMAIL_SMTP_HOST", raising=False)
        monkeypatch.delenv("EMAIL_FROM", raising=False)
        monkeypatch.delenv("EMAIL_TO", raising=False)
        assert send_email_message("s", "b") is False

    def test_sends_via_smtplib(self, monkeypatch):
        import smtplib

        sent = []

        class FakeSMTP:
            def __init__(self, host, port, timeout=10):
                self.host, self.port = host, port

            def starttls(self):
                pass

            def login(self, user, password):
                pass

            def sendmail(self, from_addr, to_addrs, msg):
                sent.append((from_addr, to_addrs, msg))

            def quit(self):
                pass

        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.test.local")
        monkeypatch.setenv("EMAIL_FROM", "alerts@aerolift")
        monkeypatch.setenv("EMAIL_TO", "ops@t, ing@t")
        from api import notifications
        assert notifications.send_email_message("Asunto 1", "Body") is True
        assert sent and sent[0][0] == "alerts@aerolift"
        assert sent[0][1] == ["ops@t", "ing@t"]
        assert "Subject: Asunto 1" in sent[0][2]

    def test_failure_is_silent_false(self, monkeypatch):
        import smtplib

        def boom(*args, **kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr(smtplib, "SMTP", boom)
        monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.test.local")
        monkeypatch.setenv("EMAIL_FROM", "a@t")
        monkeypatch.setenv("EMAIL_TO", "b@t")
        from api.notifications import send_email_message
        assert send_email_message("s", "b") is False


class TestEmailFanOut:
    def test_escalation_fans_out_email_and_dedups(self, client, well_id,
                                                  monkeypatch):
        emails = []
        monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.test.local")
        monkeypatch.setenv("EMAIL_FROM", "a@t")
        monkeypatch.setenv("EMAIL_TO", "b@t")
        monkeypatch.setattr(alerts_engine, "send_slack_message",
                            lambda text: True)
        monkeypatch.setattr(alerts_engine, "send_email_message",
                            lambda subject, body: emails.append(body) or True)
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
        finally:
            db.close()
        # green baseline + red escalation, red rerun deduplicated.
        assert len(emails) == 2
        assert "W-DEMO" in emails[1]
        assert "RED" in emails[1]