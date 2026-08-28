"""Per-well ML residual models (tier pro): train a Random Forest on the
residual between measured BHFP in the production history and the physics
VLP, then correct physics predictions at inference time. Every retrain
is versioned (TwinModel row) so the calibration history is kept."""

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api import crud, engines, models, ml_service
from api.auth import get_current_key, owns_well, require_tier
from api.database import get_db
from math_engine import ml_residuals

router = APIRouter(prefix="/api/wells/{well_id}/ml", tags=["ml"])


def _well_or_404(db: Session, well_id: int,
                 key: models.ApiKey) -> models.Well:
    well = crud.get_well(db, well_id)
    if well is None or not owns_well(well, key):
        raise HTTPException(404, "well not found")
    return well


class TrainOut(BaseModel):
    n_points: int
    mae_psi: float
    r2: float
    residual_mean_psi: float
    residual_std_psi: Optional[float] = None
    trained_at: str
    version: int = 1
    active: bool = True
    source: str = "manual"
    features: list = []


class PredictIn(BaseModel):
    q_gas_mscfd: float = Field(gt=0)
    q_water_bpd: float = Field(default=0.0, ge=0)


class PredictOut(BaseModel):
    pwf_physics_psia: float
    correction_psi: float
    pwf_ml_psia: float
    n_points: int
    mae_psi: float
    band_psi: float = 0.0


class TwinOut(BaseModel):
    version: int
    trained_at: str
    active: bool
    source: str
    n_points: int
    mae_psi: Optional[float] = None
    r2: Optional[float] = None
    residual_mean_psi: Optional[float] = None
    residual_std_psi: Optional[float] = None


@router.post("/train", response_model=TrainOut)
def train(well_id: int,
          key: models.ApiKey = Depends(require_tier("pro")),
          db: Session = Depends(get_db)):
    """
    Fit the residual forest on this well's production history.
    Requires at least {} rows with measured Pwf (pwf_psia column of
    the CSV history). Retraining is versioned: the active TwinModel row
    points at the newest artifact while earlier versions stay as
    calibration history. Idempotent: with no new rows it returns the
    current version unchanged.
    """.format(ml_residuals.MIN_TRAIN_POINTS)
    well = _well_or_404(db, well_id, key)
    try:
        twin = ml_service.train_twin(db, well, source="manual")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return TrainOut(n_points=twin.n_points,
                    mae_psi=twin.mae_psi, r2=twin.r2,
                    residual_mean_psi=twin.residual_mean_psi,
                    residual_std_psi=twin.residual_std_psi,
                    trained_at=twin.trained_at.isoformat(),
                    version=twin.version, active=twin.active,
                    source=twin.source,
                    features=json.loads(twin.features))


@router.get("/status")
def status(well_id: int,
           key: models.ApiKey = Depends(get_current_key),
           db: Session = Depends(get_db)):
    """Has this well a trained residual model? (active twin profile)"""
    _well_or_404(db, well_id, key)
    twin = ml_service.active_twin(db, well_id)
    if twin is None:
        payload = ml_residuals.load_model(well_id)
        if payload is None:
            return {"trained": False}
        return {"trained": True, "version": None, "active": True,
                "ml_path": None, "n_points": payload["n_points"],
                "metrics": payload["metrics"],
                "trained_at": payload["trained_at"]}
    return {
        "trained": True,
        "version": twin.version,
        "active": twin.active,
        "source": twin.source,
        "ml_path": twin.ml_path,
        "features": json.loads(twin.features),
        "n_points": twin.n_points,
        "metrics": twin.metrics,
        "trained_at": twin.trained_at.isoformat(),
    }


@router.get("/twins", response_model=List[TwinOut])
def twins(well_id: int,
          key: models.ApiKey = Depends(get_current_key),
          db: Session = Depends(get_db)):
    """Full versioned calibration history for this well (digital twin)."""
    _well_or_404(db, well_id, key)
    rows = db.query(models.TwinModel).filter(
        models.TwinModel.well_id == well_id).order_by(
        models.TwinModel.version).all()
    return [TwinOut(version=r.version,
                    trained_at=r.trained_at.isoformat(),
                    active=r.active, source=r.source,
                    n_points=r.n_points, mae_psi=r.mae_psi, r2=r.r2,
                    residual_mean_psi=r.residual_mean_psi,
                    residual_std_psi=r.residual_std_psi)
            for r in rows]


@router.post("/predict", response_model=PredictOut)
def predict(well_id: int, body: PredictIn,
            key: models.ApiKey = Depends(require_tier("pro")),
            db: Session = Depends(get_db)):
    """Physics BHFP corrected by the learned residual (fallback-safe:
    without a trained model the caller gets 409 and should use physics)."""
    well = _well_or_404(db, well_id, key)
    twin, payload = ml_service.get_artifact(db, well_id)
    if payload is None:
        raise HTTPException(409,
                            "no trained model - POST /ml/train first")
    vlp_fn = engines.build_vlp_func(well)
    phys = float(vlp_fn(body.q_gas_mscfd))
    out = ml_residuals.predict_corrected(payload, phys,
                                         body.q_gas_mscfd,
                                         body.q_water_bpd)
    n_points = (twin.n_points if twin is not None
                else payload["n_points"])
    mae = (twin.mae_psi if twin is not None
           else payload["metrics"]["mae_psi"])
    return PredictOut(n_points=n_points, mae_psi=mae, **out)
