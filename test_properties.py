from math_engine.gas_properties import get_gas_properties

# Test Case (Example 1.10 / 1.11 from the book)
# P = 2000 psia, T = 200°F (which is 660 °R), gamma_g = 0.65 (Sweet gas)
P = 2000.0
T = 200.0 + 460.0  # Convert F to Rankine
gamma_g = 0.65

props = get_gas_properties(P, T, gamma_g)

print(f"--- Gas Properties at {P} psia and {T}°R ---")
print(f"Pseudocritical P: {props['Ppc']:.2f} psia")
print(f"Pseudocritical T: {props['Tpc']:.2f} °R")
print(f"Z-Factor:         {props['z']:.4f}")
print(f"Density:          {props['density_lbm_ft3']:.4f} lbm/ft3")
print(f"Viscosity:        {props['viscosity_cp']:.5f} cp")