from math_engine.liquid_loading import check_liquid_loading

# Test Case: A mature gas well producing water
# Pressure: 1000 psia, Temp: 160°F (620 °R), Gamma_g: 0.65
# Tubing ID: 2.441 inches, Flow Rate: 1.5 Mscf/D (Low rate, likely loaded)

p = 1000.0
T = 160.0 + 460.0  # Convert F to Rankine
gamma_g = 0.65
d = 2.441
q_g = 1.5 

results = check_liquid_loading(q_g, p, T, gamma_g, d, liquid_type='water')

print(f"--- Liquid Loading Check ---")
print(f"Actual Velocity: {results['actual_velocity_ft_sec']} ft/sec")
print(f"Critical Velocity: {results['critical_velocity_ft_sec']} ft/sec")
print(f"Min Flow Rate: {results['minimum_flow_rate_Mscf_D']} Mscf/D")
print(f"Is Well Loaded? {'YES - WARNING' if results['is_loaded'] else 'NO - Stable'}")