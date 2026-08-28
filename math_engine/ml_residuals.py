"""
math_engine.ml_residuals
------------------------
Random-Forest residual correction on top of the physics VLP.

The physics engine (Beggs & Brill / dry-gas RK) predicts BHFP from
first principles; real wells drift as scale, emulsions and completion
details accumulate. We train a small RandomForest on the residual

    residual = measured_pwf - physics_pwf(q)

with features [q_gas_mscfd, q_water_bpd, day]. Inference is always

    pwf_ml = physics_pwf + model.predict(features)

so the ML layer can only correct the physics - never replace it - and
wells without enough measured history simply keep pure physics.
Models are persisted per well with joblib under AEROLIFT_ML_DIR
(default <repo>/ml_models).
"""

import datetime
import os
from typing import Dict, List, Optional

import joblib
import numpy
from sklearn.ensemble import RandomForestRegressor

MODEL_DIR = os.environ.get(
    "AEROLIFT_ML_DIR",
    os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "ml_models"))
FEATURES = ["q_gas_mscfd", "q_water_bpd", "day"]
MIN_TRAIN_POINTS = 30


def build_dataset(rows: List[Dict], physics_pwf_fn):
    """
    :param rows: dicts with q_gas_mscfd (>0), optional q_water_bpd,
                 optional pwf_psia (measured BHFP) and day index.
    :param physics_pwf_fn: callable(q_mscfd) -> physics BHFP psia.
    :returns: (X, y) feature matrix and residual targets.
    :raises ValueError: fewer than MIN_TRAIN_POINTS usable rows.
    """
    x_mat, y_vec = [], []
    for r in rows:
        q = float(r.get("q_gas_mscfd") or 0.0)
        if q <= 0:
            continue
        meas = r.get("pwf_psia")
        if meas is None:
            continue
        phys = float(physics_pwf_fn(q))
        if not numpy.isfinite(phys):
            continue
        x_mat.append([q,
                      float(r.get("q_water_bpd") or 0.0),
                      float(r.get("day") or 0.0)])
        y_vec.append(float(meas) - phys)
    if len(x_mat) < MIN_TRAIN_POINTS:
        raise ValueError(
            "need at least {} rows with measured Pwf; got {}".format(
                MIN_TRAIN_POINTS, len(x_mat)))
    return x_mat, y_vec


def train_model(x_mat: List[List[float]], y_vec: List[float],
                random_state: int = 42):
    """Fit the residual forest and return (model, metrics dict)."""
    forest = RandomForestRegressor(n_estimators=120, min_samples_leaf=2,
                                   random_state=random_state, n_jobs=-1)
    forest.fit(x_mat, y_vec)
    y_arr = numpy.asarray(y_vec, dtype=float)
    pred = forest.predict(x_mat)
    mae = float(numpy.mean(numpy.abs(pred - y_arr)))
    ss_tot = float(numpy.sum((y_arr - y_arr.mean()) ** 2))
    r2 = 1.0 - float(numpy.sum((y_arr - pred) ** 2)) / ss_tot \
        if ss_tot > 0 else 1.0
    return forest, {"mae_psi": round(mae, 3), "r2": round(r2, 4),
                    "residual_mean_psi": round(float(y_arr.mean()), 3),
                    "residual_std_psi": round(float(y_arr.std()), 3)}


def save_model(well_id: int, model, metrics: Dict, n_points: int,
               path: Optional[str] = None) -> str:
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = path or os.path.join(MODEL_DIR,
                                "well_{}.joblib".format(well_id))
    joblib.dump({
        "well_id": well_id,
        "model": model,
        "features": FEATURES,
        "n_points": n_points,
        "metrics": metrics,
        "trained_at": datetime.datetime.utcnow().isoformat() + "Z",
    }, path)
    return path


def load_model(well_id: int, path: Optional[str] = None) -> Optional[Dict]:
    path = path or os.path.join(MODEL_DIR,
                                "well_{}.joblib".format(well_id))
    if not os.path.exists(path):
        return None
    payload = joblib.load(path)
    if payload.get("well_id") != well_id:
        return None
    return payload


def predict_corrected(payload: Dict, physics_pwf: float,
                      q_gas_mscfd: float, q_water_bpd: float = 0.0,
                      day: float = 0.0) -> Dict:
    """physics + learned residual, with the correction and its ±1σ band."""
    x_row = [[float(q_gas_mscfd), float(q_water_bpd or 0.0),
              float(day or 0.0)]]
    correction = float(payload["model"].predict(x_row)[0])
    metrics = payload.get("metrics") or {}
    band_psi = float(metrics.get("residual_std_psi") or 0.0)
    return {
        "pwf_physics_psia": float(physics_pwf),
        "correction_psi": correction,
        "pwf_ml_psia": float(physics_pwf) + correction,
        "band_psi": round(band_psi, 3),
    }
