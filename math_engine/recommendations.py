"""
math_engine.recommendations
---------------------------
Recommendation engine (decision-tree logic): given the liquid-loading
state of a well, recommend mitigation actions ordered by fit and cost.

Severity model
--------------
    stable    : not loading, healthy velocity margin (>20% above critical)
    at_risk   : not loading yet, margin < 20% - intervention planning time
    mild      : loading, low water production (< ~10 bbl/D)
    moderate  : loading, moderate water (10-30 bbl/D) / intermittent slugging
    severe    : loading, high water (> ~30 bbl/D) or rate far below critical

Mitigation ladder (typical costs, 2024-era US onshore ranges):
    Capillary string + chemical foamer : ~$500/mo OPEX + small install
    Plunger lift                        : $5,000 - $8,000
    Velocity string (tubing downsizing) : $15,000 - $25,000 (workover)
    Beam pump                           : $60,000+ (last resort for gas wells)

Units: field units (see CONTEXT.md).
"""

# Water-rate thresholds (bbl/D) separating severity bands when loading
_MILD_WATER_BPD = 10.0
_SEVERE_WATER_BPD = 30.0

# Velocity-margin fraction above critical considered "healthy"
_HEALTHY_MARGIN = 0.20

# Standard smaller tubing IDs (in) commonly used as velocity strings
_STANDARD_TUBING_IDS = [2.992, 2.441, 1.995, 1.751, 1.500]


def classify_loading_severity(is_loading, margin_fraction,
                              water_rate_bpd=0.0):
    """
    Map the loading state onto a severity band.

    :param is_loading: bool - actual rate below critical rate?
    :param margin_fraction: (q_actual - q_crit)/q_crit (may be nan).
    :param water_rate_bpd: produced water rate, bbl/D.
    :return: 'stable' | 'at_risk' | 'mild' | 'moderate' | 'severe'
    """
    if not is_loading:
        if margin_fraction != margin_fraction:  # NaN guard
            return "at_risk"
        return "stable" if margin_fraction >= _HEALTHY_MARGIN else "at_risk"

    # Well IS below critical rate - severity scales with water volume
    if water_rate_bpd >= _SEVERE_WATER_BPD:
        return "severe"
    if water_rate_bpd > _MILD_WATER_BPD:
        return "moderate"
    return "mild"


def _velocity_string_target_id(d_in, q_actual_mscfd, q_crit_mscfd):
    """
    Largest tubing ID (from standard sizes) that restores v_actual >=
    v_crit at the current rate. Velocity scales as q/d^2, so keeping
    the same rate in a smaller tube raises velocity by (d_old/d_new)^2:

        d_max = d_current * sqrt(q_actual / q_crit)
    """
    if not d_in or not q_actual_mscfd or not q_crit_mscfd \
            or q_crit_mscfd <= 0:
        return None
    ratio = q_actual_mscfd / q_crit_mscfd
    if ratio >= 1.0:
        return None  # already unloaded; no downsizing needed

    d_max = d_in * ratio ** 0.5
    candidates = [cid for cid in _STANDARD_TUBING_IDS if cid <= d_max * 0.98]
    return min(candidates) if candidates else None


def recommend_interventions(is_loading, margin_fraction,
                            water_rate_bpd=0.0,
                            d_in=None,
                            q_actual_mscfd=None, q_crit_mscfd=None):
    """
    Build an ordered list of recommended actions for the well.

    :return: dict with:
        severity : str band from classify_loading_severity()
        headline : one-line status summary
        actions  : list of dicts {priority, action, why, typical_cost}
    """
    severity = classify_loading_severity(is_loading, margin_fraction,
                                         water_rate_bpd)
    actions = []

    target_id = _velocity_string_target_id(d_in, q_actual_mscfd, q_crit_mscfd)

    if severity == "stable":
        headline = ("Well is unloading liquids normally ({:.0f}% velocity "
                    "margin). No action needed - keep monitoring."
                    .format(margin_fraction * 100))
        actions.append({
            "priority": 3, "action": "Routine monitoring",
            "why": "Velocity is comfortably above Turner's critical rate.",
            "typical_cost": "$0",
        })
        actions.append({
            "priority": 2, "action": "Budget review next fiscal year",
            "why": "As reservoir pressure declines the IPR shifts down; "
                   "plan a plunger lift installation before margins vanish.",
            "typical_cost": "$5,000 - $8,000 (future)",
        })

    elif severity == "at_risk":
        headline = ("Well still lifts liquids but the margin is thin "
                    "(<20%). Time to plan deliquification, not panic.")
        actions.append({
            "priority": 1, "action": "Install plunger lift (planned)",
            "why": "Cheapest mechanical fix while the well still has "
                   "energy; installing early avoids emergency workovers.",
            "typical_cost": "$5,000 - $8,000",
        })
        actions.append({
            "priority": 2, "action": "Begin capillary foamer injection trial",
            "why": "Foamers lower surface tension and critical velocity; "
                   "a cheap stop-gap that buys months of life.",
            "typical_cost": "~$500/month chemicals + capillary install",
        })

    elif severity == "mild":
        headline = ("Mild liquid loading with low water volume - "
                    "chemical deliquification should restore flow.")
        actions.append({
            "priority": 1,
            "action": "Capillary string + chemical foamer",
            "why": "Low water volumes are ideal for foamers: they cut "
                   "surface tension so droplets lift at lower gas "
                   "velocity. Fastest/cheapest intervention.",
            "typical_cost": "~$500/month chemicals + capillary install",
        })
        actions.append({
            "priority": 2, "action": "Plunger lift",
            "why": "If foaming underperforms, plunger lift mechanically "
                   "slugs liquids out using the well's own pressure.",
            "typical_cost": "$5,000 - $8,000",
        })
        if target_id:
            actions.append({
                "priority": 3,
                "action": "Velocity string to {:.3f}\" tubing".format(target_id),
                "why": "Downsizing from {:.3f}\" restores critical "
                       "velocity at today's rate without chemicals."
                       .format(d_in or 0),
                "typical_cost": "$15,000 - $25,000 (workover)",
            })

    elif severity == "moderate":
        headline = ("Moderate/intermittent liquid loading - mechanical "
                    "lift or tubing resize recommended.")
        actions.append({
            "priority": 1, "action": "Plunger lift installation",
            "why": "Intermittent slug flow at these water rates is the "
                   "textbook plunger-lift application: uses stored casing "
                   "pressure, no external energy needed.",
            "typical_cost": "$5,000 - $8,000",
        })
        if target_id:
            actions.append({
                "priority": 1,
                "action": "Velocity string to {:.3f}\" tubing".format(target_id),
                "why": "Downsizing from {:.3f}\" increases in-situ gas "
                       "velocity above Turner's critical threshold at "
                       "today's declining rate.".format(d_in or 0),
                "typical_cost": "$15,000 - $25,000 (workover)",
            })
        actions.append({
            "priority": 2, "action": "Continuous foamer injection",
            "why": "Can bridge economics until a workover rig is available.",
            "typical_cost": "~$500/month",
        })

    else:  # severe
        headline = ("Severe liquid loading with high water production - "
                    "well will die soon without major intervention.")
        if target_id:
            actions.append({
                "priority": 1,
                "action": "Velocity string to {:.3f}\" tubing".format(target_id),
                "why": "High water rates overwhelm foamers/plungers; "
                       "downsizing to {:.3f}\" is the physics-based fix "
                       "that restores carry-out velocity permanently."
                       .format(target_id),
                "typical_cost": "$15,000 - $25,000 (workover)",
            })
        actions.append({
            "priority": 1, "action": "Beam pump (gas well deliquification)",
            "why": "When reservoir pressure is too low for plunger or "
                   "velocity-string economics, pumping the liquids "
                   "directly is the reliable last resort.",
            "typical_cost": "$60,000+ installed",
        })
        actions.append({
            "priority": 2, "action": "Compression/dehydration review",
            "why": "Lowering wellhead pressure via compression can "
                   "restore drawdown enough to re-energize natural flow.",
            "typical_cost": "Field-specific (compressor rental/buy)",
        })

    # Stable ordering by priority then keep insertion order within tier
    actions.sort(key=lambda a: a["priority"])
    return {"severity": severity, "headline": headline, "actions": actions}
