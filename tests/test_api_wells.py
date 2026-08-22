"""API tests: well CRUD, deliverability test, CSV history upload."""

from tests.conftest import DEMO_WELL, TEST_POINTS


class TestWellCrud:
    def test_create_and_get(self, client, well_id):
        r = client.get("/api/wells/{}".format(well_id))
        assert r.status_code == 200
        body = r.json()
        assert body["tag"] == "W-DEMO"
        assert body["p_res"] == 2200.0
        assert body["vlp_model"] == "beggs_brill"

    def test_list_contains_well(self, client, well_id):
        r = client.get("/api/wells")
        assert r.status_code == 200
        assert any(w["id"] == well_id for w in r.json())

    def test_duplicate_tag_conflict(self, client):
        r1 = client.post("/api/wells", json=DEMO_WELL)
        assert r1.status_code == 201
        r2 = client.post("/api/wells", json=DEMO_WELL)
        assert r2.status_code == 409
        client.delete("/api/wells/{}".format(r1.json()["id"]))

    def test_gigo_rejected(self, client):
        # Passes pydantic positivity bounds but violates physics:
        # wellhead pressure at/above reservoir pressure.
        bad = dict(DEMO_WELL, tag="W-BAD", p_res=800.0, p_wh=2000.0)
        r = client.post("/api/wells", json=bad)
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert isinstance(detail, dict)
        codes = [i["code"] for i in detail["issues"]]
        assert "wh_above_reservoir" in codes

    def test_patch_updates_fields(self, client, well_id):
        r = client.patch("/api/wells/{}".format(well_id),
                         json={"q_water_bpd": 55.0})
        assert r.status_code == 200
        assert r.json()["q_water_bpd"] == 55.0

    def test_delete_then_404(self, client, well_id):
        assert client.delete("/api/wells/{}".format(well_id)).status_code \
            == 204
        assert client.get("/api/wells/{}".format(well_id)).status_code == 404

    def test_unknown_well_404(self, client):
        assert client.get("/api/wells/999999").status_code == 404


class TestDeliverability:
    def test_put_and_fit_quality(self, client, well_id):
        r = client.put("/api/wells/{}/deliverability-test".format(well_id),
                       json=TEST_POINTS)
        assert r.status_code == 200
        body = r.json()
        assert body["fit_ok"] is True
        assert 0.3 <= body["fitted_n"] <= 1.2
        assert body["fitted_C"] > 0

    def test_get_roundtrip(self, client, tested_well_id):
        r = client.get(
            "/api/wells/{}/deliverability-test".format(tested_well_id))
        assert r.status_code == 200
        pts = r.json()
        assert len(pts) == 4
        assert {"pwf_psia", "q_mscfd"} <= set(pts[0].keys())

    def test_pwf_above_pres_rejected(self, client, well_id):
        bad = {"pwf_psia": [2500.0, 1900.0], "q_mscfd": [100.0, 800.0]}
        r = client.put("/api/wells/{}/deliverability-test".format(well_id),
                       json=bad)
        assert r.status_code == 422

    def test_length_mismatch_rejected(self, client, well_id):
        bad = {"pwf_psia": [2100.0, 1900.0], "q_mscfd": [400.0]}
        r = client.put("/api/wells/{}/deliverability-test".format(well_id),
                       json=bad)
        assert r.status_code == 422

    def test_no_test_404(self, client, well_id):
        r = client.get(
            "/api/wells/{}/deliverability-test".format(well_id))
        assert r.status_code == 404


CSV_OK = (
    "fecha,q_gas,agua,whp\n"
    "2024-01-01,1500,25,210\n"
    "2024-01-02,1450,26,205\n"
    "xx/yy/zzzz,notanumber,30,200\n"
    "2024-01-04,1350,28,198\n"
)

CSV_BAD_HEADERS = "qgas_only\n100\n"


class TestCsvHistory:
    def test_upload_with_aliases_and_bad_rows(self, client, well_id):
        r = client.post("/api/wells/{}/history/csv".format(well_id),
                        content=CSV_OK.encode("utf-8"),
                        headers={"Content-Type": "text/csv"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["records_added"] == 3
        assert body["records_skipped"] == 1
        assert len(body["errors"]) == 1
        assert body["errors"][0].startswith("line 4")

    def test_history_listing_ordered(self, client, well_id):
        client.post("/api/wells/{}/history/csv".format(well_id),
                    content=CSV_OK.encode("utf-8"),
                    headers={"Content-Type": "text/csv"})
        r = client.get("/api/wells/{}/history".format(well_id))
        assert r.status_code == 200
        rows = r.json()
        dates = [x["date"] for x in rows]
        assert dates == sorted(dates)
        assert rows[0]["q_gas_mscfd"] == 1500.0

    def test_missing_required_header_422(self, client, well_id):
        r = client.post("/api/wells/{}/history/csv".format(well_id),
                        content=CSV_BAD_HEADERS.encode("utf-8"),
                        headers={"Content-Type": "text/csv"})
        assert r.status_code == 422
        assert "date" in r.json()["detail"]

    def test_empty_body_422(self, client, well_id):
        r = client.post("/api/wells/{}/history/csv".format(well_id),
                        content=b"",
                        headers={"Content-Type": "text/csv"})
        assert r.status_code == 422
