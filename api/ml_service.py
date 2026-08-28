"""Digital-twin calibration service (Fase 2.1).

Turns the naive "overwrite well_{id}.joblib" of the ML endpoint into a
versioned loop: every successful retrain inserts a `TwinModel` row and
points `active` at the newest artifact, keeping the full calibration
history as the source of truth (metrics, data size, trained_at). The
artifact itself stays in the joblib directory (`AEROLIFT_ML_DIR`).

Contract notes:
- `train_twin` raises ValueError when the well has too little measured
  history, mirroring the legacy `/ml/train` behaviour (409 upstream).
- Idempotent by default: retraining with the exact same number of usable
  points is a no-op unless `force=True` (new data -> bigger count -> new
  version automatically).
- Loading falls back to the legacy `well_{id}.joblib` artifact so
  deployments trained before the migration keep working.
"""

import json
import os

from sqlalchemy.orm import Session

from api import engines, models
from math_engine import ml_residuals


def _versioned_path(well_id: int, version: int, model_dir=None) -> str:
    d = model_dir or ml_residuals.MODEL_DIR
    return os.path.join(d, "well_{}_v{}.joblib".format(well_id, version))


def delete_artifact(path: str) -> None:
    """Best-effort removal of a versioned artifact (never fatal)."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _history_rows(db: Session, well_id: int):
    """Production rows in the exact shape ml_residuals.build_dataset wants."""
    from api import crud
    rows = []
    for i, rec in enumerate(crud.list_production(db, well_id)):
        rows.append({"q_gas_mscfd": rec.q_gas_mscfd,
                     "q_water_bpd": rec.q_water_bpd or 0.0,
                     "pwf_psia": rec.pwf_psia,
                     "day": 30.0 * i})
    return rows


def latest_twin(db: Session, well_id: int):
    """Most recent TwinModel row (regardless of the active flag), or None."""
    return db.query(models.TwinModel).filter(
        models.TwinModel.well_id == well_id).order_by(
        models.TwinModel.version.desc()).first()


def active_twin(db: Session, well_id: int):
    """The active calibration row, or None when never trained."""
    row = db.query(models.TwinModel).filter(
        models.TwinModel.well_id == well_id,
        models.TwinModel.active.is_(True)).order_by(
        models.TwinModel.version.desc()).first()
    return row or latest_twin(db, well_id)


def _is_current(latest, n_points: int, source: str) -> bool:
    """True when the latest row already covers this exact dataset."""
    if latest is None:
        return False
    return (latest.n_points == n_points
            and (latest.source == source or source == "manual"))


def train_twin(db: Session, well, source="manual", force=False):
    """Fit (or refresh) the residual forest for `well`, versioned.

    :returns: the active TwinModel row after the run.
    :raises ValueError: too few rows with measured Pwf (see
        ml_residuals.MIN_TRAIN_POINTS). Leaves the last version active.
    """
    rows = _history_rows(db, well.id)
    vlp_fn = engines.build_vlp_func(well)
    x_mat, y_vec = ml_residuals.build_dataset(rows, vlp_fn)
    n_points = len(y_vec)

    latest = latest_twin(db, well.id)
    if not force and _is_current(latest, n_points, source):
        return latest

    forest, metrics = ml_residuals.train_model(x_mat, y_vec)
    version = (latest.version if latest is not None else 0) + 1
    path = _versioned_path(well.id, version)

    os.makedirs(ml_residuals.MODEL_DIR, exist_ok=True)
    ml_residuals.save_model(well.id, forest, metrics, n_points, path=path)

    for row in db.query(models.TwinModel).filter(
            models.TwinModel.well_id == well.id).all():
        row.active = False
    twin = models.TwinModel(
        well_id=well.id,
        version=version,
        source=source,
        n_points=n_points,
        mae_psi=metrics["mae_psi"],
        r2=metrics["r2"],
        residual_mean_psi=metrics["residual_mean_psi"],
        residual_std_psi=metrics["residual_std_psi"],
        features=json.dumps(ml_residuals.FEATURES),
        ml_path=path,
        active=True,
    )
    db.add(twin)
    db.commit()
    db.refresh(twin)
    return twin


def get_artifact(db: Session, well_id: int):
    """Load the artifact backing the active twin (legacy file as fallback)."""
    twin = active_twin(db, well_id)
    if twin is not None:
        payload = ml_residuals.load_model(well_id, path=twin.ml_path)
        if payload is not None:
            return twin, payload
    payload = ml_residuals.load_model(well_id)
    return None, payload