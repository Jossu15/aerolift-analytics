"""
math_engine.charts
------------------
Plotly figure builders for AeroLift Analytics dashboard.
Every function returns a plotly.graph_objects.Figure.
"""

import math
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from math_engine.gas_properties import get_gas_properties, gas_fvf
from math_engine.liquid_loading import (
    critical_velocity, actual_gas_velocity, belfroid_correction,
    sigma_temperature_correction, film_flow_criterion, _liquid_properties,
    _METHOD_CONSTANTS,
)
from math_engine.ipr import fit_rawlins_schellhardt, absolute_open_flow
from math_engine.bhp_dry_gas import cullender_smith_bhp

_F2R = 459.67
_TEMPLATE = "plotly_white"


def _crit_velocity(method, p_psia, t_rankine, gamma_g, d_in,
                   liquid_type='water'):
    """Critical velocity (ft/s) honoring the regime-aware ensemble methods.

    Droplet methods (turner/coleman/li) keep the classic closed form;
    'barnea'/'smart' route through the Barnea-driven ensemble (roadmap
    2.6) so the sensitivity charts stay meaningful for those wells.
    """
    method_key = (method or 'turner').lower()
    if method_key in ('barnea', 'smart'):
        from math_engine.loading_ensemble import ensemble_critical_velocity
        return ensemble_critical_velocity(
            p_psia, t_rankine, gamma_g, d_in,
            liquid_type=liquid_type)["v_crit_ft_s"]
    props = get_gas_properties(p_psia, t_rankine, gamma_g)
    sigma, rho_L = _liquid_properties(liquid_type)
    return critical_velocity(method_key, rho_L,
                             props['density_lbm_ft3'], sigma)


def plot_operating_envelope(p_res, t_res, gamma_g, tubing_id,
                            q_actual=None, liquid_type='water',
                            method='turner'):
    fig = go.Figure()
    pressures, q_crits = [], []
    p_start = max(p_res * 0.05, 50)
    for p in range(int(p_start), int(p_res * 1.05), 20):
        try:
            props = get_gas_properties(p, t_res, gamma_g)
            rho_g = props['density_lbm_ft3']
            sigma, rho_L = _liquid_properties(liquid_type)
            if rho_g >= rho_L:
                continue
            v_crit = _crit_velocity(method, p, t_res, gamma_g, tubing_id,
                                    liquid_type)
            Bg = gas_fvf(p, t_res, props['z'])
            d_ft = tubing_id / 12.0
            area = math.pi * (d_ft ** 2) / 4.0
            q_crit = v_crit * area / Bg * 86400.0 / 1000.0
            pressures.append(p)
            q_crits.append(q_crit)
        except Exception:
            continue
    if not pressures:
        return fig
    max_q = max(q_crits) * 2
    fig.add_trace(go.Scatter(
        x=q_crits + [max_q, max_q, 0],
        y=pressures + [pressures[-1], pressures[0], pressures[0]],
        fill='toself', fillcolor='rgba(255,99,99,0.15)',
        line=dict(width=0), name='Zona de carga'))
    fig.add_trace(go.Scatter(
        x=q_crits, y=pressures, name='q_critica',
        line=dict(color='red', width=3, dash='dash')))
    try:
        props_avg = get_gas_properties(p_res * 0.5, t_res, gamma_g)
        rho_g_avg = props_avg['density_lbm_ft3']
        sigma, rho_L = _liquid_properties(liquid_type)
        rho_mix = (rho_g_avg + rho_L) / 2.0
        v_erosion = 125.0 / math.sqrt(max(rho_mix, 0.1))
        d_ft = tubing_id / 12.0
        area = math.pi * (d_ft ** 2) / 4.0
        Bg_avg = gas_fvf(p_res * 0.5, t_res, props_avg['z'])
        q_erosion = v_erosion * area / Bg_avg * 86400.0 / 1000.0
        fig.add_vline(x=q_erosion, line_dash="dot", line_color="orange",
                      annotation_text="v_erosion {:.0f} ft/s".format(v_erosion))
    except Exception:
        pass
    if q_actual is not None:
        fig.add_trace(go.Scatter(
            x=[q_actual], y=[p_res], mode='markers',
            marker=dict(size=14, color='blue', symbol='star'),
            name='Punto actual'))
    fig.update_layout(title="Envolvente de Operacion: P vs Qgas",
                      xaxis_title="Qgas (Mscf/D)", yaxis_title="P (psia)",
                      template=_TEMPLATE, height=500)
    return fig


def plot_vcrit_vs_pressure(t_res, gamma_g, tubing_id, liquid_type='water',
                           method='turner'):
    fig = make_subplots(rows=1, cols=2,
                        subplot_titles=("v_crit vs P", "q_crit vs P"))
    pressures, v_crits, q_crits = [], [], []
    for p in range(100, 6000, 50):
        try:
            props = get_gas_properties(p, t_res, gamma_g)
            rho_g = props['density_lbm_ft3']
            sigma, rho_L = _liquid_properties(liquid_type)
            if rho_g >= rho_L:
                continue
            v = _crit_velocity(method, p, t_res, gamma_g, tubing_id,
                               liquid_type)
            Bg = gas_fvf(p, t_res, props['z'])
            d_ft = tubing_id / 12.0
            area = math.pi * (d_ft ** 2) / 4.0
            q = v * area / Bg * 86400.0 / 1000.0
            pressures.append(p)
            v_crits.append(v)
            q_crits.append(q)
        except Exception:
            continue
    fig.add_trace(go.Scatter(x=pressures, y=v_crits, line=dict(color='#1f77b4', width=3)),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=pressures, y=q_crits, line=dict(color='#d62728', width=3)),
                  row=1, col=2)
    fig.update_xaxes(title_text="P (psia)", row=1, col=1)
    fig.update_xaxes(title_text="P (psia)", row=1, col=2)
    fig.update_yaxes(title_text="v_crit (ft/s)", row=1, col=1)
    fig.update_yaxes(title_text="q_crit (Mscf/D)", row=1, col=2)
    fig.update_layout(title="Sensibilidad de v_crit y q_crit vs Presion",
                      template=_TEMPLATE, height=400, showlegend=False)
    return fig


def plot_vcrit_vs_temperature(p, gamma_g, tubing_id, liquid_type='water',
                              method='turner'):
    fig = make_subplots(rows=1, cols=2,
                        subplot_titles=("v_crit vs T", "sigma vs T"))
    temps, v_crits, sigmas = [], [], []
    for t_f in range(40, 400, 5):
        t_r = t_f + _F2R
        try:
            props = get_gas_properties(p, t_r, gamma_g)
            rho_g = props['density_lbm_ft3']
            sigma_base, rho_L = _liquid_properties(liquid_type)
            sigma = sigma_temperature_correction(sigma_base, t_r, liquid_type=liquid_type)
            if rho_g >= rho_L:
                continue
            v = _crit_velocity(method, p, t_r, gamma_g, tubing_id,
                               liquid_type)
            temps.append(t_f)
            v_crits.append(v)
            sigmas.append(sigma)
        except Exception:
            continue
    fig.add_trace(go.Scatter(x=temps, y=v_crits, line=dict(color='#1f77b4', width=3)),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=temps, y=sigmas, line=dict(color='#ff7f0e', width=3)),
                  row=1, col=2)
    fig.update_xaxes(title_text="T (F)", row=1, col=1)
    fig.update_xaxes(title_text="T (F)", row=1, col=2)
    fig.update_yaxes(title_text="v_crit (ft/s)", row=1, col=1)
    fig.update_yaxes(title_text="sigma (dynes/cm)", row=1, col=2)
    fig.update_layout(title="Sensibilidad vs Temperatura",
                      template=_TEMPLATE, height=400, showlegend=False)
    return fig


def plot_vcrit_vs_diameter(p, t_res, gamma_g, liquid_type='water',
                           method='turner'):
    diameters = [1.0, 1.25, 1.5, 1.995, 2.0, 2.375, 2.5, 2.875, 3.0, 3.5, 4.0, 4.5, 5.0]
    v_crits, q_crits = [], []
    for d in diameters:
        try:
            props = get_gas_properties(p, t_res, gamma_g)
            rho_g = props['density_lbm_ft3']
            sigma, rho_L = _liquid_properties(liquid_type)
            if rho_g >= rho_L:
                v_crits.append(0); q_crits.append(0); continue
            v = _crit_velocity(method, p, t_res, gamma_g, d, liquid_type)
            Bg = gas_fvf(p, t_res, props['z'])
            d_ft = d / 12.0
            area = math.pi * (d_ft ** 2) / 4.0
            q = v * area / Bg * 86400.0 / 1000.0
            v_crits.append(v)
            q_crits.append(q)
        except Exception:
            v_crits.append(0); q_crits.append(0)
    fig = make_subplots(rows=1, cols=2,
                        subplot_titles=("v_crit vs D (constante)", "q_crit vs D (constante)"))
    fig.add_trace(go.Bar(x=[str(d)+'"' for d in diameters], y=v_crits,
                         marker_color='#1f77b4'), row=1, col=1)
    fig.add_trace(go.Bar(x=[str(d)+'"' for d in diameters], y=q_crits,
                         marker_color='#d62728'), row=1, col=2)
    fig.update_yaxes(title_text="v_crit (ft/s)", row=1, col=1)
    fig.update_yaxes(title_text="q_crit (Mscf/D)", row=1, col=2)
    fig.update_layout(title="Sensibilidad vs Diametro de Tuberia (v_crit constante)",
                      template=_TEMPLATE, height=400, showlegend=False)
    return fig


def plot_pz(gp_hist, p_hist, G, intercept, slope):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=gp_hist, y=p_hist, mode='markers+lines',
                             marker=dict(size=10, color='blue'), name='Datos'))
    gp_max = max(gp_hist) * 1.3
    gp_line = [0, gp_max]
    p_line = [intercept + slope * g for g in gp_line]
    fig.add_trace(go.Scatter(x=gp_line, y=p_line, mode='lines',
                             line=dict(color='red', dash='dash'), name='Ajuste p/z'))
    fig.add_trace(go.Scatter(x=[G], y=[0], mode='markers',
                             marker=dict(size=14, color='green', symbol='x'),
                             name='OGIP'))
    fig.update_layout(title="Material Balance p/z", xaxis_title="Gp (MMscf)",
                      yaxis_title="P/z (psia)", template=_TEMPLATE, height=450)
    return fig


def plot_deliverability_loglog(pwf_list, q_list, p_res):
    fig = go.Figure()
    diffs_sq = [(p_res**2 - p**2) for p in pwf_list]
    fig.add_trace(go.Scatter(x=q_list, y=diffs_sq, mode='markers+lines',
                             marker=dict(size=10), name='Prueba'))
    if len(q_list) >= 2:
        import numpy as np
        log_q = [math.log10(q) for q in q_list if q > 0]
        log_dp2 = [math.log10(d) for d in diffs_sq if d > 0]
        if len(log_q) >= 2:
            n = (log_q[-1] - log_q[0]) / (log_dp2[-1] - log_dp2[0]) if log_dp2[-1] != log_dp2[0] else 1.0
            fig.add_annotation(text="n = {:.3f}".format(abs(n)),
                               xref="x", yref="y", x=q_list[1], y=diffs_sq[1],
                               showarrow=False, font=dict(size=14, color='red'))
    fig.update_layout(title="Deliverabilidad Log-Log (Rawlins-Schellhardt)",
                      xaxis_title="q (Mscf/D)", yaxis_title="Pr^2 - Pwf^2",
                      xaxis_type="log", yaxis_type="log",
                      template=_TEMPLATE, height=450)
    return fig


def plot_temperature_profile(p_wh, t_wh, t_res, tvd, q_gas, d, gamma_g, n=30):
    depths, temps = [], []
    for i in range(n + 1):
        z = tvd * i / n
        T = t_wh + (t_res - t_wh) * (z / tvd) ** 0.8
        depths.append(z)
        temps.append(T - _F2R)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=temps, y=depths, mode='lines+markers',
                             line=dict(color='#d62728', width=3)))
    fig.update_layout(title="Perfil Geotermico", xaxis_title="Temperatura (F)",
                      yaxis_title="Profundidad (ft)", yaxis=dict(autorange='reversed'),
                      template=_TEMPLATE, height=500)
    return fig


def plot_erosional_velocity(tubing_id, gamma_g, q_range=None):
    fig = go.Figure()
    densities = [0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0]
    d_ft = tubing_id / 12.0
    area = math.pi * (d_ft ** 2) / 4.0
    for rho in densities:
        v_erosion = 125.0 / math.sqrt(max(rho, 0.01))
        q_e = v_erosion * area * 86400.0 / 1000.0
        fig.add_trace(go.Scatter(x=[rho], y=[v_erosion], mode='markers+text',
                                 text=["{:.0f} ft/s".format(v_erosion)],
                                 textposition="top center",
                                 marker=dict(size=12), showlegend=False))
    rhos = [i * 0.1 for i in range(1, 50)]
    vs = [125.0 / math.sqrt(max(r, 0.01)) for r in rhos]
    fig.add_trace(go.Scatter(x=rhos, y=vs, mode='lines',
                             line=dict(color='red', width=2, dash='dash'),
                             name='API RP 14E: C=125'))
    fig.update_layout(title="Velocidad Erosional (API RP 14E)",
                      xaxis_title="Densidad mezcla (lbm/ft3)",
                      yaxis_title="v_erosion (ft/s)",
                      template=_TEMPLATE, height=400)
    return fig


def plot_hydrate_curve():
    pressures = list(range(100, 6000, 100))
    t_hydrate = []
    for p in pressures:
        T = 38.0 * (p / 1000.0) ** 0.36
        t_hydrate.append(T)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pressures, y=t_hydrate, mode='lines',
                             line=dict(color='blue', width=3),
                             name='Hidratos metano'))
    fig.add_trace(go.Scatter(x=pressures, y=[32.0] * len(pressures), mode='lines',
                             line=dict(color='cyan', dash='dash'),
                             name='32 F (0 C)'))
    fig.add_vrect(x0=0, x1=1000, y0=0, y1=75, fillcolor='rgba(200,200,255,0.1)',
                  line_width=0, annotation_text="Zona comun de operacion")
    fig.update_layout(title="Curva de Hidratos de Metano",
                      xaxis_title="Presion (psia)", yaxis_title="Temperatura (F)",
                      template=_TEMPLATE, height=450)
    return fig


def plot_multi_model_comparison(p, t_res, gamma_g, d, liquid_type='water'):
    methods = ['turner', 'coleman', 'li']
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c']
    fig = go.Figure()
    pressures, curves = [], {m: [] for m in methods}
    for pp in range(100, 6000, 100):
        try:
            props = get_gas_properties(pp, t_res, gamma_g)
            rho_g = props['density_lbm_ft3']
            sigma, rho_L = _liquid_properties(liquid_type)
            if rho_g >= rho_L:
                continue
            pressures.append(pp)
            for m in methods:
                curves[m].append(critical_velocity(m, rho_L, rho_g, sigma))
        except Exception:
            continue
    for m, c in zip(methods, colors):
        fig.add_trace(go.Scatter(x=pressures, y=curves[m], name=m.capitalize(),
                                 line=dict(color=c, width=3)))
    fig.add_trace(go.Scatter(x=pressures,
                             y=[curves['turner'][i] * belfroid_correction(45)
                                for i in range(len(pressures))],
                             name='Turner+Belfroid 45d',
                             line=dict(color='purple', width=2, dash='dash')))
    fig.add_trace(go.Scatter(x=pressures,
                             y=[film_flow_criterion(d, 67.0, 0.028 * pp / 1000)
                                for pp in pressures],
                             name='Film flow',
                             line=dict(color='gray', width=2, dash='dot')))
    fig.update_layout(title="Comparacion Multi-Modelo vs Presion",
                      xaxis_title="P (psia)", yaxis_title="v_crit (ft/s)",
                      template=_TEMPLATE, height=450)
    return fig


def plot_belfroid_envelope(p, t_res, gamma_g, d, q_actual, liquid_type='water'):
    import numpy as np
    angles = np.linspace(5, 90, 50)
    rates = np.linspace(10, q_actual * 2.5, 50)
    v_turner = critical_velocity('turner', 67.0,
                                 get_gas_properties(p, t_res, gamma_g)['density_lbm_ft3'],
                                 60.0)
    z = np.zeros((len(angles), len(rates)))
    for i, theta in enumerate(angles):
        v_crit = v_turner * belfroid_correction(theta)
        for j, q in enumerate(rates):
            v_act = actual_gas_velocity(q, p, t_res, gamma_g, d)
            z[i, j] = 1 if v_act < v_crit else 0
    fig = go.Figure(data=go.Contour(
        z=z, x=rates, y=list(angles),
        colorscale=[[0, 'rgba(99,255,99,0.3)'], [1, 'rgba(255,99,99,0.3)']],
        showscale=False))
    fig.add_trace(go.Scatter(x=[q_actual], y=[45], mode='markers',
                             marker=dict(size=14, color='blue', symbol='star'),
                             name='Punto actual'))
    fig.update_layout(title="Envelope Belfroid: Angulo vs Tasa",
                      xaxis_title="Qgas (Mscf/D)",
                      yaxis_title="Inclinacion (grados desde horizontal)",
                      template=_TEMPLATE, height=450)
    return fig


def plot_decline_type_curves(q_i, b, Di_days, months=60):
    days = list(range(0, months * 30 + 1, 10))
    q_exp = [q_i * math.exp(-Di_days * t) for t in days]
    q_hyp = [q_i * (1 + b * Di_days * t) ** (-1.0 / b) if b != 0
             else q_i * math.exp(-Di_days * t) for t in days]
    q_harm = [q_i / (1 + Di_days * t) for t in days]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=days, y=q_exp, name='Exponencial (b=0)',
                             line=dict(color='#1f77b4', width=3)))
    fig.add_trace(go.Scatter(x=days, y=q_harm, name='Armonica (b=1)',
                             line=dict(color='#ff7f0e', width=3)))
    fig.add_trace(go.Scatter(x=days, y=q_hyp, name='Hiperbolica (b={:.1f})'.format(b),
                             line=dict(color='#2ca02c', width=3)))
    fig.update_layout(title="Curvas de Declinacion de Arps",
                      xaxis_title="Dias", yaxis_title="q (Mscf/D)",
                      template=_TEMPLATE, height=400)
    return fig


def plot_margins_histogram(margins):
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=margins, nbinsx=30,
                               marker_color='#1f77b4', opacity=0.7))
    fig.add_vline(x=0, line_dash="dash", line_color="red")
    fig.update_layout(title="Distribucion de Margenes (q - q_crit) / q_crit",
                      xaxis_title="Margen (fraccion)", yaxis_title="Conteo",
                      template=_TEMPLATE, height=400)
    return fig


def plot_confusion_matrix(tp, tn, fp, fn):
    fig = go.Figure(data=go.Heatmap(
        z=[[tn, fp], [fn, tp]],
        x=['Pred: OK', 'Pred: Cargando'],
        y=['Real: OK', 'Real: Cargando'],
        colorscale='RdYlGn', text=[[str(tn), str(fp)], [str(fn), str(tp)]],
        texttemplate="%{text}", textfont={"size": 20}))
    fig.update_layout(title="Matriz de Confusion",
                      template=_TEMPLATE, height=400)
    return fig


def plot_accuracy_by_pressure(wells_data, method='turner'):
    ranges = [(0, 500), (500, 1000), (1000, 2000), (2000, 3000), (3000, 6000)]
    labels, accs = [], []
    for lo, hi in ranges:
        correct, total = 0, 0
        for w in wells_data:
            p = w.get('p_wh_psia', 0)
            if lo <= p < hi and w.get('correct') is not None:
                total += 1
                if w['correct']:
                    correct += 1
        if total > 0:
            labels.append("{}-{} psia".format(lo, hi))
            accs.append(100.0 * correct / total)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=accs, marker_color='#1f77b4'))
    fig.update_layout(title="Accuracy por Rango de Presion",
                      xaxis_title="Rango de Presion", yaxis_title="Accuracy (%)",
                      template=_TEMPLATE, height=400)
    return fig


def plot_corey_rel_perm(lam=2.0, n_points=50):
    sw_list = [i / (n_points - 1) for i in range(n_points)]
    krg = [(1 - sw) ** (2 + lam) for sw in sw_list]
    krw = [sw ** (2 + 3 * lam - 2) for sw in sw_list]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sw_list, y=krg, name='Krg (gas)',
                             line=dict(color='#1f77b4', width=3)))
    fig.add_trace(go.Scatter(x=sw_list, y=krw, name='Krw (agua)',
                             line=dict(color='#d62728', width=3)))
    fig.update_layout(title="Permeabilidad Relativa (Corey, lambda={:.1f})".format(lam),
                      xaxis_title="Sw (saturacion de agua)", yaxis_title="Kr",
                      template=_TEMPLATE, height=400)
    return fig
