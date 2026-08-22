"""ML residual layer: engine math + REST contract."""

import pytest

from math_engine import ml_residuals


@pytest.fixture(autouse=True)
def _isolated_ml_dir(tmp_path, monkeypatch):
    """Keep tests hermetic: never read/write real ml_models/ artifacts."""
    monkeypatch.setattr(ml_residuals, "MODEL_DIR", str(tmp_path))


def _physics(q):
    return 400.0 + 0.10 * q


def _rows(n=40, offset=25.0, water_slope=0.5):
    """Synthetic field data: measured Pwf = physics + systematic residual."""
    rows = []
    for i in range(n):
        q = 300.0 + 20.0 * i
        w = 10.0 + i
        rows.append({"q_gas_mscfd": q, "q_water_bpd": w,
                     "pwf_psia": _physics(q) + offset + water_slope * w,
                     "day": 30.0 * i})
    return rows


def test_build_dataset_rejects_short_history():
    with pytest.raises(ValueError):
        ml_residuals.build_dataset(_rows(5), _physics)


def test_train_recovers_systematic_offset():
    x_mat, y_vec = ml_residuals.build_dataset(_rows(40), _physics)
    forest, metrics = ml_residuals.train_model(x_mat, y_vec)
    assert metrics["r2"] > 0.9
    payload = {"model": forest}
    # true residual at q=1000, water=35: 25 + 0.5*35 = 42.5 psi
    out = ml_residuals.predict_corrected(payload, _physics(1000.0),
                                         1000.0, q_water_bpd=35.0)
    assert abs(out["correction_psi"] - 42.5) < 4.0
    assert abs(out["pwf_ml_psia"]
               - (_physics(1000.0) + 42.5)) < 4.0


def test_save_load_roundtrip_and_well_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_residuals, "MODEL_DIR", str(tmp_path))
    x_mat, y_vec = ml_residuals.build_dataset(_rows(35), _physics)
    forest, metrics = ml_residuals.train_model(x_mat, y_vec)
    path = ml_residuals.save_model(777, forest, metrics, len(y_vec))
    payload = ml_residuals.load_model(777, path=path)
    assert payload is not None
    assert payload["well_id"] == 777 and payload["n_points"] == 35
    assert ml_residuals.load_model(999, path=path) is None


class TestMlApi:
    @staticmethod
    def _csv(n=65, offset=25.0, water_slope=0.3):
        lines = ["date,q_gas_mscfd,q_water_bpd,pwf_psia"]
        for i in range(n):
            q = 300.0 + 15.0 * i
            w = 10.0 + (i % 20)
            phys = _physics(q)
            lines.append("{}-{:02d}-01,{:.1f},{:.1f},{:.2f}".format(
                2024 + i // 12, i % 12 + 1, q, w,
                phys + offset + water_slope * w))
        return "\n".join(lines)

    def test_predict_before_train_409(self, client, tested_well_id):
        r = client.post("/api/wells/{}/ml/predict".format(tested_well_id),
                        json={"q_gas_mscfd": 900.0})
        assert r.status_code == 409

    def test_train_status_predict_happy_path(self, client,
                                             tested_well_id):
        up = client.post(
            "/api/wells/{}/history/csv".format(tested_well_id),
            content=self._csv(65).encode("utf-8"),
            headers={"Content-Type": "text/csv"})
        assert up.status_code == 200, up.text
        assert up.json()["records_added"] == 65

        tr = client.post("/api/wells/{}/ml/train".format(tested_well_id))
        assert tr.status_code == 200, tr.text
        body = tr.json()
        assert body["n_points"] >= 65
        assert body["r2"] > 0.8
        assert abs(body["residual_mean_psi"]) > 10

        st = client.get("/api/wells/{}/ml/status".format(tested_well_id))
        assert st.status_code == 200 and st.json()["trained"] is True

        pr = client.post(
            "/api/wells/{}/ml/predict".format(tested_well_id),
            json={"q_gas_mscfd": 1200.0, "q_water_bpd": 25.0})
        assert pr.status_code == 200, pr.text
        pb = pr.json()
        # ML output is always physics + a bounded learned correction
        assert pb["pwf_ml_psia"] == pytest.approx(
            pb["pwf_physics_psia"] + pb["correction_psi"], abs=0.01)
        assert abs(pb["correction_psi"]) < 500
        assert pb["n_points"] == body["n_points"]

    def test_train_without_pwf_history_409(self, client, unique_tag):
        from tests.conftest import DEMO_WELL
        payload = dict(DEMO_WELL)
        payload["tag"] = "ml-thin-" + unique_tag
        created = client.post("/api/wells",
                              json=payload).json()
        r = client.post("/api/wells/{}/ml/train".format(created["id"]))
        assert r.status_code == 409

    def test_basic_tier_blocked(self, basic_client, tested_well_id):
        r = basic_client.post(
            "/api/wells/{}/ml/train".format(tested_well_id))
        assert r.status_code == 403
