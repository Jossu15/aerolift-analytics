"""
math_engine.portfolio
---------------------
Field-level intervention ranking (Fase 3 - Portfolio Optimizer).

Runs the physics-honest intervention economics of `economics.py` for a
whole portfolio of wells, picks each well's best option and aggregates
field-level KPIs:

    well  -> one evaluated option per candidate intervention
    rank  -> wells sorted by their best option's NPV (best first)
    summary -> Mscf/D at risk, $ recoverable, total NPV/cost, recovery

Everything here is pure math on plain dicts so it can be tested without
a database; the API layer feeds it well params + p/z history per well.

Units: field units (CONTEXT.md). Money in USD.
"""

from concurrent.futures import ThreadPoolExecutor
import math

from math_engine import economics
from math_engine.recommendations import _STANDARD_TUBING_IDS

# Candidate interventions, best-fitting first (recommendations ladder)
INTERVENTIONS = ("velocity_string", "compression")

DEFAULT_GAS_PRICE_USD_MCF = 3.5


def _default_targets(params: dict) -> dict:
    """Sane intervention targets from the well's current completion.

    velocity_string -> largest standard tubing smaller than the current
    ID (max velocity gain per dollar); compression -> halve the wellhead
    pressure (comfortably below today's p_wh).
    """
    d = float(params["tubing_id_in"])
    candidates = [cid for cid in _STANDARD_TUBING_IDS if cid < d]
    return {
        "target_tubing_id_in":
            max(candidates) if candidates else max(d * 0.8, 0.75),
        "target_p_wh_psia": max(float(params["p_wh"]) * 0.5, 50.0),
    }


def well_intervention_options(params: dict, gp_list, p_list,
                              well_id=None, tag=None,
                              gas_price_usd_mcf=DEFAULT_GAS_PRICE_USD_MCF,
                              costs_usd=None, targets=None,
                              time_step_days=30.0, max_steps=240) -> list:
    """Evaluate every candidate intervention for one well.

    :param params: the evaluate_intervention params dict (same keys the
        /analysis/economics endpoint sends).
    :param gp_list, p_list: p/z production history (MMscf cumulative,
        psia) used as the do-nothing baseline forecast seed.
    :param costs_usd: optional {intervention: cost} overrides; missing
        keys fall back to the economics.CATALOG default.
    :param targets: optional {target_tubing_id_in, target_p_wh_psia}
        overrides; by default `_default_targets` is used.
    :return: list of economics.evaluate_intervention results enriched
        with well_id/tag, sorted best-NPV-first. Physics or data
        failures for an intervention are skipped, never fatal.
    """
    ts = dict(targets) if targets else _default_targets(params)
    options = []
    for intervention in INTERVENTIONS:
        requires = economics.CATALOG[intervention]["requires"]
        overrides = {k: ts[k] for k in requires if k in ts}
        try:
            res = economics.evaluate_intervention(
                params, gp_list, p_list, intervention,
                gas_price_usd_mcf=gas_price_usd_mcf,
                cost_usd=(costs_usd or {}).get(intervention),
                time_step_days=time_step_days, max_steps=max_steps,
                **overrides)
        except Exception:
            continue
        res = dict(res)
        if well_id is not None:
            res["well_id"] = well_id
        if tag is not None:
            res["tag"] = tag
        options.append(res)
    options.sort(key=lambda o: o["npv_usd"], reverse=True)
    return options


def _evaluate_well(w: dict, gas_price_usd_mcf, costs_usd, targets,
                   time_step_days, max_steps) -> dict:
    """One well's report dict (shared by the sequential and parallel
    rankers so both produce byte-for-byte identical reports)."""
    options = well_intervention_options(
        w["params"], w["gp_list"], w["p_list"],
        well_id=w.get("well_id"), tag=w.get("tag"),
        gas_price_usd_mcf=gas_price_usd_mcf, costs_usd=costs_usd,
        targets=targets, time_step_days=time_step_days,
        max_steps=max_steps)
    return {
        "well_id": w.get("well_id"),
        "tag": w.get("tag"),
        "q_nominal_mscfd": w.get("q_nominal_mscfd"),
        "at_risk": bool(w.get("at_risk", True)),
        "option_count": len(options),
        "best_option": options[0] if options else None,
        "options": options,
    }


def _sort_reports(reports: list) -> list:
    reports.sort(key=lambda r: ((r["best_option"] or {}).get("npv_usd")
                                if r["best_option"] else -math.inf),
                 reverse=True)
    return reports


def rank_portfolio(wells, gas_price_usd_mcf=DEFAULT_GAS_PRICE_USD_MCF,
                   costs_usd=None, targets=None,
                   time_step_days=30.0, max_steps=240) -> list:
    """Rank a portfolio of wells by each well's best intervention NPV.

    :param wells: list of dicts::

        {"well_id": int, "tag": str, "params": dict,
         "gp_list": [...] , "p_list": [...],
         "q_nominal_mscfd": float, "at_risk": bool}

    `q_nominal_mscfd`/`at_risk` are optional and bubble up into the
    report for the executive summary aggregation.
    :return: list of reports sorted best-NPV-first::

        {"well_id", "tag", "q_nominal_mscfd", "at_risk",
         "best_option": dict|None, "options": [...], "option_count": int}
    """
    reports = [_evaluate_well(w, gas_price_usd_mcf, costs_usd, targets,
                              time_step_days, max_steps) for w in wells]
    return _sort_reports(reports)


def rank_portfolio_parallel(wells, gas_price_usd_mcf=DEFAULT_GAS_PRICE_USD_MCF,
                            costs_usd=None, targets=None,
                            time_step_days=30.0, max_steps=240,
                            workers: int = 4) -> list:
    """rank_portfolio() with per-well economics evaluated in parallel.

    The per-well evaluation is pure math on plain dicts, so it runs safely
    on a thread pool. Reports are collected in input order before the same
    sort, so the result is identical to ``rank_portfolio`` (only faster:
    on CPython the physics loops stay GIL-bound, the win is the I/O-driven
    row build plus the numpy/C-side work that releases the GIL).
    """
    n = max(1, len(wells))
    pool = max(1, min(int(workers), n))
    with ThreadPoolExecutor(max_workers=pool,
                            thread_name_prefix="portfolio-rank") as ex:
        futures = [ex.submit(_evaluate_well, w, gas_price_usd_mcf,
                             costs_usd, targets, time_step_days,
                             max_steps) for w in wells]
        reports = [f.result() for f in futures]
    return _sort_reports(reports)


def portable_best(row: dict) -> dict:
    """Flatten one rank row for a caller that only needs the essentials."""
    best = row["best_option"]
    return {
        "well_id": row.get("well_id"),
        "tag": row.get("tag"),
        "q_nominal_mscfd": row.get("q_nominal_mscfd"),
        "at_risk": row.get("at_risk"),
        "actionable": best is not None,
        **({k: best[k] for k in (
            "intervention", "label", "cost_usd", "npv_usd", "roi_pct",
            "payback_months", "incremental_gas_mmscf",
            "life_extension_days", "intervention_death_day")}
           if best else {}),
    }


def portfolio_summary(reports: list) -> dict:
    """Field-level KPIs over the ranked portfolio.

    `at_risk` wells' nominal rate drives "gas at risk"; positive-NPV
    best options drive "recoverable" KPIs (what a budget could win).
    """
    actionable = [r for r in reports if r["best_option"] is not None]
    at_risk = [r for r in reports if r.get("at_risk")]
    pos = [r for r in actionable if r["best_option"]["npv_usd"] > 0]
    rois = [r["best_option"]["roi_pct"] for r in pos
            if r["best_option"].get("roi_pct") is not None]
    paybacks = [r["best_option"]["payback_months"] for r in pos
                if r["best_option"].get("payback_months") is not None]
    return {
        "wells_total": len(reports),
        "wells_at_risk": len(at_risk),
        "gas_at_risk_mscfd": round(
            sum(r.get("q_nominal_mscfd") or 0.0 for r in at_risk), 1),
        "wells_actionable": len(actionable),
        "gas_actionable_mscfd": round(
            sum(r.get("q_nominal_mscfd") or 0.0 for r in actionable), 1),
        "wells_positive_npv": len(pos),
        "positive_npv_usd": round(
            sum(r["best_option"]["npv_usd"] for r in pos), 2),
        "positive_cost_usd": round(
            sum(r["best_option"]["cost_usd"] for r in pos), 2),
        "positive_incremental_gas_mmscf": round(
            sum(r["best_option"]["incremental_gas_mmscf"] for r in pos), 2),
        "positive_roi_mean_pct": (
            round(sum(rois) / len(rois), 1) if rois else None),
        "positive_payback_mean_months": (
            round(sum(paybacks) / len(paybacks), 1) if paybacks else None),
    }