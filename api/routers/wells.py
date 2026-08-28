"""Well management: CRUD, deliverability test, CSV production history."""

import csv
import datetime as _dt
import io
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import crud, engines, models, schemas
from api.auth import get_current_key, owns_well, require_tier
from api.database import get_db
from math_engine.data_quality import validate_well_inputs
from math_engine.ipr import fit_rawlins_schellhardt

router = APIRouter(prefix="/api/wells", tags=["wells"],
                   dependencies=[Depends(get_current_key)])

# CSV header aliases -> canonical field
_CSV_ALIASES = {
    "date": ("date", "fecha", "day"),
    "q_gas_mscfd": ("q_gas_mscfd", "q_gas", "qgas", "gas_rate",
                    "tasa_gas"),
    "q_water_bpd": ("q_water_bpd", "q_water", "water_rate", "agua"),
    "p_wh_psia": ("p_wh_psia", "p_wh", "whp", "pwh",
                  "presion_superficie"),
    "pwf_psia": ("pwf_psia", "pwf", "p_wf", "bhfp", "presion_fondo"),
}


def _gigo_errors(well_like: dict):
    t_res = well_like.get("t_res_f", 0.0) + 460.0
    t_wh = well_like.get("t_wh_f", 0.0) + 460.0
    return [i for i in validate_well_inputs(
        P_res=well_like.get("p_res"), P_wh=well_like.get("p_wh"),
        T_surface_R=t_wh, T_bottomhole_R=t_res,
        q_gas_mscfd=well_like.get("q_gas_nominal_mscfd") or None,
        q_water_bpd=well_like.get("q_water_bpd"),
        depth_ft=well_like.get("tvd_ft"),
        d_in=well_like.get("tubing_id_in"),
        gamma_g=well_like.get("gamma_g"))
        if i["severity"] == "error"]


def _get_well_or_404(db: Session, well_id: int,
                     key: models.ApiKey):
    """Fetch the well and enforce ownership (404 avoids leaking ids)."""
    well = crud.get_well(db, well_id)
    if well is None or not owns_well(well, key):
        raise HTTPException(404, "well {} not found".format(well_id))
    return well


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------
@router.post("", response_model=schemas.WellOut, status_code=201)
def create_well(payload: schemas.WellCreate,
                key: models.ApiKey = Depends(get_current_key),
                db: Session = Depends(get_db)):
    errors = _gigo_errors(payload.model_dump())
    if errors:
        raise HTTPException(422, detail={
            "message": "physically impossible inputs (GIGO)",
            "issues": errors})
    try:
        return crud.create_well(db, payload, owner_key_id=key.id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,
                            "a well with tag '{}' already exists"
                            .format(payload.tag))


@router.get("", response_model=List[schemas.WellOut])
def list_wells(limit: int = 200, offset: int = 0,
               key: models.ApiKey = Depends(get_current_key),
               db: Session = Depends(get_db)):
    return crud.list_wells(db, limit=limit, offset=offset,
                           owner_key_id=key.id)


@router.get("/alerts", response_model=List[schemas.AlertOut])
def list_alerts(limit: int = 200, offset: int = 0,
                key: models.ApiKey = Depends(get_current_key),
                db: Session = Depends(get_db)):
    """Semaphore alerts for the operator's whole well portfolio.

    Serves the latest persisted snapshot per well (from the alert
    scheduler or a manual recompute) when any exist; otherwise falls
    back to an on-the-fly evaluation at each well's nominal rate:
        loaded        -> red
        metastable    -> orange
        at_risk       -> yellow
        stable        -> green
    Wells without a nominal rate are skipped (can't evaluate).
    """
    from api.alerts_engine import has_owned_snapshots, latest_alert_dicts

    if has_owned_snapshots(db, key):
        return [schemas.AlertOut(**d)
                for d in latest_alert_dicts(db, key, limit=limit)]

    wells = crud.list_wells(db, limit=limit, offset=offset,
                            owner_key_id=key.id)
    alerts = []
    for w in wells:
        snap = engines.portfolio_alert(w, db=db)
        if snap is not None:
            alerts.append(schemas.AlertOut(**snap))
    return alerts


@router.post("/alerts/recompute", response_model=List[schemas.AlertOut])
def recompute_alerts(limit: int = 200, offset: int = 0,
                     key: models.ApiKey = Depends(require_tier("pro")),
                     db: Session = Depends(get_db)):
    """Re-evaluate the operator's wells now and persist a new snapshot.

    Returns the freshly computed semaphore rows (each carries its
    computed_at). Discovers severity escalations and notifies Slack when
    a webhook is configured - duplicated with the background scheduler
    so an operator can force a refresh on demand.
    """
    from api.alerts_engine import SEVERITY_RANK, compute_portfolio_alerts

    wells = crud.list_wells(db, limit=limit, offset=offset,
                            owner_key_id=key.id)
    rows = compute_portfolio_alerts(db, wells=wells, source="manual")
    rows.sort(key=lambda d: (SEVERITY_RANK[d["severity"]], d["well_id"]))
    return [schemas.AlertOut(**d) for d in rows]


@router.get("/{well_id}", response_model=schemas.WellOut)
def get_well(well_id: int, key: models.ApiKey = Depends(get_current_key),
             db: Session = Depends(get_db)):
    return _get_well_or_404(db, well_id, key)


@router.patch("/{well_id}", response_model=schemas.WellOut)
def update_well(well_id: int, payload: schemas.WellUpdate,
                key: models.ApiKey = Depends(get_current_key),
                db: Session = Depends(get_db)):
    well = _get_well_or_404(db, well_id, key)
    merged = {c: getattr(well, c) for c in
              ("p_res", "t_res_f", "gamma_g", "p_wh", "t_wh_f", "tvd_ft",
               "tubing_id_in", "q_water_bpd", "liquid_sg",
               "q_gas_nominal_mscfd")}
    merged.update(payload.model_dump(exclude_unset=True,
                                     exclude_none=True))
    errors = _gigo_errors(merged)
    if errors:
        raise HTTPException(422, detail={
            "message": "update would produce impossible inputs",
            "issues": errors})
    return crud.update_well(db, well, payload)


@router.delete("/{well_id}", status_code=204)
def delete_well(well_id: int, key: models.ApiKey = Depends(get_current_key),
                db: Session = Depends(get_db)):
    well = _get_well_or_404(db, well_id, key)
    crud.delete_well(db, well)


# ------------------------------------------------------------------
# Deliverability test
# ------------------------------------------------------------------
@router.put("/{well_id}/deliverability-test",
            response_model=schemas.DeliverabilityTestOut)
def put_deliverability_test(well_id: int,
                            payload: schemas.DeliverabilityTestIn,
                            key: models.ApiKey = Depends(get_current_key),
                            db: Session = Depends(get_db)):
    well = _get_well_or_404(db, well_id, key)
    if len(payload.pwf_psia) != len(payload.q_mscfd):
        raise HTTPException(422,
                            "pwf_psia and q_mscfd must have equal length")
    if not all(0 < p < well.p_res for p in payload.pwf_psia):
        raise HTTPException(
            422, "every Pwf must satisfy 0 < Pwf < P_res "
                 "({} psia)".format(well.p_res))
    points = [{"pwf_psia": float(p), "q_mscfd": float(q)}
              for p, q in zip(payload.pwf_psia, payload.q_mscfd)]
    row = crud.replace_test(db, well, points)

    fitted_C = fitted_n = None
    fit_ok = False
    try:
        fitted_C, fitted_n = fit_rawlins_schellhardt(
            float(well.p_res), payload.pwf_psia, payload.q_mscfd)
        fit_ok = 0.3 <= fitted_n <= 1.2
    except Exception:
        pass
    return schemas.DeliverabilityTestOut(
        pwf_psia=payload.pwf_psia, q_mscfd=payload.q_mscfd,
        fitted_C=fitted_C, fitted_n=fitted_n, fit_ok=fit_ok)


@router.get("/{well_id}/deliverability-test")
def get_deliverability_test(well_id: int,
                            key: models.ApiKey = Depends(get_current_key),
                            db: Session = Depends(get_db)):
    _get_well_or_404(db, well_id, key)
    row = crud.get_test(db, well_id)
    if row is None:
        raise HTTPException(404, "no deliverability test stored")
    return row.points


# ------------------------------------------------------------------
# Production history (CSV upload + listing)
# ------------------------------------------------------------------
def _map_headers(header_row):
    """Map CSV columns to canonical names; returns dict or raises."""
    mapping = {}
    for raw in header_row:
        key = raw.strip().lower().replace(" ", "_").replace("-", "_")
        for canonical, aliases in _CSV_ALIASES.items():
            if key in aliases:
                mapping[raw] = canonical
                break
    missing = {"date", "q_gas_mscfd"} - set(mapping.values())
    if missing:
        raise HTTPException(
            422, "CSV missing required column(s): {} - recognized headers: "
                 "{}".format(sorted(missing),
                             {k: v for k, v in _CSV_ALIASES.items()}))
    return mapping


def _parse_date(value: str):
    value = value.strip()
    try:
        return _dt.date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return _dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError("unrecognized date '{}'".format(value))


@router.post("/{well_id}/history/csv",
             response_model=schemas.HistoryUploadResult)
async def upload_history_csv(well_id: int, request: Request,
                             key: models.ApiKey = Depends(get_current_key),
                             db: Session = Depends(get_db)):
    """
    Upload production history as raw CSV text (Content-Type: text/csv).

    Required headers: date (+ alias) and gas rate (+ aliases); water rate
    and wellhead pressure optional. Invalid rows are skipped and reported.
    """
    _get_well_or_404(db, well_id, key)
    body = (await request.body()).decode("utf-8-sig", errors="replace")
    if not body.strip():
        raise HTTPException(422, "empty CSV body")

    reader = csv.reader(io.StringIO(body))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise HTTPException(422, "CSV needs a header row plus data rows")

    colmap = _map_headers(rows[0])

    added, skipped, errors = [], 0, []
    for line_no, raw in enumerate(rows[1:], start=2):
        rec = {}
        for header, canonical in colmap.items():
            idx = rows[0].index(header)
            rec[canonical] = raw[idx] if idx < len(raw) else ""
        try:
            date_iso = _parse_date(str(rec["date"]))
            q_gas = float(rec["q_gas_mscfd"])
            if q_gas <= 0:
                raise ValueError("q_gas must be > 0")
            row_out = {"date": date_iso, "q_gas_mscfd": q_gas}
            if rec.get("q_water_bpd"):
                row_out["q_water_bpd"] = float(rec["q_water_bpd"])
            if rec.get("p_wh_psia"):
                row_out["p_wh_psia"] = float(rec["p_wh_psia"])
            if rec.get("pwf_psia"):
                pwf = float(rec["pwf_psia"])
                if pwf <= 0:
                    raise ValueError("pwf must be > 0")
                row_out["pwf_psia"] = pwf
            added.append(row_out)
        except (ValueError, IndexError) as exc:
            skipped += 1
            if len(errors) < 20:
                errors.append("line {}: {}".format(line_no, exc))

    n = crud.add_production_records(db, well_id, added) if added else 0
    return schemas.HistoryUploadResult(records_added=n,
                                       records_skipped=skipped,
                                       errors=errors)


@router.get("/{well_id}/history",
            response_model=List[schemas.ProductionRecordOut])
def get_history(well_id: int, limit: int = 5000,
                key: models.ApiKey = Depends(get_current_key),
                db: Session = Depends(get_db)):
    _get_well_or_404(db, well_id, key)
    return crud.list_production(db, well_id, limit=limit)
