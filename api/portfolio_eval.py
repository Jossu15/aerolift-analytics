"""Shared portfolio evaluation logic.

Both the synchronous portfolio endpoints and the background batch runner
use these helpers so a run computed in a worker thread is byte-for-byte
the same result the sync endpoints return.

The per-well physics (deliverability, alert, economics) is pure given a
db session bound to the well, so the same code runs safely in any thread;
``portfolio_reports`` accepts any ``Session`` instance.
"""

from typing import Optional

from sqlalchemy.orm import Session

from api import crud, engines, models
from math_engine import portfolio as portfolio_engine

DEFAULT_GAS_PRICE = 3.5
DEFAULT_MAX_STEPS = 180
MAX_WELLS = 10000


def well_params(db: Session, well: models.Well) -> dict:
    """Evaluate_intervention params for a stored well (same as the
    /analysis/economics endpoint uses)."""
    return {
        "p_wh": float(well.p_wh),
        "t_wh_f": float(well.t_wh_f),
        "t_res_f": float(well.t_res_f),
        "tvd_ft": float(well.tvd_ft),
        "tubing_id_in": float(well.tubing_id_in),
        "gamma_g": float(well.gamma_g),
        "q_water_bpd": float(well.q_water_bpd or 0.0),
        "liquid_sg": float(well.liquid_sg),
        "vlp_model": well.vlp_model,
        "load_method": well.load_method,
        "friction_multiplier":
            float(getattr(well, "friction_multiplier", None) or 1.0),
        "q_gas_nominal_mscfd": float(well.q_gas_nominal_mscfd or 0.0),
        "ipr": engines.ipr_spec(db, well),
    }


def build_rows(db: Session, wells) -> list:
    """Portfolio input rows for rank_portfolio: one dict per well."""
    rows = []
    for w in wells:
        q = float(w.q_gas_nominal_mscfd or 0.0)
        alert = None
        if q > 0:
            try:
                alert = engines.portfolio_alert(w, db=db)
            except Exception:
                alert = None
        gp_list, p_list, _ = engines.preview_decline_history(db, w)
        rows.append({
            "well_id": w.id,
            "tag": w.tag,
            "params": well_params(db, w),
            "gp_list": gp_list,
            "p_list": p_list,
            "q_nominal_mscfd": q,
            "at_risk": bool(alert is not None and alert["severity"] != "green"),
        })
    return rows


def portfolio_reports(db: Session, owner_key_id: int,
                      gas_price_usd_mcf: float = DEFAULT_GAS_PRICE,
                      max_steps: int = DEFAULT_MAX_STEPS) -> list:
    """Rank the whole portfolio of an owner key."""
    wells = crud.list_wells(db, limit=MAX_WELLS, offset=0,
                            owner_key_id=owner_key_id)
    rows = build_rows(db, wells)
    return portfolio_engine.rank_portfolio(
        rows, gas_price_usd_mcf=gas_price_usd_mcf,
        max_steps=max_steps, time_step_days=30.0)


def summary_of(reports: list) -> dict:
    return portfolio_engine.portfolio_summary(reports)


def rank_row_schema(report: dict) -> Optional[dict]:
    """Portable best-option shape for API/json persistence."""
    flat = portfolio_engine.portable_best(report)
    return {
        "well_id": flat.get("well_id"),
        "tag": flat.get("tag"),
        "q_nominal_mscfd": flat.get("q_nominal_mscfd"),
        "at_risk": bool(flat.get("at_risk", True)),
        "actionable": bool(flat.get("actionable", False)),
        "intervention": flat.get("intervention"),
        "label": flat.get("label"),
        "cost_usd": flat.get("cost_usd"),
        "npv_usd": flat.get("npv_usd"),
        "roi_pct": flat.get("roi_pct"),
        "payback_months": flat.get("payback_months"),
        "incremental_gas_mmscf": flat.get("incremental_gas_mmscf"),
        "life_extension_days": flat.get("life_extension_days"),
    }


def flat_to_item(flat: dict) -> dict:
    """map a rank_row_schema() dict onto PortfolioRunItem columns."""
    return {
        "well_id": flat.get("well_id"),
        "tag": flat.get("tag") or "",
        "at_risk": bool(flat.get("at_risk", True)),
        "q_nominal_mscfd": flat.get("q_nominal_mscfd"),
        "actionable": bool(flat.get("actionable", False)),
        "intervention": flat.get("intervention"),
        "label": flat.get("label"),
        "cost_usd": flat.get("cost_usd"),
        "npv_usd": flat.get("npv_usd"),
        "roi_pct": flat.get("roi_pct"),
        "payback_months": flat.get("payback_months"),
        "incremental_gas_mmscf": flat.get("incremental_gas_mmscf"),
        "life_extension_days": flat.get("life_extension_days"),
    }