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
from math_engine.charts import (
    plot_operating_envelope, plot_vcrit_vs_pressure,
    plot_vcrit_vs_temperature, plot_vcrit_vs_diameter,
    plot_pz, plot_deliverability_loglog,
    plot_temperature_profile, plot_erosional_velocity,
    plot_hydrate_curve, plot_multi_model_comparison,
    plot_belfroid_envelope, plot_decline_type_curves,
    plot_margins_histogram, plot_confusion_matrix,
    plot_accuracy_by_pressure, plot_corey_rel_perm,
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
from math_engine.economics import CATALOG, evaluate_intervention
from math_engine.reporting import build_report
from math_engine.oil_pvt import (
    standing_solution_gor,
    standing_bubble_point,
    oil_viscosity,
    vogel_qo_max,
    vogel_curve,
    validate_ranges,
)
from math_engine.artificial_lift import size_esp, rod_pump_check
from math_engine.bulk_loader import parse_file, bulk_analyze, results_to_csv

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
# VIEW MODE SELECTOR (sidebar top)
# ==========================================
view_mode = st.sidebar.radio(
    "Modo",
    ["Análisis de Pozo", "Carga Masiva"],
    label_visibility="collapsed")

st.sidebar.markdown("---")

if view_mode == "Carga Masiva":
    # ==========================================
    # BULK LOADER MODE — full page, no sidebar inputs
    # ==========================================
    st.header("📂 Carga Masiva de Pozos")
    st.markdown(
        "Sube un archivo **JSON**, **CSV** o **Excel** con datos de múltiples "
        "pozos. El sistema calcula liquid loading para cada pozo y compara "
        "con el estado observado si está disponible.")

    col_cfg1, col_cfg2 = st.columns([1, 1])
    with col_cfg1:
        bulk_method = st.radio(
            "Método de evaluación",
            ("turner", "coleman"), horizontal=True, key="bulk_method")
    with col_cfg2:
        st.caption(
            "**Formatos aceptados:**\n"
            "- **JSON**: lista de objetos con campos `p_wh`, `q_gas_mscfd`, etc.\n"
            "- **CSV**: encabezados con alias flexibles (`pwh`, `whp`, `q_gas`, etc.)\n"
            "- **Excel (.xlsx)**: misma estructura que CSV\n\n"
            "**Campos requeridos:** `p_wh` (presión superficie) y "
            "`q_gas_mscfd` (tasa gas). Los demás tienen defaults.")

    uploaded = st.file_uploader(
        "Selecciona archivo de pozos",
        type=["json", "csv", "xlsx"],
        help="JSON, CSV o Excel con datos de pozos",
        key="bulk_upload")

    if uploaded is not None:
        try:
            content = uploaded.read()
            raw_wells = parse_file(uploaded.name, content)
        except Exception as exc:
            st.error("Error al parsear archivo: {}".format(exc))
            raw_wells = []

        if raw_wells:
            with st.spinner("Analizando {} pozos...".format(len(raw_wells))):
                analysis = bulk_analyze(raw_wells, method=bulk_method)

            summary = analysis["summary"]

            st.subheader("📊 Resumen")
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Pozos parseados", summary["total_parsed"])
            m2.metric("Errores", summary["parse_errors"])
            m3.metric("Evaluable", summary["evaluable"])
            acc = summary["accuracy_pct"]
            m4.metric("Accuracy",
                      "{:.1f}%".format(acc) if acc is not None else "N/A")
            rec = summary["recall_pct"]
            m5.metric("Recall (loaded)",
                      "{:.1f}%".format(rec) if rec is not None else "N/A")

            if summary["errors"]:
                with st.expander(
                        "⚠️ {} pozos con errores de formato".format(
                            summary["parse_errors"])):
                    for err in summary["errors"]:
                        st.text("{}: {}".format(
                            err["tag"], "; ".join(err["errors"])))

            st.subheader("📋 Resultados por pozo")
            import pandas as pd
            df = pd.DataFrame(analysis["wells"])

            def _highlight(row):
                styles = [""] * len(row)
                if row.get("correct") is True:
                    styles = ["background-color: #d4edda"] * len(row)
                elif row.get("correct") is False:
                    styles = ["background-color: #f8d7da"] * len(row)
                return styles

            display_cols = [
                "tag", "p_wh", "t_wh_f", "gamma_g", "tubing_id_in",
                "q_gas_mscfd", "status_raw", "status_actual",
                "v_crit_ft_s", "v_actual_ft_s", "q_crit_mscfd",
                "is_loading", "margin_pct", "correct", "method"]
            existing_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(
                df[existing_cols].style.apply(_highlight, axis=1),
                use_container_width=True, height=400)

            if summary["evaluable"] > 0:
                st.subheader("🎯 Desglose de Precisión")
                b1, b2, b3, b4 = st.columns(4)
                b1.metric("Wells cargados (reales)",
                          summary["loaded_count"])
                b2.metric("Wells sin carga (reales)",
                          summary["unloaded_count"])
                b3.metric("Predichos como cargados",
                          summary["flagged_as_loading"])
                fp = summary["false_positive_pct"]
                b4.metric("Falsos positivos",
                          "{:.1f}%".format(fp) if fp is not None else "N/A")

            st.subheader("📥 Exportar")
            csv_data = results_to_csv(analysis)
            st.download_button(
                label="📥 Descargar CSV con resultados",
                data=csv_data,
                file_name="aerolift_bulk_results.csv",
                mime="text/csv")

            from math_engine.bulk_loader import results_to_json
            json_data = results_to_json(analysis)
            st.download_button(
                label="📥 Descargar JSON con resultados",
                data=json_data,
                file_name="aerolift_bulk_results.json",
                mime="application/json")

            if summary["evaluable"] > 0:
                st.subheader("Visualizacion")
                import plotly.express as px
                chart_data = df[df["status_actual"] != "unknown"].copy()
                if len(chart_data) > 0:
                    fig = px.scatter(
                        chart_data,
                        x="q_gas_mscfd", y="q_crit_mscfd",
                        color="status_actual",
                        symbol="correct",
                        hover_name="tag",
                        title="Tasa actual vs Tasa Critica",
                        labels={
                            "q_gas_mscfd": "Tasa actual (Mscf/D)",
                            "q_crit_mscfd": "Tasa critica (Mscf/D)",
                            "status_actual": "Estado real",
                            "correct": "Prediccion correcta"
                        })
                    max_val = max(chart_data["q_gas_mscfd"].max(),
                                  chart_data["q_crit_mscfd"].max()) * 1.1
                    fig.add_scatter(
                        x=[0, max_val], y=[0, max_val],
                        mode="lines", name="Linea de carga",
                        line=dict(dash="dash", color="red"))
                    st.plotly_chart(fig, use_container_width=True)

                st.subheader("Graficas de Diagnostico")
                diag1, diag2 = st.columns(2)
                with diag1:
                    margins = chart_data["margin_pct"].dropna().tolist()
                    if margins:
                        st.plotly_chart(plot_margins_histogram(margins),
                                        use_container_width=True)
                with diag2:
                    tp = len(chart_data[(chart_data["status_actual"] == "loaded") &
                                        (chart_data["is_loading"] == True)])
                    tn = len(chart_data[(chart_data["status_actual"] == "unloaded") &
                                        (chart_data["is_loading"] == False)])
                    fp = len(chart_data[(chart_data["status_actual"] == "unloaded") &
                                        (chart_data["is_loading"] == True)])
                    fn = len(chart_data[(chart_data["status_actual"] == "loaded") &
                                        (chart_data["is_loading"] == False)])
                    st.plotly_chart(plot_confusion_matrix(tp, tn, fp, fn),
                                    use_container_width=True)

                diag3, diag4 = st.columns(2)
                with diag3:
                    if "p_wh" in chart_data.columns:
                        acc_data = chart_data[["p_wh", "correct"]].dropna().to_dict("records")
                        st.plotly_chart(plot_accuracy_by_pressure(acc_data, bulk_method),
                                        use_container_width=True)
                with diag4:
                    fig_box = go.Figure()
                    for status in ["loaded", "unloaded"]:
                        subset = chart_data[chart_data["status_actual"] == status]
                        if len(subset) > 0:
                            fig_box.add_trace(go.Box(
                                y=subset["v_crit_ft_s"], name=status,
                                boxmean='sd'))
                    fig_box.update_layout(
                        title="Distribucion v_crit por Estado",
                        yaxis_title="v_crit (ft/s)",
                        template="plotly_white", height=400)
                    st.plotly_chart(fig_box, use_container_width=True)

    st.stop()  # Don't render the analysis tabs below

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
# PARSING DE INPUTS P/Z (scope principal)
# ==========================================
gp_hist = parse_float_list(gp_hist_txt)
p_hist = parse_float_list(p_hist_txt)
mb_ok = gp_hist and p_hist and len(gp_hist) == len(p_hist) \
    and len(gp_hist) >= 2 \
    and all(p2 < p1 for p1, p2 in zip(p_hist, p_hist[1:]))

# Material balance fit (scope principal para tabs 2 y 4)
intercept_mb = slope_mb = G = None
if mb_ok:
    try:
        intercept_mb, slope_mb, G = fit_material_balance(
            t_res, gamma_g, gp_hist, p_hist)
    except Exception:
        mb_ok = False

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
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "Loading", "Nodal", "Travers",
    "Forecast", "Recomend.",
    "Petroleo", "Ingenieria"])

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
    st.caption("Reducir tuberia a 1.995\" bajaria la tasa critica de "
               "{:.0f} a {:.0f} Mscf/D en estas condiciones."
               .format(q_min_now, q_min_1995))

    st.markdown("---")
    st.subheader("Graficas de Sensibilidad")

    col_env, col_vcrit = st.columns(2)
    with col_env:
        st.plotly_chart(plot_operating_envelope(
            p_res, t_res, gamma_g, tubing_id, q_actual=q_gas,
            liquid_type="water", method=load_method),
            use_container_width=True)
    with col_vcrit:
        st.plotly_chart(plot_vcrit_vs_pressure(
            t_res, gamma_g, tubing_id, "water", load_method),
            use_container_width=True)

    col_temp, col_diam = st.columns(2)
    with col_temp:
        st.plotly_chart(plot_vcrit_vs_temperature(
            eval_P, gamma_g, tubing_id, "water", load_method),
            use_container_width=True)
    with col_diam:
        st.plotly_chart(plot_vcrit_vs_diameter(
            eval_P, t_res, gamma_g, "water", load_method),
            use_container_width=True)

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

    st.markdown("---")
    st.subheader("Graficas Adicionales")
    col_pz, col_deliv = st.columns(2)
    with col_pz:
        if mb_ok and intercept_mb is not None:
            st.plotly_chart(plot_pz(gp_hist, p_hist, G, intercept_mb, slope_mb),
                            use_container_width=True)
        else:
            st.info("Ingrese historial p/z para ver grafico.")
    with col_deliv:
        if pwf_list and q_list:
            st.plotly_chart(plot_deliverability_loglog(pwf_list, q_list, p_res),
                            use_container_width=True)
        else:
            st.info("Ingrese datos de prueba para ver grafico log-log.")

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
        title="Traverse de presion ({})".format(vlp_model),
        xaxis_title="Presion (psia)",
        yaxis_title="Profundidad (ft)",
        yaxis=dict(autorange="reversed"),
        template="plotly_white", height=600)
    st.plotly_chart(fig_tr, use_container_width=True)

    st.subheader("Perfil de Temperatura")
    st.plotly_chart(plot_temperature_profile(
        p_wh, t_wh, t_res, tvd, q_operate, tubing_id, gamma_g),
        use_container_width=True)

# ------------------------------------------
# TAB 4: FORECAST + HEALTH SCORE
# ------------------------------------------
with tab4:
    st.header("Pronóstico de Vida del Pozo")

    if not mb_ok:
        st.error("Historial p/z inválido: se necesitan ≥2 pares (Gp, P) "
                 "con presión decreciente.")
        st.stop()

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

    # ---- Economía de intervención (Fase G) ----
    st.markdown("---")
    with st.expander("💰 Economía de intervención (what-if físico)"):
        col_i, col_p = st.columns(2)
        interv = col_i.selectbox("Intervención",
                                 ("velocity_string", "compression"))
        price = col_p.number_input("Precio del gas ($/Mscf)", 0.5, 20.0,
                                   3.5, 0.25)
        target_id = target_pwh = None
        if interv == "velocity_string":
            max_id = max(tubing_id - 0.05, 0.95)
            target_id = st.number_input(
                "ID objetivo velocity string (in)", 0.9,
                max_id,
                min(max(1.5, 1.0), round(max_id, 3)), 0.05)
        else:
            target_pwh = st.number_input(
                "P_wh con compresión (psia)", 30.0,
                float(p_wh) - 10.0, float(max(60.0, p_wh * 0.6)), 10.0)
        cost = st.number_input(
            "Costo de intervención (USD)", 1000.0, 2000000.0,
            float(CATALOG[interv]["default_cost_usd"]), 5000.0)

        econ_params = {
            "p_wh": float(p_wh), "t_wh_f": float(t_wh_f),
            "t_res_f": float(t_res_f), "tvd_ft": tvd,
            "tubing_id_in": tubing_id, "gamma_g": gamma_g,
            "q_water_bpd": q_water, "liquid_sg": liquid_sg,
            "vlp_model": "beggs_brill" if use_bb else "dry_rk2",
            "load_method": load_method, "friction_multiplier": fr_mult,
            "q_gas_nominal_mscfd": q_gas,
            "ipr": (("rs", {"C": rs_data["C"], "n": rs_data["n"]})
                    if rs_data else
                    ("houpeurt", {"a": a_coef, "b": b_coef})),
        }
        if st.button("Calcular ROI / NPV"):
            try:
                econ = evaluate_intervention(
                    econ_params, gp_hist, p_hist, interv,
                    gas_price_usd_mcf=price, cost_usd=cost,
                    time_step_days=30.0,
                    target_tubing_id_in=target_id,
                    target_p_wh_psia=target_pwh)
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Gas incremental",
                          "{:.0f} MMscf".format(
                              econ["incremental_gas_mmscf"]))
                m2.metric("NPV (10% anual)",
                          "${:,.0f}".format(econ["npv_usd"]))
                m3.metric("ROI", "{:.0f}%".format(econ["roi_pct"])
                          if econ["roi_pct"] is not None else "n/a")
                m4.metric("Payback",
                          "{} meses".format(econ["payback_months"])
                          if econ["payback_months"] else "> horizonte")
                ext = econ["life_extension_days"]
                st.caption("Días de vida extra del pozo: {}".format(
                    "{:.0f}".format(ext) if ext is not None else "n/a"))
                st.session_state["last_econ"] = econ
            except ValueError as exc:
                st.error(str(exc))

    # ---- Reporte PDF (un clic, misma física que la API) ----
    report_sections = [("Datos del pozo", [
        "P_res {:.0f} psia | T_res {:.0f} F | gamma_g {:.2f}".format(
            p_res, t_res, gamma_g),
        "TVD {:.0f} ft | ID {:.3f} in | P_wh {:.0f} psia | "
        "agua {:.0f} bbl/D".format(tvd, tubing_id, p_wh, q_water),
        "VLP {} | metodo {} | friccion x{:.2f}".format(
            vlp_model, load_method, fr_mult),
    ])]
    report_sections.append(("Veredicto liquid loading @ q actual "
                            "{:.0f} Mscf/D".format(q_gas), [
        "Cargando: {} | Severidad: {}".format(
            "SI" if load_res["is_loading"] else "NO", severity),
        "v_actual {:.2f} vs v_critico {:.2f} ft/s".format(
            load_res["v_actual_ft_s"], load_res["v_crit_ft_s"]),
        "Accion sugerida: {}".format(
            advice["actions"][0]["action"] if advice["actions"] else "-"),
    ]))
    if nodal:
        report_sections.append(("Analisis nodal", [
            "Punto natural: q={:.0f} Mscf/D @ Pwf={:.0f} psia".format(
                nodal["q_mscfd"], nodal["Pwf_psia"])]))
    bad_row_fc = next((r for r in history if r["status"] != "flowing"),
                      None)
    days_to_risk = int(bad_row_fc["day"]) if bad_row_fc is not None \
        and history[0]["status"] == "flowing" else None
    report_sections.append(("Pronostico p/z", [
        "OGIP ~{:.0f} MMscf | Pi/Zi {:.0f} psia".format(G, intercept_mb),
        "Dias hasta riesgo de loading: {}".format(
            days_to_risk if days_to_risk is not None
            else "sin muerte en horizonte"),
    ]))
    last_econ = st.session_state.get("last_econ")
    if last_econ:
        report_sections.append(("Economia ultima intervencion", [
            "Gas incremental: {:.0f} MMscf | NPV: ${:,.0f}".format(
                last_econ["incremental_gas_mmscf"],
                last_econ["npv_usd"]),
            "ROI: {} | Payback: {}".format(
                "{:.0f}%".format(last_econ["roi_pct"])
                if last_econ["roi_pct"] is not None else "n/a",
                "{} meses".format(last_econ["payback_months"])
                if last_econ["payback_months"] else "> horizonte"),
        ]))
    pdf_bytes = build_report(
        "AeroLift Analytics - Reporte de pozo",
        "generado desde el dashboard", report_sections)
    st.download_button("Descargar reporte PDF", pdf_bytes,
                       "aerolift_reporte.pdf", "application/pdf")

    with st.expander("Tabla del pronostico"):
        rows = [{"Día": r["day"], "Gp (MMscf)": round(r["Gp"]),
                 "Pr (psia)": round(r["Pr"]),
                 "q (Mscf/D)": round(r["q_mscfd"]),
                 "Pwf": "-" if r["Pwf"] is None else round(r["Pwf"]),
                 "Estado": r["status"]} for r in history]
        st.table(rows)

    st.subheader("Curvas de Declinacion de Arps")
    arps_qi = st.number_input("qi para Arps (Mscf/D)", 100.0, 50000.0,
                              float(history[0]["q_mscfd"]) if history else 900.0,
                              50.0, key="arps_qi")
    arps_b = st.slider("b (exponente)", 0.0, 2.0, 0.5, 0.1, key="arps_b")
    arps_Di = st.number_input("Di inicial (1/dia)", 0.0001, 0.1, 0.001, 0.0001,
                              format="%.4f", key="arps_Di")
    st.plotly_chart(plot_decline_type_curves(arps_qi, arps_b, arps_Di, months=60),
                    use_container_width=True)

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

# ------------------------------------------
# TAB 6: OIL WELLS (Fase I)
# ------------------------------------------
with tab6:
    st.header("Pozos de Petróleo - PVT, IPR y Levantamiento Artificial")
    st.caption("Correlaciones: Standing (Rs/Pb/Bo), Beggs-Robinson "
               "(viscosidad), Vogel (IPR). Unidades de campo.")

    c1, c2, c3 = st.columns(3)
    oil_api = c1.number_input("API del aceite", 10.0, 60.0, 32.0, 0.5)
    gor = c2.number_input("GOR (scf/STB)", 0.0, 3000.0, 500.0, 25.0)
    water_cut_oil = c3.slider("Water cut", 0.0, 1.0, 0.30, 0.05)

    with st.expander("Prueba de producción (calibración Vogel)",
                     expanded=True):
        t1, t2 = st.columns(2)
        qo_test = t1.number_input("qo de prueba (STB/D)", 1.0, 20000.0,
                                  500.0, 25.0)
        pwf_test = t2.number_input("Pwf de prueba (psia)", 1.0,
                                   float(p_res) - 1.0,
                                   float(p_res * 0.5), 25.0)

    try:
        rs_at_p = standing_solution_gor(p_res, t_res_f, oil_api, gamma_g)
        pb_res = standing_bubble_point(rs_at_p, t_res_f, oil_api,
                                       gamma_g)
        vis = oil_viscosity(p_res, pb_res, t_res_f, oil_api, gamma_g,
                            oil_sg=141.5 / (oil_api + 131.5))
        qo_max = vogel_qo_max(qo_test, pwf_test, p_res)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Pb (Standing)", "{:.0f} psia".format(pb_res))
        m2.metric("Rs @ p_res",
                  "{:.0f} scf/STB".format(rs_at_p))
        m3.metric("mu_o @ p_res",
                  "{:.3f} cp ({})".format(vis["mu_o_cp"],
                                          "saturado"
                                          if p_res <= pb_res
                                          else "subsaturado"))
        m4.metric("qo_max (Vogel)",
                  "{:.0f} STB/D".format(qo_max))

        fig_ipr = go.Figure()
        pts = vogel_curve(qo_max, p_res)
        fig_ipr.add_trace(go.Scatter(
            x=[p_["qo_stb_d"] for p_ in pts],
            y=[p_["pwf_psia"] for p_ in pts],
            mode="lines+markers", name="IPR Vogel"))
        fig_ipr.add_trace(go.Scatter(
            x=[qo_test], y=[pwf_test], mode="markers",
            marker=dict(color="red", size=12), name="Prueba"))
        fig_ipr.update_layout(
            title="IPR de petróleo (Vogel)",
            xaxis_title="qo (STB/D)", yaxis_title="Pwf (psia)",
            template="plotly_white", height=380)
        st.plotly_chart(fig_ipr, use_container_width=True)

        for w in validate_ranges(t_res_f, oil_api, rs_at_p):
            st.warning(w)
    except ValueError as exc:
        st.error("Entrada invalida: {}".format(exc))
        qo_max = None

    st.markdown("---")
    st.subheader("Permeabilidad Relativa (Corey)")
    corey_lam = st.slider("Lambda (Corey)", 1.0, 5.0, 2.0, 0.5, key="corey_lam")
    st.plotly_chart(plot_corey_rel_perm(corey_lam), use_container_width=True)

    st.markdown("---")
    left, right = st.columns(2)
    with left:
        st.subheader("⚡ ESP (Gould simplificado)")
        esp_rate = st.number_input("Tasa objetivo total (STB/D)",
                                   10.0, 30000.0, 800.0, 50.0,
                                   key="esp_rate")
        esp_thp = st.number_input("THP deseada (psia)", 0.0, 3000.0,
                                  150.0, 10.0, key="esp_thp")
        esp_depth = st.number_input("Profundidad de bomba (ft)",
                                    500.0, float(tvd),
                                    float(tvd * 0.9), 100.0,
                                    key="esp_depth")
        if st.button("Dimensionar ESP") and qo_max is not None:
            try:
                esp = size_esp(
                    {"p_res": float(p_res), "t_res_f": t_res_f,
                     "tvd_ft": tvd, "api_gravity": oil_api,
                     "gamma_g": gamma_g, "gor_scf_stb": gor},
                    target_rate_stb_d=esp_rate,
                    qo_max_stb_d=qo_max,
                    water_cut=water_cut_oil,
                    thp_psia=esp_thp,
                    pump_depth_ft=esp_depth)
                e1, e2, e3 = st.columns(3)
                e1.metric("PIP", "{:.0f} psia".format(
                    esp["intake_psi"]))
                e2.metric("Descarga", "{:.0f} psia".format(
                    esp["discharge_psi"]))
                e3.metric("TDH", "{:.0f} ft".format(esp["tdh_ft"]))
                f1, f2, f3 = st.columns(3)
                f1.metric("Etapas", esp["stages"])
                f2.metric("HP motor req.",
                          "{:.0f}".format(esp["motor_hp_required"]))
                f3.metric("HP comercial",
                          esp["motor_hp_recommended"] or ">250")
                for wn in esp["warnings"]:
                    st.warning(wn)
            except ValueError as exc:
                st.error(str(exc))

    with right:
        st.subheader("🔧 Bombeo mecánico (checklist)")
        rp_rate = st.number_input("Tasa objetivo (STB/D)",
                                  10.0, 30000.0, 400.0, 50.0,
                                  key="rp_rate")
        r1, r2, r3 = st.columns(3)
        rp_d = r1.number_input("Plunger (in)", 1.06, 3.75, 1.75, 0.0625)
        rp_s = r2.number_input("Carrera (in)", 12.0, 300.0, 86.0, 1.0)
        rpm_n = r3.number_input("SPM", 4.0, 12.0, 8.0, 0.5)
        rp_depth = st.number_input("Profundidad de bomba (ft)",
                                   500.0, 12000.0,
                                   min(float(tvd), 12000.0), 100.0,
                                   key="rp_depth")
        if st.button("Evaluar bombeo mecánico"):
            try:
                rp = rod_pump_check(
                    {"p_res": float(p_res), "t_res_f": t_res_f,
                     "tvd_ft": tvd, "api_gravity": oil_api,
                     "gamma_g": gamma_g},
                    target_rate_stb_d=rp_rate,
                    water_cut=water_cut_oil,
                    pump_depth_ft=rp_depth,
                    plunger_dia_in=float(rp_d),
                    stroke_len_in=float(rp_s),
                    spm=float(rpm_n))
                g1, g2, g3 = st.columns(3)
                g1.metric("PD", "{:.0f} bpd".format(
                    rp["pump_displacement_bpd"]))
                g2.metric("Disponible", "{:.0f} bpd".format(
                    rp["achievable_rate_bpd"]))
                g3.metric("HP hidráulico", "{:.1f}".format(
                    rp["hydraulic_hp"]))
                st.markdown("**Veredicto: {}**".format(rp["verdict"]))
                for chk in rp["checks"]:
                    icon = "✅" if chk["ok"] else "⚠️"
                    st.markdown("{} **{}** — {}".format(
                        icon, chk["check"], chk["note"]))
            except ValueError as exc:
                st.error(str(exc))

# ------------------------------------------
# TAB 7: ENGINEERING
# ------------------------------------------
with tab7:
    st.header("Ingenieria: Graficas de Apoyo")
    st.caption("Velocidad erosional, hidratos, comparacion multi-modelo, "
               "envelope Belfroid.")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Velocidad Erosional (API RP 14E)")
        st.plotly_chart(plot_erosional_velocity(tubing_id, gamma_g),
                        use_container_width=True)
    with c2:
        st.subheader("Curva de Hidratos de Metano")
        st.plotly_chart(plot_hydrate_curve(), use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("Comparacion Multi-Modelo")
        st.plotly_chart(plot_multi_model_comparison(
            eval_P, t_res, gamma_g, tubing_id, "water"),
            use_container_width=True)
    with c4:
        st.subheader("Envelope Belfroid (Angulo vs Tasa)")
        st.plotly_chart(plot_belfroid_envelope(
            eval_P, t_res, gamma_g, tubing_id, q_actual=q_gas),
            use_container_width=True)
