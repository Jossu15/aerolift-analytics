"""Portfolio endpoints (Fase 3): intervention ranking, budget simulator,
summary, background batch runs and PDF export. Pro tier only."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from api import models, schemas
from api import portfolio_batch, portfolio_eval
from api.auth import require_tier
from api.database import get_db
from api.portfolio_eval import DEFAULT_GAS_PRICE, DEFAULT_MAX_STEPS
from math_engine import budget as budget_engine

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _owned_runs(db: Session, key: models.ApiKey):
    return (db.query(models.PortfolioRun)
                .filter(models.PortfolioRun.owner_key_id == key.id)
                .order_by(models.PortfolioRun.id.desc()))


def _run_or_404(db: Session, key: models.ApiKey, run_id: int):
    run = _owned_runs(db, key).filter(models.PortfolioRun.id == run_id).first()
    if run is None:
        raise HTTPException(404, "run not found")
    return run


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


def _run_out(run: models.PortfolioRun) -> dict:
    return {
        "id": run.id,
        "status": run.status,
        "gas_price_usd_mcf": run.gas_price_usd_mcf,
        "max_steps": run.max_steps,
        "wells_total": run.wells_total,
        "wells_actionable": run.wells_actionable,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "error": run.error,
    }


def _run_detail(db: Session, run: models.PortfolioRun) -> dict:
    items = []
    for it in run.items:
        items.append({
            "well_id": it.well_id,
            "tag": it.tag,
            "q_nominal_mscfd": it.q_nominal_mscfd,
            "at_risk": it.at_risk,
            "actionable": it.actionable,
            "intervention": it.intervention,
            "label": it.label,
            "cost_usd": it.cost_usd,
            "npv_usd": it.npv_usd,
            "roi_pct": it.roi_pct,
            "payback_months": it.payback_months,
            "incremental_gas_mmscf": it.incremental_gas_mmscf,
            "life_extension_days": it.life_extension_days,
        })
    items.sort(key=lambda x: (x["npv_usd"] is None, -(x["npv_usd"] or -1)))
    return dict(_run_out(run), summary=run.summary_json, items=items)


# ------------------------------------------------------------------
# Sync endpoints (compute inline; small portfolios during development)
# ------------------------------------------------------------------
@router.get("/ranking", response_model=List[schemas.PortfolioRankRow])
def ranking(gas_price_usd_mcf: float = DEFAULT_GAS_PRICE,
            max_steps: int = DEFAULT_MAX_STEPS,
            key: models.ApiKey = Depends(require_tier("pro")),
            db: Session = Depends(get_db)):
    """Best intervention option per well, sorted by NPV (best first)."""
    reports = portfolio_eval.portfolio_reports(
        db, key.id, gas_price_usd_mcf, max_steps)
    return [portfolio_eval.rank_row_schema(r) for r in reports]


@router.post("/budget", response_model=schemas.BudgetOut)
def budget_plan(payload: schemas.BudgetIn,
                key: models.ApiKey = Depends(require_tier("pro")),
                db: Session = Depends(get_db)):
    """Knapsack: pick the NPV-maximizing intervention set under capex."""
    reports = portfolio_eval.portfolio_reports(
        db, key.id, payload.gas_price_usd_mcf, payload.max_steps)
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
    reports = portfolio_eval.portfolio_reports(
        db, key.id, gas_price_usd_mcf, max_steps)
    summ = portfolio_eval.summary_of(reports)
    body = dict(summ)
    if budget_usd and budget_usd > 0:
        result = _budget_result(reports, float(budget_usd), True)
        body["budget"] = _budget_schema(result)
    return schemas.PortfolioSummaryOut(**body)


# ------------------------------------------------------------------
# Background batch runs (async; the dashboard polls status)
# ------------------------------------------------------------------
@router.post("/runs", response_model=schemas.PortfolioRunOut, status_code=202)
def start_run(payload: schemas.PortfolioRunIn,
              key: models.ApiKey = Depends(require_tier("pro")),
              db: Session = Depends(get_db)):
    """Queue a field-wide evaluation; returns immediately with the run id."""
    run_id = portfolio_batch.submit_portfolio_run(
        key.id, payload.gas_price_usd_mcf, payload.max_steps)
    run = _run_or_404(db, key, run_id)
    return _run_out(run)


@router.get("/runs", response_model=List[schemas.PortfolioRunOut])
def list_runs(limit: int = 20,
              key: models.ApiKey = Depends(require_tier("pro")),
              db: Session = Depends(get_db)):
    """Recent runs of this key, newest first."""
    items = _owned_runs(db, key).limit(min(limit, 100)).all()
    return [_run_out(r) for r in items]


@router.get("/runs/{run_id}", response_model=schemas.PortfolioRunDetailOut)
def get_run(run_id: int,
            key: models.ApiKey = Depends(require_tier("pro")),
            db: Session = Depends(get_db)):
    """Full run: status, field summary and per-well ranking items."""
    run = _run_or_404(db, key, run_id)
    return _run_detail(db, run)


# ------------------------------------------------------------------
# Reporting
# ------------------------------------------------------------------
@router.get("/report.pdf")
def report_pdf(budget_usd: Optional[float] = None,
               gas_price_usd_mcf: float = DEFAULT_GAS_PRICE,
               max_steps: int = DEFAULT_MAX_STEPS,
               key: models.ApiKey = Depends(require_tier("pro")),
               db: Session = Depends(get_db)):
    """One-page executive PDF: field KPIs + ranking + optimized package."""
    import datetime

    from math_engine.reporting import (build_report,
                                       portfolio_report_sections)
    reports = portfolio_eval.portfolio_reports(
        db, key.id, gas_price_usd_mcf, max_steps)
    summ = portfolio_eval.summary_of(reports)
    budget = None
    if budget_usd and budget_usd > 0:
        budget = _budget_result(reports, float(budget_usd), True)
    sections = portfolio_report_sections(summ, reports, budget)
    pdf_bytes = build_report(
        "AeroLift Analytics - Reporte de portafolio",
        "Operador {} | generado {}".format(
            key.label, datetime.date.today().isoformat()),
        sections,
        footer_note="{} pozos | {} en riesgo".format(
            summ["wells_total"], summ["wells_at_risk"]))
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition":
                 'inline; filename="aerolift_portfolio.pdf"'})