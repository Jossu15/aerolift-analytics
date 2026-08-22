"""
SCADA integration: REST endpoint for the plant historian to push
real-time telemetry. Every reading is evaluated by the physics engine
on ingestion and the verdict (loading state + severity + first action)
is returned immediately so the historian/alarm layer can act on it.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api import crud, engines, models, schemas
from api.auth import get_current_key, owns_well
from api.database import get_db
from api.models import ScadaReading

router = APIRouter(prefix="/api/scada", tags=["scada"],
                   dependencies=[Depends(get_current_key)])


def _tag_well_or_404(db: Session, tag: str, key: models.ApiKey):
    well = crud.get_well_by_tag(db, tag)
    if well is None or not owns_well(well, key):
        raise HTTPException(404,
                            "unknown well_tag '{}'".format(tag))
    return well


@router.post("/telemetry", response_model=schemas.TelemetryOut,
             status_code=201)
def push_telemetry(payload: schemas.TelemetryIn,
                   key: models.ApiKey = Depends(get_current_key),
                   db: Session = Depends(get_db)):
    """
    Ingest one real-time reading:

        {"well_tag": "W-01", "q_gas_mscfd": 850,
         "q_water_bpd": 30, "p_wh_psia": 195}

    The engine evaluates liquid loading at bottomhole conditions and
    persists the verdict alongside the raw values. The historian pushes
    with the API key that owns the wells.
    """
    well = _tag_well_or_404(db, payload.well_tag, key)

    q_water = payload.q_water_bpd \
        if payload.q_water_bpd is not None else well.q_water_bpd
    snapshot = engines.loading_snapshot(well, payload.q_gas_mscfd,
                                        q_water_bpd=q_water,
                                        p_wh=payload.p_wh_psia)

    margin = snapshot["margin_pct"] / 100.0 \
        if snapshot["margin_pct"] is not None else None
    reading = ScadaReading(
        well_id=well.id,
        ts=payload.ts.replace(tzinfo=None) if payload.ts else None,
        q_gas_mscfd=payload.q_gas_mscfd,
        q_water_bpd=payload.q_water_bpd,
        p_wh_psia=payload.p_wh_psia,
        is_loading=snapshot["is_loading"],
        margin_fraction=margin,
        severity=snapshot["severity"])
    row = crud.add_scada_reading(db, reading)

    from datetime import datetime, timezone
    ts_out = payload.ts or row.ts.replace(tzinfo=timezone.utc) or \
        datetime.now(timezone.utc)
    return schemas.TelemetryOut(
        well_tag=well.tag, ts=ts_out,
        is_loading=snapshot["is_loading"],
        margin_pct=snapshot["margin_pct"],
        severity=snapshot["severity"],
        headline=snapshot["headline"],
        first_action=snapshot["first_action"],
        bhfp_psia=snapshot["bhfp_psia"])


@router.get("/status/{tag}", response_model=schemas.ScadaStatusOut)
def status_by_tag(tag: str, key: models.ApiKey = Depends(get_current_key),
                  db: Session = Depends(get_db)):
    """Last stored telemetry + its engine verdict for a well tag."""
    well = _tag_well_or_404(db, tag, key)

    row = crud.last_scada_reading(db, well.id)
    if row is None:
        # No telemetry yet - evaluate at the nominal rate as a fallback.
        if not well.q_gas_nominal_mscfd:
            raise HTTPException(409,
                                "no readings and no nominal rate set")
        snap = engines.loading_snapshot(well, well.q_gas_nominal_mscfd)
        from datetime import datetime, timezone
        return schemas.ScadaStatusOut(
            well_tag=tag, ts=datetime.now(timezone.utc),
            is_loading=snap["is_loading"],
            margin_pct=snap["margin_pct"], severity=snap["severity"],
            headline=snap["headline"], first_action=snap["first_action"],
            bhfp_psia=snap["bhfp_psia"], last_reading_ts=None)

    margin_pct = row.margin_fraction * 100.0 \
        if row.margin_fraction is not None else None
    return schemas.ScadaStatusOut(
        well_tag=tag, ts=row.ts,
        is_loading=row.is_loading,
        margin_pct=margin_pct, severity=row.severity,
        headline="{}: {} ({})".format(
            tag, "CARGANDO" if row.is_loading else "estable",
            row.severity),
        first_action=None,
        last_reading_ts=row.ts)


@router.delete("/status/{tag}", status_code=204)
def purge_readings(tag: str, key: models.ApiKey = Depends(get_current_key),
                   db: Session = Depends(get_db)):
    """Housekeeping: drop stored telemetry for a tag."""
    well = _tag_well_or_404(db, tag, key)
    db.query(ScadaReading).filter(
        ScadaReading.well_id == well.id).delete()
    db.commit()
