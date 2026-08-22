from math_engine.nodal_analysis import find_well_flow_point, calculate_pwf_ipr, calculate_pwf_vlp

# --- TEST CASE: Matching Example 4.9 from Lee & Wattenbarger ---
# Reservoir and Well Data
p_res = 2000.0      # Average reservoir pressure (psia)
a = 1.5e6           # Houpeurt 'a' coefficient (psia^2 / Mscf/D) - *Adjusted for test*
b = 5.0e3           # Houpeurt 'b' coefficient (psia^2 / (Mscf/D)^2) - *Adjusted for test*

p_wh = 1000.0       # Wellhead flowing pressure (psia)
T_wh = 75.0 + 460.0 # Wellhead temperature (Rankine)
T_res = 150.0 + 460.0 # Reservoir temperature (Rankine)
L = 6000.0          # Tubing length / TVD (ft)
d = 1.995           # Tubing ID (inches)
gamma_g = 0.65      # Gas specific gravity

print("--- Nodal Analysis Test ---")

# 1. Test IPR at a specific rate
q_test = 2.0 # Mscf/D
p_wf_ipr = calculate_pwf_ipr(q_test, p_res, a, b)
print(f"IPR p_wf at {q_test} Mscf/D: {p_wf_ipr:.2f} psia")

# 2. Test VLP at a specific rate
p_wf_vlp = calculate_pwf_vlp(q_test, p_wh, T_wh, T_res, L, d, gamma_g)
print(f"VLP p_wf at {q_test} Mscf/D: {p_wf_vlp:.2f} psia")

# 3. Find the Natural Flow Point (Intersection)
print("\n--- Finding Natural Flow Point ---")
result = find_well_flow_point(p_res, a, b, p_wh, T_wh, T_res, L, d, gamma_g)

if result['converged']:
    print(f"SUCCESS! Natural Flow Point Found:")
    print(f"  Optimal Flow Rate (q_opt): {result['q_opt']:.2f} Mscf/D")
    print(f"  Bottomhole Pressure (p_wf): {result['p_wf_opt']:.2f} psia")
else:
    print(f"FAILED to converge: {result['message']}")