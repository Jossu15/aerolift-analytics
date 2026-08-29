"""Load paper validation datasets into the well DB (Turner 1969 + Xinjiang 2023).

Normalizes tests/fixtures/{turner_106,xinjiang_2023}.json via
math_engine.bulk_loader (unit conversions + alias mapping), derives the
reservoir fields the Turner paper does not report (p_res via a gas
hydrostatic gradient, t_res_f via a geothermal gradient), creates the
wells through /api/wells/bulk (runs GIGO validation), then recomputes
and persists portfolio alert snapshots so the dashboard shows all wells.

Running again is safe: wells whose tag already exists are skipped.

Usage:
    python scripts/load_paper_wells.py

Env:
    AEROLIFT_API      base URL (default http://127.0.0.1:8000)
    AEROLIFT_API_KEY  X-API-Key header (default demo pro key)
"""

import json
import os
import sys
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from math_engine.bulk_loader import parse_file, _normalize_well  # noqa: E402

BASE_URL = os.environ.get("AEROLIFT_API", "http://127.0.0.1:8000")
API_KEY = os.environ.get(
    "AEROLIFT_API_KEY", "aero__OncyEhnA6VGlm9-q7CjiKzDOs1EkudB3cCOiAla")
FIXTURES = os.path.join(PROJECT_ROOT, "tests", "fixtures")

# Derived-reservoir gradients for datasets that lack reservoir data
GAS_PRESSURE_GRADIENT = 0.13       # psi/ft above wellhead -> p_res
GEOTHERMAL_GRADIENT = 0.015        # deg F/ft above surface temp -> t_res_f


def _request(method: str, path: str, payload=None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE_URL + path, data=data,
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
        method=method)
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        return json.loads(body.decode("utf-8")) if body else {}


def _existing_tags() -> set:
    wells = _request("GET", "/api/wells")
    return {w.get("tag") for w in wells}


def _build_turner(wells_raw, existing) -> list:
    """Turner: fetch rows lack p_res/t_res_f - derive them."""
    out = []
    for i, w in enumerate(wells_raw):
        tag = "TURNER-{:03d}".format(i + 1)
        if tag in existing:
            continue
        n = _normalize_well(w, i)
        p_wh = float(n.get("p_wh") or 0)
        t_wh = float(n.get("t_wh_f") or 60)
        depth = float(n.get("depth_ft") or 0)
        p_res = round(p_wh + GAS_PRESSURE_GRADIENT * depth, 1)
        t_res = round(t_wh + GEOTHERMAL_GRADIENT * depth, 1)
        out.append({
            "tag": tag,
            "name": "Turner-{:03d}".format(i + 1),
            "p_res": p_res,
            "t_res_f": t_res,
            "gamma_g": float(n.get("gamma_g") or 0.6),
            "p_wh": p_wh,
            "t_wh_f": t_wh,
            "tvd_ft": depth,
            "tubing_id_in": float(n.get("tubing_id_in") or 1.995),
            "q_water_bpd": float(n.get("q_water_bpd") or 0),
            "liquid_sg": float(n.get("liquid_sg") or 1.0),
            "q_gas_nominal_mscfd": float(n.get("q_gas_mscfd") or 0),
            "vlp_model": "beggs_brill",
            "load_method": "turner",
            "friction_multiplier": 1.0,
            "well_type": "gas",
        })
    return out


def _build_xinjiang(wells_raw, existing) -> list:
    out = []
    for i, w in enumerate(wells_raw):
        tag = "XJ-{:03d}".format(i + 1)
        if tag in existing:
            continue
        n = _normalize_well(w, i)
        out.append({
            "tag": tag,
            "name": "Xinjiang-{:03d}".format(i + 1),
            "p_res": float(n.get("p_res") or 0),
            "t_res_f": float(n.get("t_res_f") or 80),
            "gamma_g": float(n.get("gamma_g") or 0.65),
            "p_wh": float(n.get("p_wh") or 0),
            "t_wh_f": float(n.get("t_wh_f") or 80),
            "tvd_ft": float(n.get("depth_ft") or 0),
            "tubing_id_in": float(n.get("tubing_id_in") or 1.995),
            "q_water_bpd": float(n.get("q_water_bpd") or 0),
            "liquid_sg": float(n.get("liquid_sg") or 1.0),
            "q_gas_nominal_mscfd": float(n.get("q_gas_mscfd") or 0),
            "vlp_model": "beggs_brill",
            "load_method": "turner",
            "friction_multiplier": 1.0,
            "well_type": "gas",
        })
    return out


def _load_dataset(name: str, fixture: str, builder, existing: set) -> None:
    path = os.path.join(FIXTURES, fixture)
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    wells_raw = parse_file(fixture, json.dumps(raw).encode("utf-8"))
    wells = builder(wells_raw, existing)
    print("{}: parsed={} new_to_create={}".format(name, len(wells_raw),
                                                  len(wells)))
    if not wells:
        return
    result = _request("POST", "/api/wells/bulk", {"wells": wells})
    print("{}: wells_created={} wells_skipped={}".format(
        name, result.get("wells_created"), result.get("wells_skipped")))
    for err in result.get("errors", []):
        print("  ERROR:", err)


def main() -> int:
    existing = _existing_tags()
    print("existing wells: {}".format(len(existing)))

    _load_dataset("xinjiang", "xinjiang_2023.json", _build_xinjiang, existing)
    _load_dataset("turner", "turner_106.json", _build_turner, existing)

    recompute = _request("POST", "/api/wells/alerts/recompute")
    print("recomputed {} alert snapshots".format(len(recompute)))
    sev = {}
    for a in recompute:
        sev[a.get("severity")] = sev.get(a.get("severity"), 0) + 1
    print("severity distribution:", sev)

    total = _request("GET", "/api/wells")
    print("total wells now: {}".format(len(total)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())