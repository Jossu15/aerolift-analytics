"""Portfolio endpoints (Fase 3): intervention ranking, budget simulator,
summary and (later) PDF export. Every path requires the pro tier."""

from typing import List, Optional

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from api import crud, engines, models, schemas
from api.auth import get_current_key, require_tier
from api.database import get_db
from math_engine import budget as budget_engine
from math_engine import portfolio as portfolio_engine

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

DEFAULT_GAS_PRICE = 3.5
DEFAULT_MAX_STEPS = 180


def _well_params(db: Session, well: models.Well) -> dict:
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


def _portfolio_reports(db: Session, key: models.ApiKey,
                       gas_price_usd_mcf: float,
                       max_steps: int) -> list:
    """Rank the key's whole well portfolio via math_engine.portfolio."""
    wells = crud.list_wells(db, owner_key_id=key.id)
    rows = []
    for w in wells:
        q = float(w.q_gas_nominal_mscfd or 0.0)
        alert = None
        if q > 0:
            try:
                alert = engines.portfolio_alert(w, db=db)
            except Exception:
                alert = None
        params = _well_params(db, w)
        gp_list, p_list, _ = engines.preview_decline_history(db, w)
        rows.append({
            "well_id": w.id,
            "tag": w.tag,
            "params": params,
            "gp_list": gp_list,
            "p_list": p_list,
            "q_nominal_mscfd": q,
            "at_risk": bool(alert is not None and alert["severity"] != "green"),
        })
    return portfolio_engine.rank_portfolio(
        rows, gas_price_usd_mcf=gas_price_usd_mcf,
        max_steps=max_steps, time_step_days=30.0)


def _rank_row_schema(report: dict) -> dict:
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


def _budget_result(reports: list, budget_usd: float,
                   one_per_well: bool) -> dict:
    offers = [r["best_option"] for r in reports
              if r["best_option"] is not None]
    return budget_engine.optimize_budget(
        offers, budget_usd, one_per_well=one_per_well)


def _budget_schema(result: dict) -> dict:
    chosen = []
    for o in result["chosen"]:
        chosen.append({
            "well_id": o.get("well_id"),
            "tag": o.get("tag"),
            "intervention": o["intervention"],
            "label": o.get("label"),
            "cost_usd": o["cost_usd"],
            "npv_usd": o["npv_usd"],
            "roi_pct": o.get("roi_pct"),
            "payback_months": o.get("payback_months"),
            "incremental_gas_mmscf": o.get("incremental_gas_mmscf", 0.0),
            "life_extension_days": o.get("life_extension_days"),
        })
    return {
        "chosen": chosen,
        "total_cost_usd": result["total_cost_usd"],
        "total_npv_usd": result["total_npv_usd"],
        "budget_usd": result["budget_usd"],
        "utilization_pct": result["utilization_pct"],
        "wells_selected": result["wells_selected"],
        "total_incremental_gas_mmscf": result[
            "total_incremental_gas_mmscf"],
    }


@router.get("/ranking", response_model=List[schemas.PortfolioRankRow])
def ranking(gas_price_usd_mcf: float = DEFAULT_GAS_PRICE,
            max_steps: int = DEFAULT_MAX_STEPS,
            key: models.ApiKey = Depends(require_tier("pro")),
            db: Session = Depends(get_db)):
    """Best intervention option per well, sorted by NPV (best first)."""
    reports = _portfolio_reports(db, key, gas_price_usd_mcf, max_steps)
    return [_rank_row_schema(r) for r in reports]


@router.post("/budget", response_model=schemas.BudgetOut)
def budget_plan(payload: schemas.BudgetIn,
                key: models.ApiKey = Depends(require_tier("pro")),
                db: Session = Depends(get_db)):
    """Knapsack: pick the NPV-maximizing intervention set under capex."""
    reports = _portfolio_reports(db, key,
                                 payload.gas_price_usd_mcf,
                                 payload.max_steps)
    result = _budget_result(reports, payload.budget_usd,
                            payload.one_per_well)
    return schemas.BudgetOut(**_budget_schema(result))


@router.get("/summary", response_model=schemas.PortfolioSummaryOut)
def summary(budget_usd: Optional[float] = None,
            gas_price_usd_mcf: float = DEFAULT_GAS_PRICE,
            max_steps: int = DEFAULT_MAX_STEPS,
            key: models.ApiKey = Depends(require_tier("pro")),
            db: Session = Depends(get_db)):
    """Field-level KPIs + (opt.) the optimized package for a budget."""
    reports = _portfolio_reports(db, key, gas_price_usd_mcf, max_steps)
    summ = portfolio_engine.portfolio_summary(reports)
    body = dict(summ)
    if budget_usd and budget_usd > 0:
        result = _budget_result(reports, float(budget_usd), True)
        body["budget"] = _budget_schema(result)
    return schemas.PortfolioSummaryOut(**body)