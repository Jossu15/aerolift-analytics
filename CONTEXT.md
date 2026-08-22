# AeroLift Analytics - Mathematical Context
## Source: Gas Reservoir Engineering by Lee & Wattenbarger

This document contains the core mathematical models, equations, and rules for the AeroLift Analytics project. All calculations MUST use **Field Units** unless explicitly stated otherwise.

## 1. Units and Conventions
- **Pressure:** Always absolute (`psia`). If given `psig`, add 14.7.
- **Temperature:** Always absolute Rankine (`°R`). Convert Fahrenheit by adding 459.67 (or 460 for simplicity).
- **Flow Rate:** Gas in `Mscf/D` (Thousands of standard cubic feet per day).
- **Density:** `lbm/ft³`.
- **Viscosity:** `cp` (centipoise).
- **Length/Depth:** `ft` (feet).
- **Diameter:** `in` (inches) for pipe, but convert to `ft` for Reynolds number and friction calculations.

## 2. Gas Properties (Chapter 1)

### 2.1 Pseudocritical Properties (Sutton's Correlation)
Used when gas composition is unknown. Requires gas specific gravity ($\gamma_g$, air=1.0).
- $P_{pc} = 756.8 - 131.0\gamma_g - 3.6\gamma_g^2$  (psia)
- $T_{pc} = 169.2 + 349.5\gamma_g - 74.0\gamma_g^2$  (°R)

### 2.2 Pseudoreduced Properties
- $P_{pr} = P / P_{pc}$
- $T_{pr} = T / T_{pc}$

### 2.3 Gas Compressibility Factor (z-factor)
- Use the **Dranchuk-Abou-Kassem (DAK)** Equation of State.
- It is an implicit equation and requires an iterative root-finding solver (e.g., Newton-Raphson or SciPy's `fsolve`).
- Valid ranges: $0.2 \le P_{pr} < 30$ and $1.0 < T_{pr} \le 3.0$.

### 2.4 Gas Density
- $\rho_g = \frac{2.70 \cdot \gamma_g \cdot P}{z \cdot T}$  (lbm/ft³)

### 2.5 Gas Viscosity
- Use the **Lee-Gonzalez-Eakin** correlation.
- Requires apparent molecular weight $M = 28.96 \cdot \gamma_g$.

## 3. Wellbore Hydraulics & Pressure Traverse (Chapter 4)

### 3.1 Mechanical Energy Balance (Vertical Pipe)
For single-phase gas flow in a vertical wellbore (no shaft work):
$$ \frac{144 \cdot dp}{\rho} + dZ + \frac{v \cdot dv}{g_c} + dF = 0 $$
*(Note: 144 is the conversion factor from ft² to in²).*

### 3.2 Reynolds Number ($N_{Re}$)
- $N_{Re} = \frac{20 \cdot \gamma_g \cdot q_g}{\mu_g \cdot d}$
- Where $q_g$ is in Mscf/D, $\mu_g$ in cp, and $d$ is pipe ID in inches.
- Laminar flow if $N_{Re} \le 2000$. Turbulent if $N_{Re} > 4000$.

### 3.3 Friction Factor ($f$)
- Use the **Colebrook-White** equation or **Haaland** approximation for turbulent flow.
- Relative roughness ($\epsilon/d$): For new tubing, use $\epsilon = 0.0006$ inches.

## 4. Liquid Loading & Critical Velocity (Chapter 8)

### 4.1 Turner's Method for Liquid Loading
A well is "loaded" (will die) if the actual gas velocity drops below the critical velocity required to lift liquid droplets.

**General Equation (Eq 8.32):**
$$ v_{g,min} = 20.404 \left[ \frac{\sigma (\rho_L - \rho_g)}{\rho_g^2} \right]^{0.25} $$
*(Where $\sigma$ is interfacial tension in dynes/cm, $\rho$ in lbm/ft³, $v$ in ft/sec).*

**Simplified for Water (Eq 8.33):**
Assuming $\sigma = 60$ dynes/cm and $\rho_L = 67$ lbm/ft³:
$$ v_{g,w} = 5.62 \left[ \frac{67 - 0.0031 P}{0.0031 P} \right]^{0.25} $$

**Simplified for Condensate (Eq 8.34):**
Assuming $\sigma = 20$ dynes/cm and $\rho_L = 45$ lbm/ft³:
$$ v_{g,c} = 4.02 \left[ \frac{45 - 0.0031 P}{0.0031 P} \right]^{0.25} $$

**Actual Gas Velocity Calculation:**
$$ v_{actual} = \frac{3.06 \cdot q_g \cdot T \cdot z}{P \cdot d^2} $$
*(Where $q_g$ in Mscf/D, $T$ in °R, $P$ in psia, $d$ in inches. Result in ft/sec).*

**Rule:** If $v_{actual} < v_{g,min}$, the well is liquid loaded.

## 5. Nodal Analysis & Deliverability (Chapter 4 & 7)

### 5.1 Inflow Performance Relationship (IPR)
Describes reservoir deliverability.
- **Rawlins-Schellhardt:** $q_g = C (\bar{p}^2 - p_{wf}^2)^n$
- **Houpeurt (Pseudopressure):** $\bar{p}_p - p_{p,wf} = a \cdot q_g + b \cdot q_g^2$

### 5.2 Tubing Performance Curve (VLP)
Describes the Bottomhole Flowing Pressure ($BHFP$ or $p_{wf}$) required to lift fluids to the surface at a given rate. Calculated using the wellbore flow equations (Section 3).

### 5.3 Natural Flow Point
The intersection of the IPR curve and the VLP curve. This is the stable operating point of the well.

## 6. Multiphase Flow (Chapter 4)
When water/condensate is present, use the **Beggs-Brill** correlation.
- Calculates liquid holdup ($H_L$) based on flow regimes (Segregated, Intermittent, Distributed).
- Calculates mixture density: $\rho_m = \rho_L H_L + \rho_g (1 - H_L)$.
- Calculates pressure gradient $dp/dL$ including friction and hydrostatic head.