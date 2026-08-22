"""
math_engine.economics
---------------------
Intervention economics for liquid-loading management.

Two physics-honest interventions are modeled by re-running the full
forecast with modified well parameters (no hand-waved uplift factors):

    velocity_string - smaller upper tubing ID (coil inserted) -> higher
                      gas velocity at the same rate, later loading death.
    compression     - lower wellhead pressure -> more drawdown, higher
                      rates at every Pr.

Economics on the incremental gas between scenarios:
    revenue  = incremental Mscf * gas price ($/Mcf)
    NPV      = monthly revenues discounted at an annual rate - cost
    ROI %    = (revenue - cost) / cost * 100
    payback  = first month where cumulative discounted net >= 0

Units: field units (CONTEXT.md). Money in USD.
"""

from typing import Dict, Optional, Tuple

from math_engine.backtest import DAYS_PER_MONTH, predict_death_day

# Default intervention costs (USD) - overridable per call.
CATALOG: Dict[str, Dict] = {
    "velocity_string": {
        "label": "Velocity string (coiled-tubing insert)",
        "default_cost_usd": 85000.0,
        "requires": ("target_tubing_id_in",),
    },
    "compression": {
        "label": "Compression (lower wellhead pressure)",
        "default_cost_usd": 120000.0,
        "requires": ("target_p_wh_psia",),
    },
}


def scenario_summary(params: Dict, gp_list, p_list,
                     time_step_days: float = DAYS_PER_MONTH,
                     max_steps: int = 240) -> Tuple[Optional[float], float]:
    """
    Run one forecast scenario.

    :return: (absolute_death_day or None, cumulative_gas_mmscf)
    """
    rel_day, hist = predict_death_day(params, gp_list, p_list,
                                      time_step_days=time_step_days,
                                      max_steps=max_steps)
    elapsed = len(gp_list) * time_step_days
    abs_day = None if rel_day is None else elapsed + rel_day
    cum_mmscf = sum(r["q_mscfd"] * time_step_days for r in hist
                    if r["status"] == "flowing") / 1000.0
    return abs_day, cum_mmscf


def _apply_intervention(params: Dict, key: str, overrides: Dict) -> Dict:
    if key == "velocity_string":
        new_id = overrides["target_tubing_id_in"]
        if new_id >= params["tubing_id_in"]:
            raise ValueError(
                "target_tubing_id_in ({}) must be smaller than the "
                "current tubing ID ({})".format(new_id,
                                                params["tubing_id_in"]))
        return dict(params, tubing_id_in=new_id)
    if key == "compression":
        return dict(params, p_wh=overrides["target_p_wh_psia"])
    raise ValueError("unknown intervention '{}'".format(key))


def project_economics(incremental_mmscf: float, life_months: float,
                      gas_price_usd_mcf: float, cost_usd: float,
                      discount_annual: float = 0.10) -> Dict:
    """
    Spread incremental production evenly over the intervention scenario's
    producing months and discount monthly.
    """
    total_revenue = incremental_mmscf * 1000.0 * gas_price_usd_mcf
    roi_pct = (total_revenue - cost_usd) / cost_usd * 100.0 \
        if cost_usd > 0 else None

    n_months = max(int(round(life_months)), 1)
    r = discount_annual / 12.0
    npv = -cost_usd
    payback_month = None
    for m in range(1, n_months + 1):
        rev = total_revenue / n_months
        npv += rev / ((1.0 + r) ** m)
        if payback_month is None and npv >= 0:
            payback_month = m
    return {
        "incremental_gas_mmscf": incremental_mmscf,
        "gross_revenue_usd": total_revenue,
        "npv_usd": npv,
        "roi_pct": roi_pct,
        "payback_months": payback_month,
        "discount_annual": discount_annual,
    }


def evaluate_intervention(params: Dict, gp_list, p_list, intervention: str,
                          gas_price_usd_mcf: float = 3.5,
                          cost_usd: Optional[float] = None,
                          time_step_days: float = DAYS_PER_MONTH,
                          max_steps: int = 240,
                          **overrides) -> Dict:
    """Full what-if: baseline vs intervention + economics of the delta."""
    entry = CATALOG.get(intervention)
    if entry is None:
        raise ValueError("unknown intervention '{}'. Available: {}".format(
            intervention, sorted(CATALOG)))
    missing = [k for k in entry["requires"] if overrides.get(k) is None]
    if missing:
        raise ValueError("intervention '{}' requires: {}"
                         .format(intervention, ", ".join(missing)))

    base_day, base_cum = scenario_summary(params, gp_list, p_list,
                                          time_step_days, max_steps)
    intv_params = _apply_intervention(params, intervention, overrides)
    intv_day, intv_cum = scenario_summary(intv_params, gp_list, p_list,
                                          time_step_days, max_steps)

    incremental = max(intv_cum - base_cum, 0.0)
    price_cost = cost_usd if cost_usd is not None \
        else entry["default_cost_usd"]
    life_months = (intv_day / time_step_days) if intv_day is not None \
        else max_steps

    econ = project_economics(incremental, life_months, gas_price_usd_mcf,
                             price_cost)

    return {
        "intervention": intervention,
        "label": entry["label"],
        "cost_usd": price_cost,
        "base_death_day": base_day,
        "intervention_death_day": intv_day,
        "life_extension_days": (None if intv_day is None or base_day is None
                                else intv_day - base_day),
        "base_cum_mmscf": base_cum,
        "intervention_cum_mmscf": intv_cum,
        **econ,
    }
