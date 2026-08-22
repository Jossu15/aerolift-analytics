"""
AeroLift Analytics - MVP Dashboard (Streamlit)
==============================================
Wires the math_engine into the five product views:

    1. Liquid Loading diagnostic   (Turner/Coleman @ bottomhole)
    2. Nodal Analysis              (real IPR vs real VLP, multi-root aware)
    3. Pressure Traverse           (dry-gas RK2 vs Beggs-Brill profiles)
    4. Forecast + Health Score     (p/z material balance -> days to loading)
    5. Recommendations             (deliquification decision tree)

All physics comes from math_engine - no dummy coefficients.
Field units throughout (see CONTEXT.md).
"""

import math

import streamlit as st
import plotly.graph_objects as go

from math_engine.gas_properties import z_factor
from math_engine.ipr import (
    fit_rawlins_schellhardt,
    absolute_open_flow,
)
from math_engine.nodal_helpers import (
    build_houpeurt_ipr_func,
    build_rawlins_schellhardt_ipr_func,
    build_avg_tz_vlp_func,
    build_dry_gas_vlp_func,
    build_beggs_brill_vlp_func,
)
from math_engine.nodal_analysis import (
    find_natural_flow_point,
    generate_curve,
    calculate_pwf_vlp,
)
from math_engine.bhp_dry_gas import cullender_smith_bhp
from math_engine.multiphase import multiphase_traverse
from math_engine.liquid_loading import (
    loading_assessment,
    minimum_flow_rate,
)
from math_engine.forecast import (
    fit_material_balance,
    forecast_well_life,
)
from math_engine.recommendations import (
    classify_loading_severity,
    recommend_interventions,
)
from math_engine.data_quality import validate_well_inputs

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="AeroLift Analytics",
                   page_icon="🛢️", layout="wide")
st.title("🛢️ AeroLift Analytics: Gas Well Optimization")
st.markdown(
    "Motor físico: Lee & Wattenbarger (*Gas Reservoir Engineering*) - "
    "DAK / Sutton / LGE · Beggs & Brill · Turner/Coleman · p/z material "
    "balance. Unidades de campo.")
st.markdown("---")

# ==========================================
# SIDEBAR INPUTS (The "Control Panel")
# ==========================================
st.sidebar.header("1. Pozo y Yacimiento")


def parse_float_list(text):
    """Parse a comma-separated string of floats -> list or None."""
    try:
        vals = [float(x) for x in str(text).replace(";", ",").split(",")
                if x.strip()]
        return vals if len(vals) >= 2 else None
    except ValueError:
        return None


with st.sidebar.expander("Yacimiento", expanded=True):
    p_res = st.number_input("Presión media de yacimiento (psia)",
                            value=2200.0, step=50.0)
    t_res_f = st.number_input("Temperatura de yacimiento (°F)",
                              value=170.0)
    gamma_g = st.number_input("Gravedad específica del gas (aire=1.0)",
                              value=0.65, step=0.01)

with st.sidebar.expander("Wellbore / Operación", expanded=True):
    p_wh = st.number_input("Presión de superficie (wellhead) (psia)",
                           value=200.0, step=10.0)
    t_wh_f = st.number_input("Temperatura de superficie (°F)", value=100.0)
    tvd = st.number_input("Profundidad TVD (ft)", value=8000.0, step=100.0)
    tubing_id = st.number_input("ID de tubería (in)", value=1.995, step=0.01)
    q_gas = st.number_input("Tasa actual de gas (Mscf/D)",
                            value=900.0, step=25.0)
    q_water = st.number_input("Producción de agua (bbl/D)",
                              value=30.0, step=5.0)
    liquid_sg = st.number_input("SG del líquido producido (agua=1.0)",
                                value=1.0, step=0.01)

with st.sidebar.expander("⚙️ Modelo físico"):
    vlp_model = st.selectbox(
        "Curva VLP (tubing performance)",
        ("Beggs-Brill (bifásico)", "Gas seco - marcha RK2",
         "Gas seco - promedio T&z"))
    load_method = st.radio("Método liquid loading",
                           ("turner", "coleman"), horizontal=True)
    bb_segments = st.slider("Segmentos Beggs-Brill", 10, 60, 25)
    fr_mult = st.number_input(
        "Multiplicador de fricción BB",
        min_value=0.1, max_value=10.0, value=1.0, step=0.1,
        help="Calibración de cuenca sobre el gradiente de fricción "
             "(1.0 = correlación virgen; >1 tubería rugosa/escarificada).")
    st.caption("El multiplicador solo afecta el perfil bifásico "
               "Beggs-Brill.")

with st.sidebar.expander("🧪 Prueba de deliverabilidad (4 puntos)"):
    st.caption("IPR por Rawlins-Schellhardt. Si está vacía o inválida, "
               "se usa Houpeurt (a, b) manuales.")
    pwf_test_txt = st.text_input("Pwf de prueba (psia, separadas por coma)",
                                 value="2100, 1900, 1600, 1200")
    q_test_txt = st.text_input("Tasas de prueba (Mscf/D)",
                               value="400, 750, 1150, 1550")

with st.sidebar.expander("📉 Historial balance de materiales"):
    st.caption("(Gp MMscf, P psia) - línea p/z para el pronóstico.")
    gp_hist_txt = st.text_input("Gp acumulado (MMscf)",
                                value="0, 800, 1800, 2600")
    p_hist_txt = st.text_input("P media (psia)",
                               value="4200, 3400, 2700, 2200")

st.sidebar.markdown("---")
st.sidebar.caption(
    "⚠️ Beggs-Brill está optimizado para tubería vertical/desviada. "
    "En laterales horizontales calibre un multiplicador de fricción "
    "según su experiencia de cuenca.")

# ==========================================
# UNIT CONVERSIONS + DATA QUALITY GATE (GIGO)
# ==========================================
t_res = t_res_f + 460.0
t_wh = t_wh_f + 460.0

issues = validate_well_inputs(
    P_res=p_res, P_wh=p_wh,
    T_surface_R=t_wh, T_bottomhole_R=t_res,
    q_gas_mscfd=q_gas, q_water_bpd=q_water,
    depth_ft=tvd, d_in=tubing_id, gamma_g=gamma_g,
)

blocking = [i for i in issues if i["severity"] == "error"]
warnings_dq = [i for i in issues if i["severity"] == "warning"]

if blocking:
    st.error("**Datos de entrada imposibles - cálculo bloqueado (GIGO):**\n\n"
             + "\n".join("- {}".format(i["message"]) for i in blocking))
    st.stop()
for w in warnings_dq:
    st.warning("{}".format(w["message"]))

# ==========================================
# ENGINE PIPELINE (single pass, shared by tabs)
# ==========================================
# --- VLP selection ---
vlp_note = None
use_bb = vlp_model.startswith("Beggs")
if use_bb and q_water <= 0:
    use_bb = False
    vlp_note = "Beggs-Brill requiere líquido > 0; usando gas seco (RK2)."

if use_bb:
    vlp_func = build_beggs_brill_vlp_func(
        P_surface=p_wh, T_surface=t_wh, T_bottomhole=t_res,
        depth_ft=tvd, gamma_g=gamma_g, liquid_sg=liquid_sg,
        q_liquid_bpd=q_water, d_in=tubing_id,
        angle_deg=90.0, n_segments=bb_segments,
        friction_multiplier=fr_mult)
elif vlp_model.startswith("Gas seco - marcha"):
    vlp_func = build_dry_gas_vlp_func(p_wh, t_wh, t_res, tvd,
                                      gamma_g, tubing_id, n_segments=40)
else:
    vlp_func = build_avg_tz_vlp_func(p_wh, t_wh, t_res, tvd,
                                     tubing_id, gamma_g)

# --- BHFP at today's rate ---
try:
    bhfp_today = vlp_func(q_gas)
except Exception:
    bhfp_today = None

eval_P = bhfp_today if bhfp_today else p_wh

# --- Liquid loading at bottomhole conditions ---
load_res = loading_assessment(eval_P, t_res, gamma_g, tubing_id,
                              q_actual_mscfd=q_gas, method=load_method)

# --- IPR selection ---
rs_data = None
ipr_func = None
pwf_list = parse_float_list(pwf_test_txt)
q_list = parse_float_list(q_test_txt)
if pwf_list and q_list and len(pwf_list) == len(q_list) \
        and all(0 < p < p_res for p in pwf_list) and all(q > 0 for q in q_list):
    try:
        C_fit, n_fit = fit_rawlins_schellhardt(p_res, pwf_list, q_list)
        if 0.3 <= n_fit <= 1.2:
            rs_data = {"C": C_fit, "n": n_fit,
                       "AOF": absolute_open_flow(p_res, C_fit, n_fit)}
            ipr_func = build_rawlins_schellhardt_ipr_func(
                p_res, C_fit, n_fit)
    except Exception:
        rs_data = None

a_coef = 2100.0
b_coef = 0.05
if rs_data is None:
    with st.sidebar.expander("Houpeurt manual (a, b)", expanded=False):
        a_coef = st.number_input("a (psia²/(Mscf/D))",
                                 value=a_coef, format="%.4g")
        b_coef = st.number_input("b (psia²/(Mscf/D)²)",
                                 value=b_coef, format="%.4g")
    ipr_func = build_houpeurt_ipr_func(p_res, a_coef, b_coef)

# Scan ceiling: deliverability limit of whichever IPR is active
if rs_data:
    q_ceiling = rs_data["AOF"]
else:
    disc = a_coef ** 2 + 4.0 * b_coef * p_res ** 2
    q_ceiling = (-a_coef + math.sqrt(disc)) / (2.0 * b_coef)
q_max_scan = max(min(q_ceiling * 1.05, 30000.0), 20.0)
q_min_scan = max(q_gas / 100.0, 5.0)

# --- Nodal Analysis (natural flow point, multi-intersection aware) ---
nodal = find_natural_flow_point(ipr_func, vlp_func,
                                q_min=q_min_scan,
                                q_max=q_max_scan,
                                n_scan=90, prefer="highest_rate")

q_operate = nodal["q_mscfd"] if nodal else q_gas

# --- Severity + recommendations (Step 2.4) ---
severity = classify_loading_severity(load_res["is_loading"],
                                     load_res["margin_fraction"],
                                     water_rate_bpd=q_water)
advice = recommend_interventions(load_res["is_loading"],
                                 load_res["margin_fraction"],
                                 water_rate_bpd=q_water,
                                 d_in=tubing_id,
                                 q_actual_mscfd=load_res["q_actual_mscfd"],
                                 q_crit_mscfd=load_res["q_crit_mscfd"])

if vlp_note:
    st.info(vlp_note)

# ==========================================
# DASHBOARD TABS
# ==========================================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🚨 Liquid Loading", "⚖️ Análisis Nodal", "📉 Perfil de Presión",
    "🔮 Pronóstico y Health Score", "🔧 Recomendaciones"])

# ------------------------------------------
# TAB 1: LIQUID LOADING DIAGNOSTIC
# ------------------------------------------
with tab1:
    eval_depth = "fondo (BHFP={:.0f} psia)".format(bhfp_today) \
        if bhfp_today else "superficie (BHFP no disponible)"
    st.header("Análisis de Velocidad Crítica - {}".format(
        "Turner" if load_method == "turner" else "Coleman"))
    st.markdown(
        "Evaluado en condiciones de **{}**, donde la velocidad es mínima "
        "(mayor presión). Ecuaciones 8.32-8.34.".format(eval_depth))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Velocidad real", "{:.2f} ft/s".format(
        load_res["v_actual_ft_s"]))
    c2.metric("Velocidad crítica", "{:.2f} ft/s".format(
        load_res["v_crit_ft_s"]))
    c3.metric("Tasa crítica", "{:.0f} Mscf/D".format(
        load_res["q_crit_mscfd"]))
    margin_pct = load_res["margin_fraction"] * 100.0
    c4.metric("Margen", "{:.0f}%".format(margin_pct),
              delta=None if math.isnan(margin_pct)
              else ("cargado" if margin_pct < 0 else "estable"))

    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(load_res["v_actual_ft_s"], 2),
        title={"text": "Velocidad de gas (ft/s)"},
        gauge={
            "axis": {"range": [0, max(load_res["v_crit_ft_s"] * 1.5, 1)]},
            "bar": {"color": "darkblue"},
            "steps": [
                {"range": [0, load_res["v_crit_ft_s"]], "color": "#ff9999"},
                {"range": [load_res["v_crit_ft_s"],
                           load_res["v_crit_ft_s"] * 1.5],
                 "color": "#99e699"}],
            "threshold": {"line": {"color": "black", "width": 4},
                          "thickness": 0.75,
                          "value": load_res["v_crit_ft_s"]},
        }))
    st.plotly_chart(fig_gauge, use_container_width=True)

    if load_res["is_loading"]:
        st.error(
            "⚠️ **POZO CARGANDO:** velocidad real {:.2f} ft/s < crítica "
            "{:.2f} ft/s ({}). Sin intervención el pozo morirá por "
            "acumulación de líquidos.".format(
                load_res["v_actual_ft_s"], load_res["v_crit_ft_s"],
                load_method))
    else:
        st.success(
            "✅ **ESTABLE:** margen de {:.0f}% sobre la tasa crítica "
            "({}). Vigilar al declinar la presión del yacimiento."
            .format(margin_pct, load_method))

    # Tubing downsizing preview
    q_min_1995 = minimum_flow_rate(eval_P, t_res, gamma_g, 1.995,
                                   "water", load_method)
    q_min_now = load_res["q_crit_mscfd"]
    st.caption("💡 Reducir tubería a 1.995\" bajaría la tasa crítica de "
               "{:.0f} a {:.0f} Mscf/D en estas condiciones."
               .format(q_min_now, q_min_1995))

# ------------------------------------------
# TAB 2: NODAL ANALYSIS
# ------------------------------------------
with tab2:
    st.header("Análisis Nodal: IPR vs VLP")
    src_label = ("Rawlins-Schellhardt: C={:.4g}, n={:.3f}"
                 .format(rs_data["C"], rs_data["n"])
                 if rs_data else "Houpeurt manual (a, b)")
    st.markdown("IPR: {} | VLP: {}".format(src_label, vlp_model))

    qs_curve, ipr_curve = generate_curve(ipr_func, 1.0, q_max_scan, 60)
    _, vlp_curve = generate_curve(vlp_func, 1.0, q_max_scan, 60)

    fig_nodal = go.Figure()
    fig_nodal.add_trace(go.Scatter(
        x=qs_curve, y=ipr_curve, name="IPR (yacimiento)",
        line=dict(color="#1f77b4", width=3)))
    fig_nodal.add_trace(go.Scatter(
        x=qs_curve, y=vlp_curve, name="VLP (tubería)",
        line=dict(color="#d62728", width=3)))

    if nodal:
        stable = nodal["q_mscfd"], nodal["Pwf_psia"]
        others = [p for p in nodal["all_intersections"]
                  if abs(p["q_mscfd"] - stable[0]) > 1e-6]
        fig_nodal.add_trace(go.Scatter(
            x=[stable[0]], y=[stable[1]], name="Punto natural (estable)",
            marker=dict(size=15, color="#2ca02c", symbol="star")))
        for extra in others:
            fig_nodal.add_trace(go.Scatter(
                x=[extra["q_mscfd"]], y=[extra["Pwf_psia"]],
                name="Intersección inestable",
                marker=dict(size=11, color="#ff7f0e", symbol="x")))

    fig_nodal.update_layout(
        title="Curvas IPR / VLP y punto de flujo natural",
        xaxis_title="Qgas (Mscf/D)",
        yaxis_title="Pwf (psia)",
        yaxis=dict(autorange="reversed"),
        template="plotly_white", height=600)
    st.plotly_chart(fig_nodal, use_container_width=True)

    m1, m2 = st.columns(2)
    if nodal:
        m1.metric("Tasa natural hoy",
                  "{:.0f} Mscf/D".format(nodal["q_mscfd"]))
        m2.metric("Pwf de operación",
                  "{:.0f} psia".format(nodal["Pwf_psia"]))
        if "note" in nodal:
            st.warning("**Firma de liquid loading:** {}".format(nodal["note"]))
    else:
        st.warning("⚠️ Sin intersección en el rango escaneado: el pozo no "
                   "puede fluir naturalmente (muerto/cargado) o los "
                   "parámetros IPR son inconsistentes.")

    if rs_data:
        st.metric("AOF (absolute open flow)",
                  "{:.0f} Mscf/D".format(rs_data["AOF"]))

# ------------------------------------------
# TAB 3: PRESSURE TRAVERSE
# ------------------------------------------
with tab3:
    st.header("Perfil de Presión vs Profundidad")
    st.markdown("Calculado a la tasa de operación "
                "**{:.0f} Mscf/D** (+ {:.0f} bbl/D agua)."
                .format(q_operate, q_water))

    prof_dry = cullender_smith_bhp(p_wh, t_wh, t_res, tvd, gamma_g,
                                   q_operate, tubing_id, 40)[1]

    fig_tr = go.Figure()
    depths_dry = [row[0] for row in prof_dry]
    press_dry = [row[1] for row in prof_dry]
    fig_tr.add_trace(go.Scatter(
        x=press_dry, y=depths_dry, name="Gas seco (RK2)",
        line=dict(color="#1f77b4", width=3)))

    if q_water > 0:
        _, prof_wet = multiphase_traverse(
            P_surface=p_wh, T_surface=t_wh, T_bottomhole=t_res,
            depth_ft=tvd, gamma_g=gamma_g, liquid_sg=liquid_sg,
            q_gas_mscfd=q_operate, q_liquid_bpd=q_water,
            d_in=tubing_id, angle_deg=90.0, n_segments=bb_segments,
            friction_multiplier=fr_mult)
        depths_wet = [row["depth_ft"] for row in prof_wet]
        press_wet = [row["P"] for row in prof_wet]
        fig_tr.add_trace(go.Scatter(
            x=press_wet, y=depths_wet, name="Beggs & Brill (gas+agua)",
            line=dict(color="#d62728", width=3, dash="dot")))
        last = prof_wet[-1]
        st.metric("Pwf Beggs-Brill", "{:.0f} psia".format(last["P"]))
        patterns = {}
        for row in prof_wet[1:]:
            patterns[row.get("pattern", "-")] = \
                patterns.get(row.get("pattern", "-"), 0) + 1
        st.caption("Patrones de flujo (tramos): {}".format(patterns))

    fig_tr.update_layout(
        title="Traverse de presión ({})".format(vlp_model),
        xaxis_title="Presión (psia)",
        yaxis_title="Profundidad (ft)",
        yaxis=dict(autorange="reversed"),
        template="plotly_white", height=600)
    st.plotly_chart(fig_tr, use_container_width=True)

# ------------------------------------------
# TAB 4: FORECAST + HEALTH SCORE
# ------------------------------------------
with tab4:
    st.header("Pronóstico de Vida del Pozo")
    gp_hist = parse_float_list(gp_hist_txt)
    p_hist = parse_float_list(p_hist_txt)

    mb_ok = gp_hist and p_hist and len(gp_hist) == len(p_hist) \
        and all(p2 < p1 for p1, p2 in zip(p_hist, p_hist[1:]))
    if not mb_ok:
        st.error("Historial p/z inválido: se necesitan ≥2 pares (Gp, P) "
                 "con presión decreciente.")
        st.stop()

    intercept_mb, slope_mb, G = fit_material_balance(
        t_res, gamma_g, gp_hist, p_hist)
    cG, cSlope, cInt = st.columns(3)
    cG.metric("OGIP estimado (G)", "{:.0f} MMscf".format(G))
    cSlope.metric("Gp ya producido", "{:.0f} MMscf".format(gp_hist[-1]))
    cInt.metric("Pi/Zi (intercepto)", "{:.0f} psia".format(intercept_mb))

    if rs_data:
        ipr_factory = lambda Pr: build_rawlins_schellhardt_ipr_func(
            Pr, rs_data["C"], rs_data["n"])
    else:
        ipr_factory = lambda Pr: build_houpeurt_ipr_func(Pr, a_coef, b_coef)

    def _loading_check(q, Pr, pwf):
        r = loading_assessment(pwf, t_res, gamma_g, tubing_id, q,
                               method=load_method)
        return bool(r["is_loading"])

    history = forecast_well_life(
        intercept_mb, slope_mb, G, t_res, gamma_g,
        ipr_pwf_func_factory=ipr_factory,
        vlp_pwf_func=vlp_func,
        loading_check_func=_loading_check,
        Gp_start=gp_hist[-1],
        time_step_days=30, max_steps=36,
        q_min=q_min_scan, q_max=q_max_scan)

    # Health score: days until the well stops flowing normally
    bad_row = next((r for r in history
                    if r["status"] != "flowing"), None)
    if bad_row is not None and history[0]["status"] == "flowing":
        health_days = int(bad_row["day"])
        st.metric("🩺 Health Score - días hasta riesgo",
                  "{} días (~{:.1f} meses)".format(
                      health_days, health_days / 30.4))
        st.caption("Estado final previsto: **{}**".format(bad_row["status"]))
    elif history and history[0]["status"] != "flowing":
        st.metric("🩺 Health Score", "0 días")
        st.error("El pozo ya opera bajo el umbral crítico HOY.")
    else:
        st.metric("🩺 Health Score",
                  "> {} días".format(int(len(history) * 30)))
        st.caption("Sin loading dentro del horizonte pronosticado "
                   "({} meses).".format(len(history)))

    fig_fc = go.Figure()
    for row in history:
        color = {"flowing": "#2ca02c", "loading_risk": "#ff7f0e",
                 "well_dead": "#d62728", "depleted": "#7f7f7f"}.get(
                     row["status"], "#7f7f7f")
        fig_fc.add_trace(go.Scatter(
            x=[row["day"]], y=[row["q_mscfd"]], mode="lines+markers",
            marker=dict(color=color, size=8),
            showlegend=False,
            customdata=[row["status"]],
            hovertemplate="dia %{x:.0f}: %{y:.0f} Mscf/D"
                          "<extra>%{customdata}</extra>"))
    fig_fc.update_layout(
        title="Declinación pronosticada (verde=fluyendo, naranja=cargando)",
        xaxis_title="Día", yaxis_title="Qgas natural (Mscf/D)",
        template="plotly_white", height=450)
    st.plotly_chart(fig_fc, use_container_width=True)

    with st.expander("Tabla del pronóstico"):
        rows = [{"Día": r["day"], "Gp (MMscf)": round(r["Gp"]),
                 "Pr (psia)": round(r["Pr"]),
                 "q (Mscf/D)": round(r["q_mscfd"]),
                 "Pwf": "-" if r["Pwf"] is None else round(r["Pwf"]),
                 "Estado": r["status"]} for r in history]
        st.table(rows)

# ------------------------------------------
# TAB 5: RECOMMENDATIONS
# ------------------------------------------
with tab5:
    st.header("Recomendaciones de Intervención")
    badge_color = {"stable": "🟢", "at_risk": "🟡", "mild": "🟠",
                   "moderate": "🟠", "severe": "🔴"}
    st.subheader("{} Severidad: {}".format(
        badge_color.get(severity, "⚪"), severity.upper()))
    st.info(advice["headline"])

    for act in advice["actions"]:
        with st.expander("**{}. {}**  ·  {}".format(
                act["priority"], act["action"], act["typical_cost"]),
                expanded=act["priority"] == 1):
            st.write(act["why"])

    st.markdown("---")
    st.caption(
        "Lógica Step 2.4: espuma/capilar para carga leve con poca agua · "
        "plunger lift para carga intermitente · velocity string o bombeo "
        "para carga severa con alta agua. Costos referenciales US onshore.")
