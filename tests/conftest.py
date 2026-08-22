"""Shared fixtures for API tests: authorized clients + seeded demo wells.

The default `client` fixture carries a PRO-tier API key so pre-auth test
bodies stay unchanged. `basic_client`, `extra_client` (another operator)
and `anon_client` support the auth/tier/isolation tests.
"""

from types import SimpleNamespace
import uuid

import pytest
from fastapi.testclient import TestClient

from api import models
from api.auth import generate_raw_key, hash_key
from api.database import SessionLocal, init_db
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


class _KeyClient(TestClient):
    """TestClient that injects a default X-API-Key on every request."""

    def __init__(self, *args, default_headers=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._default_headers = dict(default_headers or {})

    def request(self, method, url, **kwargs):
        headers = dict(self._default_headers)
        headers.update(kwargs.pop("headers", None) or {})
        return super().request(method, url, headers=headers, **kwargs)


def _mint(label, tier):
    """Insert an ApiKey row directly; return the raw (one-time) key."""
    raw = generate_raw_key()
    session = SessionLocal()
    try:
        session.add(models.ApiKey(key_hash=hash_key(raw), label=label,
                                  tier=tier))
        session.commit()
    finally:
        session.close()
    return raw


@pytest.fixture(scope="session")
def _clients():
    init_db()
    ns = SimpleNamespace(
        pro_raw=_mint("AeroLift Tests Pro", "pro"),
        basic_raw=_mint("AeroLift Tests Basic", "basic"),
        extra_raw=_mint("Rival Operator", "pro"),
    )
    ns.anon = TestClient(create_app())
    ns.basic = _KeyClient(create_app(),
                          default_headers={"X-API-Key": ns.basic_raw})
    ns.extra = _KeyClient(create_app(),
                          default_headers={"X-API-Key": ns.extra_raw})
    ns.pro = _KeyClient(create_app(),
                        default_headers={"X-API-Key": ns.pro_raw})
    with ns.pro:  # lifespan once; others work per-request
        yield ns


@pytest.fixture(scope="session")
def client(_clients):
    """Default authorized client (PRO tier)."""
    return _clients.pro


@pytest.fixture(scope="session")
def basic_client(_clients):
    return _clients.basic


@pytest.fixture(scope="session")
def extra_client(_clients):
    return _clients.extra


@pytest.fixture(scope="session")
def anon_client(_clients):
    return _clients.anon


@pytest.fixture()
def mint_key():
    """Mint ad-hoc keys inside a test: mint_key(label, tier) -> raw."""
    return _mint


@pytest.fixture(scope="session")
def pro_headers(_clients):
    return {"X-API-Key": _clients.pro_raw}


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
