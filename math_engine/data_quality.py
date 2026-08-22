"""
math_engine.data_quality
------------------------
Outlier / sanity detection for well input data - the first line of
defense against Garbage In, Garbage Out. Operators frequently have bad
surface pressure/temperature sensors; running impossible inputs through
the physics engine produces confident-looking nonsense.

Every rule here encodes a PHYSICAL impossibility or a strong anomaly,
flagged BEFORE any calculation runs:

    - Wellhead pressure above shut-in pressure  -> sensor fault
    - Flowing pressures above reservoir pressure -> no drawdown, cannot flow
    - Non-positive rates/depths/diameters        -> unit or entry error
    - Gas gravity outside Sutton validity        -> correlation extrapolation
    - Temperatures outside plausible ranges      -> sensor/unit error

Usage: call validate_well_inputs() with whatever fields you have;
it returns a list of issues sorted errors-first. The app layer should
block computation on 'error' and display 'warning' items.

Units: field units (see CONTEXT.md).
"""

from math_engine.gas_properties import sutton_pseudocriticals


def _issue(severity, code, message):
    return {"severity": severity, "code": code, "message": message}


def validate_well_inputs(P_res=None, P_wf=None, P_wh=None, P_shutin_wh=None,
                         T_surface_R=None, T_bottomhole_R=None,
                         q_gas_mscfd=None, q_water_bpd=None,
                         depth_ft=None, d_in=None, gamma_g=None,
                         is_flowing=True):
    """
    Validate a set of well inputs before they reach the physics engine.
    Pass only the fields available; missing fields are skipped.

    :return: list of issue dicts {'severity': 'error'|'warning',
             'code': str, 'message': str}, errors listed first.
    """
    issues = []

    def add_error(code, message):
        issues.append(_issue("error", code, message))

    def add_warning(code, message):
        issues.append(_issue("warning", code, message))

    # ------------------------------------------------------------------
    # Pressures: positivity + physical ordering rules
    # ------------------------------------------------------------------
    pressures = {"P_res": P_res, "P_wf": P_wf, "P_wh": P_wh,
                 "P_shutin_wh": P_shutin_wh}
    for name, value in pressures.items():
        if value is not None:
            if value <= 0:
                add_error(name, "{} must be positive (got {} psia); "
                                "check units (psig vs psia?) or sensor."
                          .format(name, value))
            elif value < 14.7:
                add_warning(name, "{} below atmospheric ({:.1f} psia) - "
                                  "verify this is intended."
                            .format(name, value))

    if P_shutin_wh is not None and P_wh is not None \
            and P_wh > P_shutin_wh > 0:
        add_error(
            "wh_above_shutin",
            "Flowing wellhead pressure ({:.1f} psia) exceeds shut-in "
            "wellhead pressure ({:.1f} psia) - physically impossible. "
            "Classic bad-sensor signature; check the WHP transmitter."
            .format(P_wh, P_shutin_wh))

    if P_res is not None and P_wh is not None and P_wh > 0 \
            and P_wh >= P_res:
        add_error(
            "wh_above_reservoir",
            "Wellhead pressure ({:.1f} psia) >= average reservoir "
            "pressure ({:.1f} psia) - a well cannot produce into a "
            "surface pressure at or above reservoir pressure."
            .format(P_wh, P_res))

    if P_res is not None and P_wf is not None and q_gas_mscfd \
            and q_gas_mscfd > 0 and P_wf >= P_res > 0:
        add_error(
            "no_drawdown",
            "Flowing bottomhole pressure ({:.1f} psia) >= reservoir "
            "pressure ({:.1f} psia) while producing {:.0f} Mscf/D - "
            "no drawdown means no flow. Check gauge depth/reporting."
            .format(P_wf, P_res, q_gas_mscfd))

    if P_wf is not None and P_wh is not None and P_wh > 0 \
            and P_wf < P_wh:
        add_error(
            "wf_below_wh",
            "Bottomhole pressure ({:.1f} psia) below wellhead pressure "
            "({:.1f} psia) in a producer - the gas column must ADD "
            "pressure going down. Check transducer offsets."
            .format(P_wf, P_wh))

    # ------------------------------------------------------------------
    # Temperatures: plausibility windows (Rankine)
    # ------------------------------------------------------------------
    temps = {"T_surface_R": T_surface_R, "T_bottomhole_R": T_bottomhole_R}
    for name, value in temps.items():
        if value is not None:
            if value <= 0:
                add_error(name, "{} must be positive Rankine (got {} R); "
                                "did someone pass Fahrenheit?"
                          .format(name, value))
            elif value < 460.0 or value > 900.0:
                # ~0 F to ~440 F window - outside is implausible for wells
                add_warning(name, "{} = {:.0f} R ({:.0f} F) is outside the "
                                  "plausible wellbore range (~0-440 F)."
                            .format(name, value, value - 460.0))

    if T_surface_R is not None and T_bottomhole_R is not None \
            and T_bottomhole_R < T_surface_R:
        add_warning(
            "temperature_inversion",
            "Bottomhole temperature ({:.0f} R) below surface temperature "
            "({:.0f} R) - unusual geothermal profile; verify sensors."
            .format(T_bottomhole_R, T_surface_R))

    # ------------------------------------------------------------------
    # Rates: non-negativity + zero-flow consistency
    # ------------------------------------------------------------------
    if q_gas_mscfd is not None:
        if q_gas_mscfd < 0:
            add_error("q_gas", "Gas rate cannot be negative "
                               "({} Mscf/D).".format(q_gas_mscfd))
        elif q_gas_mscfd == 0 and is_flowing:
            add_warning("q_gas_zero",
                        "Zero gas rate on a flowing well - either the well "
                        "is dead/loading or flow metering has failed.")

    if q_water_bpd is not None and q_water_bpd < 0:
        add_error("q_water", "Water rate cannot be negative "
                             "({} bbl/D).".format(q_water_bpd))

    # ------------------------------------------------------------------
    # Geometry: depth and tubing diameter bounds
    # ------------------------------------------------------------------
    if depth_ft is not None:
        if depth_ft <= 0:
            add_error("depth", "Depth must be positive (got {} ft)."
                      .format(depth_ft))
        elif depth_ft > 30000.0:
            add_warning("depth_deep",
                        "Depth of {:,.0f} ft is extreme - confirm TVD vs MD."
                        .format(depth_ft))

    if d_in is not None:
        if d_in <= 0:
            add_error("tubing_id", "Tubing ID must be positive "
                                   "({} in).".format(d_in))
        elif d_in < 0.75 or d_in > 7.0:
            add_warning("tubing_id_unusual",
                        "Tubing ID of {:.3f} in is outside common tubing "
                        "sizes (0.75-7 in) - check OD vs ID confusion."
                        .format(d_in))

    # ------------------------------------------------------------------
    # Fluid: gas gravity within Sutton correlation validity (0.57 - 1.68)
    # ------------------------------------------------------------------
    if gamma_g is not None:
        if gamma_g <= 0:
            add_error("gamma_g", "Gas specific gravity must be positive.")
        elif gamma_g < 0.57 or gamma_g > 1.68:
            add_warning("gamma_out_of_range",
                        "Gas gravity {:.2f} is outside Sutton's correlation "
                        "validity (0.57-1.68); pseudo-criticals and Z will "
                        "be extrapolated.".format(gamma_g))

    # ------------------------------------------------------------------
    # DAK EOS applicability (reduced-property windows)
    # ------------------------------------------------------------------
    if gamma_g is not None and gamma_g > 0:
        try:
            Ppc, Tpc = sutton_pseudocriticals(gamma_g)
        except Exception:
            Ppc = Tpc = None

        if Ppc and Tpc and T_bottomhole_R and T_bottomhole_R > 0:
            Tpr = T_bottomhole_R / Tpc
            if Tpr <= 1.0:
                add_error(
                    "dak_two_phase",
                    "Reduced temperature Tpr={:.2f} <= 1.0 at bottomhole "
                    "conditions - reservoir is at/below pseudo-critical "
                    "temperature (two-phase region). DAK single-phase gas "
                    "assumption invalid.".format(Tpr))
            elif Tpr > 3.0:
                add_warning("dak_tpr_high",
                            "Reduced temperature Tpr={:.2f} exceeds DAK fit "
                            "range (>3.0); Z-factor extrapolated."
                            .format(Tpr))

        if Ppc and P_res and P_res > 0 and (P_res / Ppc) > 30.0:
            add_warning("dak_ppr_high",
                        "Reduced pressure Ppr={:.1f} exceeds DAK fit range "
                        "(>30).".format(P_res / Ppc))

    # Errors first, warnings second (stable order within each group)
    severity_rank = {"error": 0, "warning": 1}
    issues.sort(key=lambda i: severity_rank[i["severity"]])
    return issues


def has_blocking_errors(issues):
    """True if any issue has severity 'error' (should block computation)."""
    return any(i["severity"] == "error" for i in issues)


def summarize_issues(issues):
    """Human-readable summary lines for UI display."""
    return ["[{}] {}: {}".format(i["severity"].upper(), i["code"],
                                 i["message"]) for i in issues]
