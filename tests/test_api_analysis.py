"""API tests: physics analysis endpoints over stored wells."""

MB_PAIRS = {"gp_mmscf": [0.0, 800.0, 1800.0, 2600.0],
            "p_psia": [4200.0, 3400.0, 2700.0, 2200.0]}


class TestLoadingEndpoint:
    def test_stable_at_nominal_rate(self, client, tested_well_id):
        r = client.get("/api/wells/{}/analysis/loading".format(
            tested_well_id))
        assert r.status_code == 200
        body = r.json()
        assert body["is_loading"] is False
        assert body["severity"] in ("stable", "at_risk")
        assert body["v_actual_ft_s"] > body["v_crit_ft_s"]
        assert body["bhfp_psia"] > 0

    def test_loaded_at_low_rate_override(self, client, tested_well_id):
        r = client.get("/api/wells/{}/analysis/loading".format(
            tested_well_id), params={"q_gas_mscfd": 60.0})
        assert r.status_code == 200
        body = r.json()
        assert body["is_loading"] is True
        assert body["severity"] in ("mild", "moderate", "severe")
        assert body["first_action"]

    def test_zero_rate_without_nominal_422(self, client, well_id):
        client.patch("/api/wells/{}".format(well_id),
                     json={"q_gas_nominal_mscfd": 0.0})
        r = client.get("/api/wells/{}/analysis/loading".format(well_id))
        assert r.status_code == 422

    def test_unknown_well_404(self, client):
        assert client.get("/api/wells/999999/analysis/loading") \
            .status_code == 404


class TestNodalEndpoint:
    def test_two_intersections_j_curve(self, client, tested_well_id):
        """Demo well + BB water reproduces the loading J-curve signature."""
        r = client.get("/api/wells/{}/analysis/nodal".format(
            tested_well_id))
        assert r.status_code == 200
        body = r.json()
        assert body["flows_naturally"] is True
        assert body["ipr_source"] == "rs"
        qs = sorted(p["q_mscfd"] for p in body["all_intersections"])
        assert len(qs) == 2
        assert qs[0] < 500 < qs[1]
        # Stable (returned) point must be the high-rate one:
        assert abs(body["natural_q_mscfd"] - qs[-1]) < 1e-6
        assert body["instability_note"]

    def test_fallback_houpeurt_when_no_test(self, client, well_id):
        client.patch("/api/wells/{}".format(well_id),
                     json={"a_coef": 2100.0, "b_coef": 0.05})
        r = client.get("/api/wells/{}/analysis/nodal".format(well_id))
        assert r.status_code == 200
        body = r.json()
        assert body["ipr_source"] == "houpeurt"
        assert body["flows_naturally"] is True


class TestTraverseEndpoint:
    def test_profiles_consistent(self, client, tested_well_id):
        r = client.get("/api/wells/{}/analysis/traverse".format(
            tested_well_id))
        assert r.status_code == 200
        body = r.json()
        n = len(body["depths_ft"])
        assert n == len(body["P_dry_gas_psia"])
        assert body["depths_ft"][0] == 0.0
        assert body["P_beggs_brill_psia"] is not None
        # Same depth discretization for both correlations:
        assert len(body["P_beggs_brill_psia"]) == n
        # Wet stream adds a liquid hydrostatic head -> HIGHER required Pwf:
        assert body["bhfp_beggs_brill_psia"] > body["bhfp_dry_gas_psia"] > \
            float(body["P_dry_gas_psia"][0])
        assert body["bb_flow_patterns"]

    def test_segments_validation(self, client, tested_well_id):
        r = client.get("/api/wells/{}/analysis/traverse".format(
            tested_well_id), params={"n_segments": 2})
        assert r.status_code == 422


class TestForecastEndpoint:
    def test_forecast_happy_path(self, client, tested_well_id):
        r = client.post("/api/wells/{}/analysis/forecast".format(
            tested_well_id), json=MB_PAIRS)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ogip_mmscf"] > 0
        assert len(body["history"]) >= 2
        assert body["days_to_risk"] is None or \
            isinstance(body["days_to_risk"], int)
        first = body["history"][0]
        assert {"day", "Gp", "Pr", "q_mscfd", "status"} <= set(first)

    def test_length_mismatch_422(self, client, tested_well_id):
        bad = dict(MB_PAIRS, p_psia=[4200.0, 3400.0])
        r = client.post("/api/wells/{}/analysis/forecast".format(
            tested_well_id), json=bad)
        assert r.status_code == 422

    def test_increasing_pressure_422(self, client, tested_well_id):
        bad = dict(MB_PAIRS,
                   p_psia=[2200.0, 2700.0, 3400.0, 4200.0])
        r = client.post("/api/wells/{}/analysis/forecast".format(
            tested_well_id), json=bad)
        assert r.status_code == 422


class TestFrictionMultiplierCalibration:
    def test_patch_changes_wet_traverse(self, client, well_id):
        base = client.get("/api/wells/{}/analysis/traverse".format(
            well_id)).json()
        r = client.patch("/api/wells/{}".format(well_id),
                         json={"friction_multiplier": 3.0})
        assert r.status_code == 200, r.text
        assert r.json()["friction_multiplier"] == 3.0
        rough = client.get("/api/wells/{}/analysis/traverse".format(
            well_id)).json()
        assert (rough["bhfp_beggs_brill_psia"]
                > base["bhfp_beggs_brill_psia"])

    def test_invalid_multiplier_422(self, client, well_id):
        for bad in (0.0, -1.0, 25.0):
            r = client.patch("/api/wells/{}".format(well_id),
                             json={"friction_multiplier": bad})
            assert r.status_code == 422


class TestCalibrationEndpoint:
    CSV = ("fecha,q_gas,pwf\n"
           "2024-01-01,900,452\n"
           "2024-02-01,880,448\n"
           "2024-03-01,910,455\n"
           "2024-04-01,860,441\n")

    def test_calibration_with_measured_pwf(self, client, well_id):
        r = client.post("/api/wells/{}/history/csv".format(well_id),
                        content=self.CSV,
                        headers={"Content-Type": "text/csv"})
        assert r.status_code == 200 and r.json()["records_added"] == 4, \
            r.text
        r = client.get("/api/wells/{}/analysis/calibration".format(well_id))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["n_points"] == 4
        assert body["bias_pct"] is not None and body["mae_pct"] is not None
        assert abs(body["bias_pct"]) < 25.0  # demo well is engine-consistent
        assert body["points"][0]["pwf_predicted_psia"] > 0

    def test_calibration_without_pwf_rows(self, client, well_id):
        r = client.get("/api/wells/{}/analysis/calibration".format(well_id))
        assert r.status_code == 200
        body = r.json()
        assert body["n_points"] == 0 and body["note"]
