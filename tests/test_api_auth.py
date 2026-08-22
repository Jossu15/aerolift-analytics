"""Auth: 401s, tier gating, per-key ownership isolation, /api/auth/me."""

from api.auth import hash_key
from api.database import SessionLocal
from api import models

import tests.conftest as cf


# ---------------------------------------------------------------- 401s
def test_health_stays_open(anon_client):
    assert anon_client.get("/health").status_code == 200


def test_missing_key_rejected(anon_client):
    r = anon_client.get("/api/wells")
    assert r.status_code == 401
    assert "missing" in r.json()["detail"].lower()


def test_invalid_key_rejected(anon_client):
    r = anon_client.get("/api/wells", headers={"X-API-Key": "aero_bogus"})
    assert r.status_code == 401


def test_deactivated_key_rejected(mint_key, anon_client):
    raw = mint_key("Doomed Key", "pro")
    session = SessionLocal()
    try:
        row = session.query(models.ApiKey).filter(
            models.ApiKey.key_hash == hash_key(raw)).one()
        row.is_active = False
        session.commit()
        key_id = row.id
    finally:
        session.close()
    try:
        r = anon_client.get("/api/wells", headers={"X-API-Key": raw})
        assert r.status_code == 401
        assert "inactive" in r.json()["detail"]
    finally:
        session = SessionLocal()
        session.query(models.ApiKey).filter(
            models.ApiKey.id == key_id).delete()
        session.commit()
        session.close()


# ---------------------------------------------------------- tier gating
def test_basic_tier_gates_nodal_and_forecast(basic_client):
    r = basic_client.post("/api/wells", json=cf.DEMO_WELL)
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    try:
        assert basic_client.get(
            "/api/wells/{}/analysis/loading".format(wid)).status_code == 200
        assert basic_client.get(
            "/api/wells/{}/analysis/traverse".format(wid)).status_code == 200
        assert basic_client.get(
            "/api/wells/{}/analysis/nodal".format(wid)).status_code == 403
        r = basic_client.post("/api/wells/{}/analysis/forecast".format(wid),
                              json={"gp_mmscf": [0.0, 800.0],
                                    "p_psia": [4200.0, 3400.0]})
        assert r.status_code == 403
        assert "pro" in r.json()["detail"]
    finally:
        basic_client.delete("/api/wells/{}".format(wid))


def test_pro_tier_reaches_nodal(client, tested_well_id):
    r = client.get("/api/wells/{}/analysis/nodal".format(tested_well_id))
    assert r.status_code == 200


# ------------------------------------------------------------ isolation
def test_keys_see_only_their_own_wells(client, extra_client):
    r = client.post("/api/wells", json=cf.DEMO_WELL)
    assert r.status_code == 201, r.text
    pro_well = r.json()

    r = extra_client.post("/api/wells",
                          json=dict(cf.DEMO_WELL, tag="W-RIVAL"))
    assert r.status_code == 201, r.text
    rival_well = r.json()
    try:
        # listings never leak the other key's wells
        pro_ids = {w["id"] for w in client.get("/api/wells").json()}
        rival_ids = {w["id"] for w in extra_client.get("/api/wells").json()}
        assert pro_well["id"] not in rival_ids
        assert rival_well["id"] not in pro_ids

        # direct access by id is a 404 (no existence leak)
        assert extra_client.get(
            "/api/wells/{}".format(pro_well["id"])).status_code == 404
        assert extra_client.patch(
            "/api/wells/{}".format(pro_well["id"]),
            json={"name": "hijacked"}).status_code == 404
        assert extra_client.delete(
            "/api/wells/{}".format(pro_well["id"])).status_code == 404

        # analysis and scada-by-tag are equally fenced
        assert extra_client.get("/api/wells/{}/analysis/loading"
                                .format(pro_well["id"])).status_code == 404
        assert extra_client.get("/api/scada/status/{}"
                                .format(pro_well["tag"])).status_code == 404

        # telemetry push to a foreign tag is rejected too
        r = extra_client.post("/api/scada/telemetry", json={
            "well_tag": pro_well["tag"], "q_gas_mscfd": 900.0})
        assert r.status_code == 404
    finally:
        extra_client.delete("/api/wells/{}".format(rival_well["id"]))
        client.delete("/api/wells/{}".format(pro_well["id"]))


def test_tag_uniqueness_is_global_not_per_owner(client, extra_client):
    """Same tag under two keys must collide (tags are globally unique)."""
    r1 = client.post("/api/wells", json=cf.DEMO_WELL)
    assert r1.status_code == 201, r1.text
    try:
        r2 = extra_client.post("/api/wells", json=cf.DEMO_WELL)
        assert r2.status_code == 409
    finally:
        client.delete("/api/wells/{}".format(r1.json()["id"]))


# ------------------------------------------------------------------ me
def test_auth_me_reports_tier_and_label(client, pro_headers):
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "pro"
    assert body["label"] == "AeroLift Tests Pro"
    assert "key_hash" not in body and "raw" not in str(body).lower()


def test_created_wells_carry_owner(client):
    r = client.post("/api/wells", json=cf.DEMO_WELL)
    wid = r.json()["id"]
    try:
        me = client.get("/api/auth/me").json()
        assert r.json()["owner_key_id"] == me["id"]
    finally:
        client.delete("/api/wells/{}".format(wid))
