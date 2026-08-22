"""
math_engine.artificial_lift
---------------------------
Artificial-lift screening for oil wells (Fase I):

- ``size_esp``      : simplified Gould-style ESP design - intake/discharge
                      pressures, total dynamic head, stage count, motor HP,
                      plus a free-gas-at-intake warning.
- ``rod_pump_check``: API-RP-11L-flavoured beam-pump screen - pump
                      displacement vs target rate, hydraulic horsepower,
                      and a rule-based feasibility checklist.

Physics inputs come from the same correlations as math_engine.oil_pvt
(Standing Rs/Pb/Bo, Vogel IPR) so both screens stay consistent with the
rest of the engine. Field units: STB/D, psia, ft, deg F.
"""

import math
from typing import Dict, List, Optional

from math_engine.oil_pvt import (
    standing_bo,
    standing_solution_gor,
    vogel_pwf,
)

# Typical mid-size ESP stage at 60 Hz operating near BEP
HEAD_PER_STAGE_FT = 45.0
PUMP_EFFICIENCY = 0.60
STD_MOTOR_HP = (15, 25, 30, 50, 60, 75, 100, 125, 150, 200, 250)


def _mix_properties(api_gravity: float, water_cut: float,
                    rs_scf_stb: float, gas_sg: float,
                    t_res_f: float) -> Dict[str, float]:
    """Stock-tank weighted mixture properties at reservoir conditions."""
    oil_sg = 141.5 / (api_gravity + 131.5)
    bo = standing_bo(rs_scf_stb, t_res_f, gas_sg, oil_sg)
    mass_lb_per_rb = 350.0 * ((1.0 - water_cut) * oil_sg
                              + water_cut * 1.05)
    rho_mix = mass_lb_per_rb / (bo * 5.615)          # lbm/ft3
    return {"oil_sg": oil_sg, "bo_rb_stb": bo,
            "rho_mix_lb_ft3": rho_mix,
            "grad_psi_ft": rho_mix / 144.0}


def size_esp(well_props: Dict, target_rate_stb_d: float,
             qo_max_stb_d: float, water_cut: float,
             thp_psia: float,
             pump_depth_ft: Optional[float] = None) -> Dict:
    """
    :param well_props: p_res, t_res_f, tvd_ft, api_gravity, gamma_g,
                       gor_scf_stb (producing GOR)
    :returns: dict with pip/discharge pressures, head, stages, motor HP,
              free-gas fraction and warnings.
    """
    p_res = float(well_props["p_res"])
    t_res_f = float(well_props["t_res_f"])
    api_gravity = float(well_props["api_gravity"])
    gas_sg = float(well_props["gamma_g"])
    gor = float(well_props.get("gor_scf_stb") or 0.0)
    depth = float(pump_depth_ft or well_props["tvd_ft"] * 0.9)

    if not 0.0 <= water_cut <= 1.0:
        raise ValueError("water_cut must be between 0 and 1")
    if target_rate_stb_d <= 0 or thp_psia < 0:
        raise ValueError("target rate must be positive, THP non-negative")

    # Intake pressure: Vogel pwf required at the target oil rate
    qo_target = target_rate_stb_d * (1.0 - water_cut)
    pip = vogel_pwf(qo_max_stb_d, qo_target, p_res)
    if pip is None:
        raise ValueError("target oil rate exceeds Vogel absolute open "
                         "flow ({:.0f} STB/D)".format(qo_max_stb_d))

    # Average fluid properties over the pumped column
    rs_avg = standing_solution_gor(
        max((pip + thp_psia) / 2.0, 14.7),
        t_res_f, api_gravity, gas_sg)
    mix = _mix_properties(api_gravity, water_cut, rs_avg, gas_sg,
                          t_res_f)

    discharge_psi = thp_psia + mix["grad_psi_ft"] * depth
    dp_pump = max(discharge_psi - pip, 0.0)
    tdh_ft = dp_pump * 144.0 / mix["rho_mix_lb_ft3"]
    stages = int(math.ceil(tdh_ft / HEAD_PER_STAGE_FT)) if tdh_ft > 0 else 0

    liq_at_pump = target_rate_stb_d * mix["bo_rb_stb"]
    gpm = liq_at_pump * 42.0 / 1440.0
    hp_hyd = gpm * tdh_ft * (mix["rho_mix_lb_ft3"] / 62.4) / 3960.0 \
        if tdh_ft > 0 else 0.0
    hp_motor = hp_hyd / PUMP_EFFICIENCY
    motor_pick = next((hp for hp in STD_MOTOR_HP
                       if hp >= hp_motor), None)

    # Free gas at intake (volumetric fraction at intake conditions)
    rs_intake = standing_solution_gor(max(pip, 14.7),
                                      t_res_f, api_gravity, gas_sg)
    free_gas_scf = max(gor - rs_intake, 0.0) * (1.0 - water_cut)
    z_approx = 0.85
    v_gas_ft3_day = free_gas_scf * z_approx * (t_res_f + 460.0) / \
        (520.0) * (14.7 / max(pip, 14.7))
    v_liq_ft3_day = target_rate_stb_d * mix["bo_rb_stb"] * 5.615
    gas_frac = v_gas_ft3_day / (v_gas_ft3_day + v_liq_ft3_day) \
        if (v_gas_ft3_day + v_liq_ft3_day) > 0 else 0.0

    warnings = []
    if gas_frac > 0.10:
        warnings.append(
            "gas libre en la bomba ~{:.0f}% del volumen: se recomienda "
            "gas anchor o separador".format(gas_frac * 100))
    if pip < 0.15 * p_res:
        warnings.append("PIP muy baja frente a p_res: riesgo de cavitacion")

    return {
        "intake_psi": round(pip, 1),
        "discharge_psi": round(discharge_psi, 1),
        "dp_pump_psi": round(dp_pump, 1),
        "tdh_ft": round(tdh_ft, 1),
        "stages": stages,
        "hydraulic_hp": round(hp_hyd, 2),
        "motor_hp_required": round(hp_motor, 1),
        "motor_hp_recommended": motor_pick,
        "bo_rb_stb": round(mix["bo_rb_stb"], 3),
        "grad_psi_ft": round(mix["grad_psi_ft"], 3),
        "free_gas_fraction": round(gas_frac, 3),
        "warnings": warnings,
    }


def rod_pump_check(well_props: Dict, target_rate_stb_d: float,
                   water_cut: float, pump_depth_ft: float,
                   plunger_dia_in: float, stroke_len_in: float,
                   spm: float,
                   vol_efficiency: float = 0.8) -> Dict:
    """
    Beam-pump screen (API RP 11L spirit, simplified):
    PD = 0.1166 * S * N * D^2  (S in inches, D in inches, N in SPM).

    :returns: displacement, achievable rate, hydraulic HP, checklist.
    """
    p_res = float(well_props["p_res"])
    t_res_f = float(well_props["t_res_f"])
    api_gravity = float(well_props["api_gravity"])
    gas_sg = float(well_props["gamma_g"])

    if not 0.0 <= water_cut <= 1.0:
        raise ValueError("water_cut must be between 0 and 1")
    if not 1.06 <= plunger_dia_in <= 3.75:
        raise ValueError("plunger diameter fuera de rango comercial "
                         "(1.06-3.75 in)")
    if not 4.0 <= spm <= 12.0:
        raise ValueError("velocidad recomendada 4-12 SPM")
    if not 12.0 <= stroke_len_in <= 300.0:
        raise ValueError("longitud de carrera fuera de rango (12-300 in)")
    if pump_depth_ft <= 0:
        raise ValueError("profundidad de bomba invalida")

    pd_bpd = 0.1166 * stroke_len_in * spm * plunger_dia_in ** 2
    achievable = pd_bpd * vol_efficiency

    rs_avg = standing_solution_gor(p_res, t_res_f, api_gravity, gas_sg)
    mix = _mix_properties(api_gravity, water_cut, rs_avg, gas_sg,
                          t_res_f)

    # Hydraulic HP ~ 7.36e-6 * PD[bpd] * depth[ft] * SG[mix]
    sg_eff = mix["rho_mix_lb_ft3"] / 62.4
    hp_hyd = 7.36e-6 * min(pd_bpd, max(target_rate_stb_d, 1.0)) \
        * pump_depth_ft * sg_eff

    checks: List[Dict] = []
    checks.append({
        "check": "Desplazamiento vs tasa objetivo",
        "ok": achievable >= target_rate_stb_d,
        "note": "PD={:.0f} bpd x eff {:.0%} -> {:.0f} bpd disponibles "
                "para {:.0f} bpd objetivo".format(
                    pd_bpd, vol_efficiency, achievable,
                    target_rate_stb_d)})
    checks.append({
        "check": "Profundidad de bomba",
        "ok": pump_depth_ft <= 9000,
        "note": "{:.0f} ft {}del limite practico 9000 ft".format(
            pump_depth_ft,
            "dentro " if pump_depth_ft <= 9000 else "EXCEDE ")})
    gor = float(well_props.get("gor_scf_stb") or 0.0)
    checks.append({
        "check": "Interferencia de gas",
        "ok": gor <= 800,
        "note": "GLR {:.0f} scf/STB {}".format(
            gor,
            "- considerar gas anchor" if gor > 500 else "- OK")})
    checks.append({
        "check": "Cut de agua alto",
        "ok": water_cut < 0.85,
        "note": "agua {:.0f}%{}".format(
            water_cut * 100,
            " - revisar corrosion/tratamiento" if water_cut >= 0.80
            else "")})

    verdict = ("apto" if all(c["ok"] for c in checks)
               else "con reservas - ver checklist")

    return {
        "pump_displacement_bpd": round(pd_bpd, 1),
        "achievable_rate_bpd": round(achievable, 1),
        "hydraulic_hp": round(hp_hyd, 2),
        "verdict": verdict,
        "checks": checks,
    }
