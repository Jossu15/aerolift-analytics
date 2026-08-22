"""Physics analyses over stored wells: loading, nodal, traverse, forecast."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api import crud, engines, models
from api.auth import get_current_key, owns_well, require_tier
from api.database import get_db

router = APIRouter(prefix="/api/wells/{well_id}/analysis", tags=["analysis"])


def _well_or_404(db: Session, well_id: int, key: models.ApiKey):
    well = crud.get_well(db, well_id)
    if well is None or not owns_well(well, key):
        raise HTTPException(404, "well {} not found".format(well_id))
    return well


class LoadingOut(BaseModel):
    is_loading: bool
    margin_pct: Optional[float] = None
    severity: str
    headline: str
    first_action: Optional[str] = None
    bhfp_psia: Optional[float] = None
    v_actual_ft_s: float
    v_crit_ft_s: float
    q_crit_mscfd: float


class Intersection(BaseModel):
    q_mscfd: float
    Pwf_psia: float


class NodalOut(BaseModel):
    ipr_source: str
    ipr_params: dict
    natural_q_mscfd: Optional[float] = None
    natural_pwf_psia: Optional[float] = None
    all_intersections: List[Intersection] = []
    instability_note: Optional[str] = None
    flows_naturally: bool


class TraverseOut(BaseModel):
    depths_ft: List[float]
    P_dry_gas_psia: List[float]
    bhfp_dry_gas_psia: float
    P_beggs_brill_psia: Optional[List[float]] = None
    bhfp_beggs_brill_psia: Optional[float] = None
    bb_flow_patterns: Optional[dict] = None


class ForecastIn(BaseModel):
    gp_mmscf: List[float] = Field(min_length=2)
    p_psia: List[float] = Field(min_length=2)
    time_step_days: int = Field(default=30, ge=1, le=365)
    max_steps: int = Field(default=36, ge=2, le=240)


class ForecastRow(BaseModel):
    day: float
    Gp: float
    Pr: float
    q_mscfd: float
    Pwf: Optional[float] = None
    status: str


class ForecastOut(BaseModel):
    ogip_mmscf: float
    pi_over_zi_psia: float
    mb_slope: float
    days_to_risk: Optional[int] = None
    history: List[ForecastRow]


class CalibrationPoint(BaseModel):
    date: str
    q_gas_mscfd: float
    pwf_measured_psia: float
    pwf_predicted_psia: Optional[float] = None
    delta_pct: Optional[float] = None


class CalibrationOut(BaseModel):
    """VLP calibration check: engine BHFP vs measured BHFP."""
    n_points: int
    bias_pct: Optional[float] = None   # mean (pred - meas)/meas * 100
    mae_pct: Optional[float] = None
    points: List[CalibrationPoint] = []
    note: Optional[str] = None


@router.get("/loading", response_model=LoadingOut)
def loading(well_id: int,
            q_gas_mscfd: Optional[float] = None,
            key: models.ApiKey = Depends(get_current_key),
            db: Session = Depends(get_db)):
    """Turner/Coleman verdict; defaults to the well's nominal rate."""
    well = _well_or_404(db, well_id, key)
    q = q_gas_mscfd if q_gas_mscfd is not None else \
        (well.q_gas_nominal_mscfd or 0.0)
    if q <= 0:
        raise HTTPException(422,
                            "no gas rate available (pass ?q_gas_mscfd=)")
    return engines.loading_snapshot(well, q)


@router.get("/nodal", response_model=NodalOut)
def nodal(well_id: int, key: models.ApiKey = Depends(require_tier("pro")),
          db: Session = Depends(get_db)):
    """IPR/VLP intersections - flags the liquid-loading J-curve signature."""
    well = _well_or_404(db, well_id, key)
    result, spec = engines.natural_flow_point(db, well)
    out = NodalOut(ipr_source=spec[0], ipr_params=spec[1],
                   flows_naturally=result is not None)
    if result:
        out.natural_q_mscfd = result["q_mscfd"]
        out.natural_pwf_psia = result["Pwf_psia"]
        out.all_intersections = [
            Intersection(q_mscfd=p["q_mscfd"], Pwf_psia=p["Pwf_psia"])
            for p in result["all_intersections"]]
        if "note" in result:
            out.instability_note = result["note"]
    return out


@router.get("/traverse", response_model=TraverseOut)
def traverse(well_id: int, q_gas_mscfd: Optional[float] = None,
             n_segments: int = 40,
             key: models.ApiKey = Depends(get_current_key),
             db: Session = Depends(get_db)):
    """Pressure vs depth profile at the given (or nominal) rate."""
    well = _well_or_404(db, well_id, key)
    if not (5 <= n_segments <= 200):
        raise HTTPException(422, "n_segments must be in [5, 200]")
    q = q_gas_mscfd if q_gas_mscfd is not None else \
        (well.q_gas_nominal_mscfd or 0.0)
    if q <= 0:
        raise HTTPException(422,
                            "no gas rate available (pass ?q_gas_mscfd=)")
    return engines.pressure_traverse(well, q, n_segments=n_segments)


@router.post("/forecast", response_model=ForecastOut)
def forecast(well_id: int, payload: ForecastIn,
             key: models.ApiKey = Depends(require_tier("pro")),
             db: Session = Depends(get_db)):
    """p/z material-balance decline + days-until-loading health score."""
    well = _well_or_404(db, well_id, key)
    if len(payload.gp_mmscf) != len(payload.p_psia):
        raise HTTPException(422,
                            "gp_mmscf and p_psia must have equal length")
    if any(p2 >= p1 for p1, p2 in zip(payload.p_psia,
                                      payload.p_psia[1:])):
        raise HTTPException(422,
                            "p_psia must be strictly decreasing")
    try:
        result = engines.forecast_from_history(
            db, well, payload.gp_mmscf, payload.p_psia,
            time_step_days=payload.time_step_days,
            max_steps=payload.max_steps)
    except ValueError as exc:
        raise HTTPException(422, "material balance fit failed: {}".format(exc))
    return ForecastOut(**result)


@router.get("/calibration", response_model=CalibrationOut)
def calibration(well_id: int,
                key: models.ApiKey = Depends(require_tier("pro")),
                db: Session = Depends(get_db)):
    """
    Compare the engine's VLP against measured BHFPs from history rows
    that carry a pwf column (CSV alias: pwf/p_wf/bhfp/presion_fondo).
    bias > 0 means the correlation over-predicts the required BHFP.
    """
    well = _well_or_404(db, well_id, key)
    recs = [r for r in crud.list_production(db, well.id) if r.pwf_psia]
    if not recs:
        return CalibrationOut(
            n_points=0,
            note="no measured Pwf rows - upload history CSV with a "
                 "pwf_psia column to calibrate")

    vlp = engines.build_vlp_func(well)
    points, deltas = [], []
    for r in recs:
        try:
            pred = vlp(float(r.q_gas_mscfd))
        except Exception:
            pred = None
        delta = ((pred - r.pwf_psia) / r.pwf_psia * 100.0
                 if pred is not None else None)
        if delta is not None:
            deltas.append(delta)
        points.append(CalibrationPoint(
            date=r.date, q_gas_mscfd=r.q_gas_mscfd,
            pwf_measured_psia=float(r.pwf_psia),
            pwf_predicted_psia=pred, delta_pct=delta))

    return CalibrationOut(
        n_points=len(points),
        bias_pct=sum(deltas) / len(deltas) if deltas else None,
        mae_pct=(sum(abs(d) for d in deltas) / len(deltas)
                 if deltas else None),
        points=points)
