"""Per-well ML residual models (tier pro): train a Random Forest on the
residual between measured BHFP in the production history and the physics
VLP, then correct physics predictions at inference time."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api import crud, engines, models
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
    trained_at: str


class PredictIn(BaseModel):
    q_gas_mscfd: float = Field(gt=0)
    q_water_bpd: float = Field(default=0.0, ge=0)


class PredictOut(BaseModel):
    pwf_physics_psia: float
    correction_psi: float
    pwf_ml_psia: float
    n_points: int
    mae_psi: float


@router.post("/train", response_model=TrainOut)
def train(well_id: int,
          key: models.ApiKey = Depends(require_tier("pro")),
          db: Session = Depends(get_db)):
    """
    Fit the residual forest on this well's production history.
    Requires >= {} monthly rows with measured Pwf (pwf_psia column of
    the CSV history). Re-training simply overwrites the model.
    """.format(ml_residuals.MIN_TRAIN_POINTS)
    well = _well_or_404(db, well_id, key)
    rows = []
    for i, rec in enumerate(
            crud.list_production(db, well_id)):
        rows.append({"q_gas_mscfd": rec.q_gas_mscfd,
                     "q_water_bpd": rec.q_water_bpd or 0.0,
                     "pwf_psia": rec.pwf_psia,
                     "day": 30.0 * i})
    vlp_fn = engines.build_vlp_func(well)
    try:
        x_mat, y_vec = ml_residuals.build_dataset(rows, vlp_fn)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    forest, metrics = ml_residuals.train_model(x_mat, y_vec)
    path = ml_residuals.save_model(well_id, forest, metrics, len(y_vec))
    payload = ml_residuals.load_model(well_id, path=path)
    return TrainOut(n_points=len(y_vec),
                    trained_at=payload["trained_at"], **metrics)


@router.get("/status")
def status(well_id: int,
           key: models.ApiKey = Depends(get_current_key),
           db: Session = Depends(get_db)):
    """Has this well a trained residual model?"""
    _well_or_404(db, well_id, key)
    payload = ml_residuals.load_model(well_id)
    if payload is None:
        return {"trained": False}
    return {"trained": True, "n_points": payload["n_points"],
            "metrics": payload["metrics"],
            "trained_at": payload["trained_at"]}


@router.post("/predict", response_model=PredictOut)
def predict(well_id: int, body: PredictIn,
            key: models.ApiKey = Depends(require_tier("pro")),
            db: Session = Depends(get_db)):
    """Physics BHFP corrected by the learned residual (fallback-safe:
    without a trained model the caller gets 409 and should use physics)."""
    well = _well_or_404(db, well_id, key)
    payload = ml_residuals.load_model(well_id)
    if payload is None:
        raise HTTPException(409,
                            "no trained model - POST /ml/train first")
    vlp_fn = engines.build_vlp_func(well)
    phys = float(vlp_fn(body.q_gas_mscfd))
    out = ml_residuals.predict_corrected(payload, phys,
                                         body.q_gas_mscfd,
                                         body.q_water_bpd)
    return PredictOut(n_points=payload["n_points"],
                      mae_psi=payload["metrics"]["mae_psi"], **out)
