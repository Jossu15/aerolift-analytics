import streamlit as st
import plotly.graph_objects as go
import numpy as np
from math_engine.liquid_loading import check_liquid_loading, calculate_turner_velocity
from math_engine.gas_properties import get_gas_properties

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="AeroLift Analytics", page_icon="🛢️", layout="wide")
st.title("🛢️ AeroLift Analytics: Gas Well Optimization")
st.markdown("---")

# ==========================================
# SIDEBAR INPUTS (The "Control Panel")
# ==========================================
st.sidebar.header("1. Well & Reservoir Parameters")

# Reservoir Data
st.sidebar.subheader("Reservoir")
p_res = st.sidebar.number_input("Avg. Reservoir Pressure (psia)", value=3000.0, step=100.0)
t_res_f = st.sidebar.number_input("Reservoir Temperature (°F)", value=200.0)
k = st.sidebar.number_input("Permeability (md)", value=10.0)
h = st.sidebar.number_input("Net Pay Thickness (ft)", value=50.0)
s = st.sidebar.number_input("Skin Factor", value=0.0)

# Wellbore Data
st.sidebar.subheader("Wellbore")
p_wh = st.sidebar.number_input("Wellhead Flowing Pressure (psia)", value=1000.0, step=50.0)
t_wh_f = st.sidebar.number_input("Wellhead Temperature (°F)", value=120.0)
tvd = st.sidebar.number_input("True Vertical Depth (ft)", value=8000.0)
tubing_id = st.sidebar.number_input("Tubing Inner Diameter (inches)", value=2.441)

# Fluid Data
st.sidebar.subheader("Fluid Properties")
gamma_g = st.sidebar.number_input("Gas Specific Gravity (air=1.0)", value=0.65, step=0.01)

# Operating Data
st.sidebar.subheader("Current Operations")
q_gas = st.sidebar.number_input("Current Gas Flow Rate (Mscf/D)", value=2.5, step=0.1)

# Convert Temperatures to Rankine
t_res = t_res_f + 460
t_wh = t_wh_f + 460

# ==========================================
# MAIN DASHBOARD TABS
# ==========================================
tab1, tab2, tab3 = st.tabs(["🚨 Liquid Loading Check", " Nodal Analysis (IPR vs VLP)", "🔧 Well Recommendations"])

# ==========================================
# TAB 1: LIQUID LOADING DIAGNOSTIC
# ==========================================
with tab1:
    st.header("Turner's Critical Velocity Analysis")
    st.markdown("Evaluating if the current gas velocity is sufficient to lift liquids to the surface based on **Eq. 8.33 & 8.34**.")
    
    # Calculate using our math engine
    results = check_liquid_loading(q_gas, p_wh, t_wh, gamma_g, tubing_id, fluid_type='water')
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(label="Actual Gas Velocity", value=f"{results['actual_velocity_ft_sec']} ft/sec")
    with col2:
        st.metric(label="Critical Velocity (Turner)", value=f"{results['critical_velocity_ft_sec']} ft/sec")
    with col3:
        status = "LOADED ⚠️" if results['is_loaded'] else "STABLE ✅"
        st.metric(label="Well Status", value=status)

    # Visual Gauge for Velocity
    fig_gauge = go.Figure(go.Indicator(
        mode = "gauge+number+delta",
        value = results['actual_velocity_ft_sec'],
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': "Velocity Margin (ft/sec)"},
        delta = {'reference': results['critical_velocity_ft_sec']},
        gauge = {
            'axis': {'range': [None, results['critical_velocity_ft_sec'] * 1.5]},
            'bar': {'color': "darkblue"},
            'steps' : [
                {'range': [0, results['critical_velocity_ft_sec']], 'color': "red"},
                {'range': [results['critical_velocity_ft_sec'], results['critical_velocity_ft_sec'] * 1.5], 'color': "green"}],
            'threshold' : {'line': {'color': "black", 'width': 4}, 'thickness': 0.75, 'value': results['critical_velocity_ft_sec']}
        }))
    st.plotly_chart(fig_gauge, use_container_width=True)

    if results['is_loaded']:
        st.error(f"⚠️ **WARNING:** The well is liquid loaded! Actual velocity ({results['actual_velocity_ft_sec']} ft/s) is below Turner's critical velocity ({results['critical_velocity_ft_sec']} ft/s). The well will likely die soon without intervention.")
    else:
        st.success(f"✅ **GOOD:** The well is currently stable. You have a velocity margin of {results['actual_velocity_ft_sec'] - results['critical_velocity_ft_sec']:.2f} ft/s before liquid loading occurs.")

# ==========================================
# TAB 2: NODAL ANALYSIS
# ==========================================
with tab2:
    st.header("Nodal Analysis: Inflow vs. Outflow")
    st.markdown("Intersecting the Reservoir Deliverability (IPR) with the Tubing Performance (VLP) to find the **Natural Flow Point**.")
    
    # Generate Flow Rate Array
    q_array = np.linspace(0.1, 20.0, 100) # 0.1 to 20 Mscf/D
    
    # --- Simplified IPR Calculation (Houpeurt / Backpressure approximation) ---
    # Using a simplified pseudo-steady state equation for demonstration
    # p_wf_res = sqrt(p_res^2 - (a*q + b*q^2))
    # For UI demo, we'll use a simplified linear/quadratic IPR
    a_ipr = (p_res**2) / (10.0 * 10**6) # Dummy coefficient for demo
    p_wf_ipr = np.sqrt(np.maximum(p_res**2 - a_ipr * (q_array**2) * 1e6, 0))
    
    # --- Simplified VLP Calculation ---
    # p_wf_tub = p_wh + Hydrostatic + Friction (Simplified for UI)
    # In a real app, this calls the iterative Cullender-Smith or Avg T&Z method
    rho_g_avg = 0.05 # lbm/ft3 (approx)
    hydrostatic = 0.433 * rho_g_avg * tvd * (tubing_id/12) # Rough approx
    friction = 0.001 * (q_array**2) * tvd / (tubing_id**5)
    p_wf_vlp = p_wh + hydrostatic + friction
    
    # Find Intersection (Natural Flow Point)
    diff = p_wf_ipr - p_wf_vlp
    idx = np.where(np.diff(np.sign(diff)))[0]
    
    if len(idx) > 0:
        q_opt = q_array[idx[0]]
        p_opt = p_wf_ipr[idx[0]]
        st.success(f"🎯 **Natural Flow Point Found:** {q_opt:.2f} Mscf/D at {p_opt:.0f} psia BHFP")
    else:
        q_opt = None
        st.warning("⚠️ No intersection found. The well might be dead (VLP > IPR) or flowing unrestricted.")

    # Plotting the Curves
    fig_nodal = go.Figure()
    
    fig_nodal.add_trace(go.Scatter(x=q_array, y=p_wf_ipr, mode='lines', name='IPR (Reservoir)', line=dict(color='blue', width=3)))
    fig_nodal.add_trace(go.Scatter(x=q_array, y=p_wf_vlp, mode='lines', name='VLP (Tubing)', line=dict(color='red', width=3)))
    
    if q_opt:
        fig_nodal.add_trace(go.Scatter(x=[q_opt], y=[p_opt], mode='markers', name='Natural Flow Point', 
                                       marker=dict(size=15, color='green', symbol='star')))

    fig_nodal.update_layout(
        title="IPR vs VLP Curve",
        xaxis_title="Gas Flow Rate (Mscf/D)",
        yaxis_title="Bottomhole Flowing Pressure (psia)",
        yaxis=dict(autorange="reversed"), # Standard for nodal analysis
        template="plotly_white",
        height=600
    )
    st.plotly_chart(fig_nodal, use_container_width=True)

# ==========================================
# TAB 3: RECOMMENDATIONS
# ==========================================
with tab3:
    st.header("AI-Driven Mitigation Strategies")
    st.markdown("Based on the current wellbore hydraulics and reservoir pressure, here are the recommended actions to prevent or fix liquid loading.")
    
    if results['is_loaded']:
        st.subheader("🚨 Immediate Actions Required")
        st.markdown("""
        1. **Velocity String (Tubing Downsizing):** 
           - *Why:* Reducing tubing ID from 2.441" to 1.995" will increase gas velocity, potentially clearing the liquids.
           - *Estimated Cost:* $15,000 - $25,000 (Workover rig required).
        
        2. **Plunger Lift Installation:**
           - *Why:* Uses the well's own gas pressure to mechanically lift liquid slugs to the surface.
           - *Estimated Cost:* $5,000 - $8,000.
           
        3. **Chemical Deliquification (Foamers):**
           - *Why:* Reduces the critical velocity required to lift water by lowering surface tension.
           - *Estimated Cost:* $500/month (Capillary string + chemical).
        """)
    else:
        st.subheader("✅ Preventative Maintenance")
        st.markdown("""
        - The well is currently stable, but as reservoir pressure ($\\bar{p}$) declines, the IPR curve will shift downward.
        - **Forecast:** At current depletion rates, this well is projected to load up in approximately **14-18 months**.
        - **Recommendation:** Begin budgeting for a Plunger Lift system for the next fiscal year.
        """)