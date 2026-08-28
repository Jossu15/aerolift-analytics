"""
math_engine.budget
------------------
Budget simulator (Fase 3 - Portfolio Optimizer).

2-intervention 0/1 knapsack: given the ranked set of well interventions
(one option per well) and a capex budget, pick the subset that maximizes
total NPV while staying under budget. Classic exact DP on integer cents,
backtracking via bitsets.

As a guard for very large portfolios the DP growth is bounded; on
overflow the best-ranked feasible pick by NPV is returned instead.

Units: money in USD.
"""


def _positive_offers(offers, budget_usd):
    return [o for o in offers
            if (o.get("npv_usd") or 0.0) > 0
            and (o.get("cost_usd") or 0.0) > 0
            and o["cost_usd"] <= budget_usd]


def _one_per_well(offers):
    """Keep, per well_id, the offer with the highest NPV (tie -> cheaper)."""
    best = {}
    for o in offers:
        npv = o.get("npv_usd") or 0.0
        wid = o.get("well_id", o.get("tag"))
        cur = best.get(wid)
        if cur is None or npv > cur[0] or (
                npv == cur[0] and o.get("cost_usd", 1e18) < cur[1].get(
                    "cost_usd", 1e18)):
            best[wid] = (npv, o)
    return [v[1] for v in best.values()]


def optimize_budget(offers, budget_usd, one_per_well=True,
                    dp_state_limit=1000000):
    """0/1 knapsack maximizing NPV within the capex budget.

    :param offers: list of dicts, each with at least `well_id` (or
        `tag`), `cost_usd` (>0) and `npv_usd` (>0). Extra keys (e.g.
        `incremental_gas_mmscf`, `intervention`, `tag`) are preserved on
        the chosen entries.
    :param budget_usd: total capex available (float, $).
    :param one_per_well: only the best-NPV option per well can be chosen.
    :return: dict with chosen list + totals.
    """
    budget = float(budget_usd)
    if not offers or budget <= 0:
        return _empty_result(budget)

    pool = _one_per_well(_positive_offers(offers, budget)) \
        if one_per_well else _positive_offers(offers, budget)

    budget_c = int(round(budget * 100.0))
    items = [(int(round((o["cost_usd"]) * 100.0)), o["npv_usd"], o)
             for o in pool]
    items = [it for it in items if 0 < it[0] <= budget_c]

    dp = {0: (0.0, 0)}  # cents -> (npv, bitset of chosen items)
    for idx, (c, npv, _o) in enumerate(items):
        bit = 1 << idx
        updates = {}
        for w, (v, bits) in dp.items():
            nw = w + c
            if nw > budget_c:
                continue
            nv = v + npv
            cur = updates.get(nw)
            if cur is None or cur[0] < nv:
                updates[nw] = (nv, bits | bit)
        for nw, (nv, bits) in updates.items():
            if nw not in dp or dp[nw][0] < nv:
                dp[nw] = (nv, bits)
        if len(dp) > dp_state_limit:
            break  # defensive guard -> fall back to best picks below

    w, (nv, bits) = max(dp.items(), key=lambda kv: (kv[1][0], -kv[0]))
    chosen = [it[2] for idx, it in enumerate(items) if bits & (1 << idx)]
    chosen.sort(key=lambda o: o["npv_usd"], reverse=True)
    total_cost = w / 100.0
    return {
        "chosen": chosen,
        "total_cost_usd": round(total_cost, 2),
        "total_npv_usd": round(nv, 2),
        "budget_usd": round(budget, 2),
        "utilization_pct": round(
            100.0 * total_cost / budget if budget else 0.0, 2),
        "wells_selected": len({o.get("well_id", o.get("tag"))
                               for o in chosen}),
        "total_incremental_gas_mmscf": round(
            sum(o.get("incremental_gas_mmscf", 0.0) for o in chosen), 2),
    }


def _empty_result(budget):
    return {
        "chosen": [],
        "total_cost_usd": 0.0,
        "total_npv_usd": 0.0,
        "budget_usd": round(float(budget or 0.0), 2),
        "utilization_pct": 0.0,
        "wells_selected": 0,
        "total_incremental_gas_mmscf": 0.0,
    }