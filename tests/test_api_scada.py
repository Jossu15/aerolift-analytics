"""API tests: SCADA telemetry ingestion and live status."""


def _telemetry(tag, q_gas, q_water=30.0, p_wh=200.0):
    return {"well_tag": tag, "q_gas_mscfd": q_gas,
            "q_water_bpd": q_water, "p_wh_psia": p_wh}


class TestTelemetry:
    def test_stable_reading(self, client, scada_well, unique_tag):
        r = client.post("/api/scada/telemetry",
                        json=_telemetry(unique_tag, 900.0))
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["well_tag"] == unique_tag
        assert body["is_loading"] is False
        assert body["severity"] in ("stable", "at_risk")
        assert body["bhfp_psia"] > 0

    def test_loaded_reading_flags_alert(self, client, scada_well,
                                        unique_tag):
        r = client.post("/api/scada/telemetry",
                        json=_telemetry(unique_tag, 50.0))
        assert r.status_code == 201
        body = r.json()
        assert body["is_loading"] is True
        assert body["severity"] in ("mild", "moderate", "severe")
        assert body["first_action"]

    def test_unknown_tag_404(self, client):
        r = client.post("/api/scada/telemetry",
                        json=_telemetry("NO-EXISTE", 900.0))
        assert r.status_code == 404

    def test_nonpositive_rate_rejected(self, client, scada_well,
                                       unique_tag):
        r = client.post("/api/scada/telemetry",
                        json=_telemetry(unique_tag, 0.0))
        assert r.status_code == 422


class TestStatus:
    def test_status_reflects_last_reading(self, client, scada_well,
                                          unique_tag):
        client.post("/api/scada/telemetry",
                    json=_telemetry(unique_tag, 50.0))
        r = client.get("/api/scada/status/{}".format(unique_tag))
        assert r.status_code == 200
        body = r.json()
        assert body["is_loading"] is True
        assert body["last_reading_ts"] is not None

    def test_status_fallback_nominal_rate(self, client, scada_well,
                                          unique_tag):
        r = client.get("/api/scada/status/{}".format(unique_tag))
        assert r.status_code == 200
        body = r.json()
        assert body["is_loading"] is False
        assert body["last_reading_ts"] is None

    def test_status_without_data_nor_nominal_409(self, client, scada_well,
                                                 unique_tag):
        r = client.patch("/api/wells/{}".format(scada_well),
                         json={"q_gas_nominal_mscfd": 0.0})
        assert r.status_code == 200
        r = client.get("/api/scada/status/{}".format(unique_tag))
        assert r.status_code == 409

    def test_purge_readings(self, client, scada_well, unique_tag):
        client.post("/api/scada/telemetry",
                    json=_telemetry(unique_tag, 900.0))
        assert client.delete(
            "/api/scada/status/{}".format(unique_tag)).status_code == 204
        # Back to the no-reading fallback path:
        r = client.get("/api/scada/status/{}".format(unique_tag))
        assert r.status_code == 200
        assert r.json()["last_reading_ts"] is None
