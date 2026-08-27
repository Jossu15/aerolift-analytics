"""Bulk well import: JSON/CSV/Excel -> DB + analysis."""

import csv
import io
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import crud, models, schemas
from api.auth import get_current_key
from api.database import get_db
from math_engine.bulk_loader import (
    parse_file,
    bulk_analyze,
    results_to_csv,
    results_to_json,
)
from math_engine.data_quality import validate_well_inputs

router = APIRouter(prefix="/api/wells/bulk", tags=["bulk"],
                   dependencies=[Depends(get_current_key)])


class BulkWellIn(BaseModel):
    """Single well for bulk creation (JSON mode)."""
    tag: str = Field(min_length=1, max_length=64)
    name: Optional[str] = None
    p_res: float = Field(gt=0)
    t_res_f: float
    gamma_g: float = Field(gt=0.5, lt=1.6)
    p_wh: float = Field(gt=0)
    t_wh_f: float
    tvd_ft: float = Field(gt=0)
    tubing_id_in: float = Field(gt=0.5, lt=2.0)
    q_water_bpd: float = Field(default=0.0, ge=0)
    liquid_sg: float = Field(default=1.0, gt=0)
    q_gas_nominal_mscfd: float = Field(default=0.0, ge=0)
    vlp_model: str = Field(default="beggs_brill")
    load_method: str = Field(default="turner")
    friction_multiplier: float = Field(default=1.0, gt=0.0, le=10.0)
    well_type: str = Field(default="gas")
    oil_api: Optional[float] = None
    a_coef: Optional[float] = None
    b_coef: Optional[float] = None


class BulkImportResult(BaseModel):
    wells_created: int
    wells_skipped: int
    analysis: dict
    errors: List[str]


@router.post("", response_model=BulkImportResult, status_code=201)
async def bulk_import_wells(
    request: Request,
    method: str = "turner",
    key: models.ApiKey = Depends(get_current_key),
    db: Session = Depends(get_db),
):
    """
    Bulk import wells from JSON payload.

    Expects a JSON body: ``{"wells": [ {...}, ... ]}``
    or a plain list ``[ {...}, ... ]``.

    Each well must have the full WellCreate fields (tag, p_res, t_res_f,
    gamma_g, p_wh, t_wh_f, tvd_ft, tubing_id_in).  Optional fields get
    defaults.  Wells that fail GIGO validation are skipped.

    After import, every well is run through liquid-loading analysis and
    the full result (predictions vs. actuals if status was provided) is
    returned.
    """
    body = await request.json()
    if isinstance(body, dict) and "wells" in body:
        wells_raw = body["wells"]
    elif isinstance(body, list):
        wells_raw = body
    else:
        raise HTTPException(
            422, "Body must be a JSON list or {'wells': [...]}")

    if not isinstance(wells_raw, list) or len(wells_raw) == 0:
        raise HTTPException(422, "wells list is empty")

    created, skipped, errors = 0, 0, []

    for i, w in enumerate(wells_raw):
        tag = w.get("tag", "BULK-{:04d}".format(i + 1))
        try:
            well_create = schemas.WellCreate(
                tag=tag,
                name=w.get("name"),
                p_res=w["p_res"],
                t_res_f=w["t_res_f"],
                gamma_g=w["gamma_g"],
                p_wh=w["p_wh"],
                t_wh_f=w["t_wh_f"],
                tvd_ft=w["tvd_ft"],
                tubing_id_in=w["tubing_id_in"],
                q_water_bpd=w.get("q_water_bpd", 0.0),
                liquid_sg=w.get("liquid_sg", 1.0),
                q_gas_nominal_mscfd=w.get("q_gas_nominal_mscfd", 0.0),
                vlp_model=w.get("vlp_model", "beggs_brill"),
                load_method=w.get("load_method", "turner"),
                friction_multiplier=w.get("friction_multiplier", 1.0),
                well_type=w.get("well_type", "gas"),
                oil_api=w.get("oil_api"),
                a_coef=w.get("a_coef"),
                b_coef=w.get("b_coef"),
            )
        except Exception as exc:
            skipped += 1
            errors.append("well '{}': {}".format(tag, exc))
            continue

        gigo = [i for i in validate_well_inputs(
            P_res=well_create.p_res, P_wh=well_create.p_wh,
            T_surface_R=well_create.t_wh_f + 460,
            T_bottomhole_R=well_create.t_res_f + 460,
            q_gas_mscfd=well_create.q_gas_nominal_mscfd or None,
            q_water_bpd=well_create.q_water_bpd,
            depth_ft=well_create.tvd_ft,
            d_in=well_create.tubing_id_in,
            gamma_g=well_create.gamma_g)
            if i["severity"] == "error"]
        if gigo:
            skipped += 1
            errors.append("well '{}': {}".format(
                tag, "; ".join(g["message"] for g in gigo)))
            continue

        try:
            crud.create_well(db, well_create, owner_key_id=key.id)
            created += 1
        except IntegrityError:
            db.rollback()
            skipped += 1
            errors.append("well '{}': duplicate tag".format(tag))

    # Run analysis on all wells owned by this key
    wells_db = crud.list_wells(db, limit=1000, owner_key_id=key.id)
    analysis_input = []
    for w in wells_db:
        analysis_input.append({
            "tag": w.tag,
            "p_wh": w.p_wh,
            "t_wh_f": w.t_wh_f,
            "gamma_g": w.gamma_g,
            "tubing_id_in": w.tubing_id_in,
            "q_gas_mscfd": w.q_gas_nominal_mscfd,
            "q_water_bpd": w.q_water_bpd,
            "depth_ft": w.tvd_ft,
            "status": None,
        })

    analysis = bulk_analyze(analysis_input, method=method)

    return BulkImportResult(
        wells_created=created,
        wells_skipped=skipped,
        analysis=analysis,
        errors=errors,
    )


@router.post("/upload", response_model=BulkImportResult, status_code=201)
async def bulk_upload_file(
    file: UploadFile = File(...),
    method: str = "turner",
    key: models.ApiKey = Depends(get_current_key),
    db: Session = Depends(get_db),
):
    """
    Bulk import from uploaded file (JSON, CSV, or Excel).

    The file is parsed using the same flexible column mapping as the
    dashboard.  Only wells with the required API fields (tag, p_res,
    t_res_f, gamma_g, p_wh, t_wh_f, tvd_ft, tubing_id_in) are created
    in the DB; others are analyzed but not persisted.
    """
    content = await file.read()
    try:
        raw_wells = parse_file(file.filename or "upload.json", content)
    except Exception as exc:
        raise HTTPException(422, "parse error: {}".format(exc))

    # Analysis always runs (even if we can't persist)
    analysis = bulk_analyze(raw_wells, method=method)

    # Try to persist wells that have all required DB fields
    created, skipped, errors = 0, 0, []
    for w in raw_wells:
        tag = (w.get("tag") or w.get("name") or w.get("well")
               or "BULK-{:04d}".format(created + skipped + 1))
        try:
            well_create = schemas.WellCreate(
                tag=str(tag).strip()[:64],
                p_res=float(w.get("p_res") or 0),
                t_res_f=float(w.get("t_res_f") or 80),
                gamma_g=float(w.get("gamma_g") or 0.6),
                p_wh=float(w.get("p_wh") or 0),
                t_wh_f=float(w.get("t_wh_f") or 80),
                tvd_ft=float(w.get("depth_ft") or 0),
                tubing_id_in=float(w.get("tubing_id_in") or 1.995),
                q_water_bpd=float(w.get("q_water_bpd") or 0),
                q_gas_nominal_mscfd=float(w.get("q_gas_mscfd") or 0),
            )
            if (well_create.p_wh <= 0 or well_create.q_gas_nominal_mscfd <= 0
                    or well_create.tvd_ft <= 0):
                skipped += 1
                errors.append(
                    "{}: missing required fields for DB persist".format(tag))
                continue
            crud.create_well(db, well_create, owner_key_id=key.id)
            created += 1
        except IntegrityError:
            db.rollback()
            skipped += 1
            errors.append("{}: duplicate tag".format(tag))
        except Exception as exc:
            skipped += 1
            errors.append("{}: {}".format(tag, exc))

    return BulkImportResult(
        wells_created=created,
        wells_skipped=skipped,
        analysis=analysis,
        errors=errors,
    )
