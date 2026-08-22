"""Shared fixtures for API tests: TestClient + seeded demo wells."""

import uuid

import pytest
from fastapi.testclient import TestClient

from api.database import init_db
from api.main import create_app

DEMO_WELL = {
    "tag": "W-DEMO",
    "name": "Pozo demostracion",
    "p_res": 2200.0,
    "t_res_f": 170.0,
    "gamma_g": 0.65,
    "p_wh": 200.0,
    "t_wh_f": 100.0,
    "tvd_ft": 8000.0,
    "tubing_id_in": 1.995,
    "q_water_bpd": 30.0,
    "liquid_sg": 1.0,
    "q_gas_nominal_mscfd": 900.0,
    "vlp_model": "beggs_brill",
    "load_method": "turner",
}

TEST_POINTS = {
    "pwf_psia": [2100.0, 1900.0, 1600.0, 1200.0],
    "q_mscfd": [400.0, 750.0, 1150.0, 1550.0],
}


@pytest.fixture(scope="session")
def client():
    init_db()
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def well_id(client):
    """Fresh demo well per test; auto-cleanup."""
    resp = client.post("/api/wells", json=DEMO_WELL)
    assert resp.status_code == 201, resp.text
    wid = resp.json()["id"]
    yield wid
    client.delete("/api/wells/{}".format(wid))


@pytest.fixture()
def tested_well_id(client, well_id):
    """Demo well with the standard 4-point deliverability test loaded."""
    r = client.put("/api/wells/{}/deliverability-test".format(well_id),
                   json=TEST_POINTS)
    assert r.status_code == 200, r.text
    return well_id


@pytest.fixture()
def unique_tag():
    return "W-S-{}".format(uuid.uuid4().hex[:8])


@pytest.fixture()
def scada_well(client, unique_tag):
    """Dedicated well with a guaranteed-unique tag for SCADA flows."""
    r = client.post("/api/wells", json=dict(DEMO_WELL, tag=unique_tag))
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    yield wid
    client.delete("/api/wells/{}".format(wid))
