# AeroLift Analytics - Mathematical & Architectural Context

**Platform:** Gas & oil well optimization engine with physics-first models, ML corrections, and economic evaluation.
**Primary Source:** *Gas Reservoir Engineering* by Lee & Wattenbarger (SPE Textbook Vol. 5).
**Status:** 342 tests passing, Docker stack running (Postgres + FastAPI + Next.js + Streamlit). Fase 2 (Digital Twin) completa: regeneración física por pozo, ensemble Barnea, UI de confianza. Fase 3 (Portfolio Optimizer) completa: ranking de intervención, knapsack de presupuesto, dashboard ejecutivo, reporte PDF y batch runner en background.

---

## 0. Conventions

| Quantity | Unit | Notes |
|---|---|---|
| Pressure | `psia` (absolute) | If given psig, add 14.7 |
| Temperature | `°R` (Rankine) | °F + 459.67 |
| Gas rate | `Mscf/D` | Thousands of scf/day |
| Oil/liquid rate | `STB/D` or `bbl/D` | Stock-tank barrels |
| Density | `lbm/ft³` | |
| Viscosity | `cp` | |
| Length/depth | `ft` | True vertical depth (TVD) |
| Tubing diameter | `in` (inches) | Convert to ft for Reynolds/friction |
| Interfacial tension | `dyne/cm` | |
| Gas specific gravity | dimensionless | Air = 1.0 |
| API gravity | °API | Oil gravity |

---

## 1. Gas Properties (`math_engine/gas_properties.py`)

### 1.1 Pseudocritical Properties — Sutton's Correlation (Eq. 1.25-1.26)
```
Ppc = 756.8 - 131.0·γg - 3.6·γg²   (psia)
Tpc = 169.2 + 349.5·γg - 74.0·γg²  (°R)
```

### 1.2 Gas Compressibility Factor — Dranchuk-Abou-Kassem (DAK) EOS
- Implicit equation solved by Newton-Raphson on reduced density.
- Valid: 0.2 ≤ Ppr < 30, 1.0 < Tpr ≤ 3.0.
- **LRU-cached** (262,144 entries) for nodal/traverse scans.

### 1.3 Gas Density (Eq. 1.58)
```
ρg = 2.70 · γg · P / (z · T)   (lbm/ft³)
```

### 1.4 Gas Viscosity — Lee-Gonzalez-Eakin (Eq. 1.63-1.67)
Requires apparent molecular weight M = 28.96 · γg.

### 1.5 Gas Formation Volume Factor (Eq. 1.53)
```
Bg = 0.02827 · z · T / P   (ft³/scf)
```

### 1.6 Gas Compressibility (Numerical)
```
cg = 1/P - (1/z)·(dz/dP)   (1/psia)
```
Evaluated numerically via DAK with central difference.

---

## 2. Liquid Loading — Critical Velocity (`math_engine/liquid_loading.py`)

Six models implemented; the adaptive **smart ensemble** selects the best based on well conditions.

### 2.1 General Droplet Equation (Eq. 8.32)
```
v_crit = C · [σ·(ρL - ρg) / ρg²]^0.25   (ft/s)
```

### 2.2 Model Constants (C)

| Model | C | Reference | Use case |
|---|---|---|---|
| Turner (1969) | 1.593 | SPE 1474 | Standard vertical wells |
| Coleman (1991) | 1.300 | — | Low-pressure wells (< 500-1000 psia) |
| Li (2002) | 0.7241 | — | Deformed droplets, high P (> 3000 psia) |

### 2.3 Belfroid Inclination Correction (2008)
SPE 115567. Critical velocity increases in deviated wells:
```
f(θ) = (sin(1.7·θ))^0.38 / (sin(153°))^0.38
```
θ = angle from **horizontal** (0° = horizontal, 90° = vertical).

### 2.4 Temperature-Dependent Surface Tension
Macleod-Sugden approximation:
```
σ(T) = σ_ref · [(Tc - T) / (Tc - T_ref)]^1.2
```
Tc: water = 1165.67 °R, condensate ≈ 1000 °R.

### 2.5 Film Flow Criterion (Wallis 1962, Pushkina-Sorokin 1969)
```
v_film = 0.47 · √(g · D · (ρL - ρg) / ρg)
```
Dominates at LOW gas rates in LARGE diameter tubing.

### 2.6 Smart Ensemble — Adaptive Model Selection
```
1. Base:  Turner (C=1.593)
2. Deviated (θ < 70°):  × Belfroid correction
3. High P (> 3000 psia):  max(Turner, Li)
4. Large tubing (D > 3"):  max(result, Film flow)
5. Final: v_crit = max(all applicable)
```
Además, `load_method` ahora acepta `turner | coleman | barnea` (Fase 2.6).
`barnea`/`smart` conmuta a `math_engine/loading_ensemble.py`: la
clasificación de régimen de Barnea (1986) por void-fraction drift-flux
(`α = vsg / (C0·vm + 0.35·√(gD))`, C0=1.2; bandas bubble < 0.25, slug
[0.25, 0.52), churn [0.52, 0.80), annular ≥ 0.80 — vsl≈0 → annular).

Familias físicas del ensemble:
  - **Gota** (annular): Turner ó max(Turner, Li) si P > 3000 psia, con la
    corrección de deformación de Ikpeka-2018 (We-based, C clamp [0.6, 1.0])
    y × Belfroid si θ < 70°.
  - **Película** (slug/churn/bubble): max(Wallis × Chen-2016, Liu-2018).
    - Chen-2016: penalización angular f = 1/√sinθ (cap 12.0).
    - Liu-2018: velocidad de reversión de película con δ = H·D/4 (H = 0.10,
      fi = 0.02) y componente axial de la gravedad (máxima en vertical).
  - Guardas: Li a alta presión, película en tubing grande (D > 3.5 in).
El régimen se clasifica a la velocidad crítica (autoconsistente) y el
resultado expone `mechanism`/`regime`/`models`. La banda ±1σ del residual
ML se mapea a banda de tasa vía `residual_rate_band` (clamp ±50 %).

### 2.7 Actual Gas Velocity
```
v_actual = Qsc · Bg / Area = 3.06 · qg · T · z / (P · d²)
```

### 2.8 Minimum Flow Rate
```
q_min = v_crit · Area / Bg · 86400 / 1000   (Mscf/D)
```

### 2.9 Default Liquid Properties

| Liquid | σ (dyne/cm) | ρL (lbm/ft³) |
|---|---|---|
| Water | 60.0 | 67.0 |
| Condensate | 20.0 | 45.0 |

### 2.10 Validation Results

| Dataset | Wells | Best model | Accuracy |
|---|---|---|---|
| Turner (1969) vertical | 94 | Turner baseline | 71.6% |
| Xinjiang (2023) tight gas | 18 | Li (2002) | 88.9% |
| Gao (2012) deviated | 42 | Turner + Belfroid | 83.3% |

---

## 3. Wellbore Hydraulics (`math_engine/hydraulics.py`)

### 3.1 Reynolds Number (Eq. 4.27)
```
NRe = 20 · γg · qg / (μg · d)
```
Laminar ≤ 2000, Turbulent > 4000.

### 3.2 Friction Factor — Swamee-Jain (explicit Moody)
```
f = 0.25 / [log₁₀(ε/(3.7·d) + 5.74/Re^0.9)]²
```
Laminar: f = 64/Re. Default roughness ε = 0.0006 in (new tubing).

### 3.3 Vertical Lift Performance — Average T&z Method (Eq. 4.39)
```
Pwf² = e^s · Pwh² + [6.67e-4 · f · Tavg² · zavg² · qg²] / [d⁵ · cos(θ)] · (e^s - 1)
s = 0.0375 · γg · L · cos(θ) / (zavg · Tavg)
```
Iterated because z_avg and μ_avg depend on Pwf.

---

## 4. Dry-Gas BHP — Cullender-Smith Style (`math_engine/bhp_dry_gas.py`)

RK2 (midpoint) depth-marching with 30-50 segments. At each step:
```
dP/dh = ρg/144 + f·ρg·v² / (2·gc·d_ft) / 144   (psi/ft)
```
Friction factor: fully turbulent Nikuradse:
```
1/√f = 1.74 - 2·log₁₀(2·ε/d)
```

---

## 5. Multiphase Flow — Beggs & Brill (`math_engine/multiphase.py`)

### 5.1 Superficial Velocities
```
vsg = Qsc · (Psc · T · z) / (P · Tsc) / Area / 86400
vsl = Qliq · 5.615 / Area / 86400
```

### 5.2 Flow Pattern Determination
From λL (no-slip holdup) and NFr (Froude number):
- Segregated, Transition, Intermittent, Distributed
- Boundary equations L1-L4 from λL.

### 5.3 Horizontal Liquid Holdup
EL0 = a · λL^b / NFr^c (regime-specific constants a, b, c).

### 5.4 Inclination Correction Factor ψ
```
ψ = 1 + C · [sin(1.8θ) - (1/3)·sin³(1.8θ)]
```
Uphill: regime-specific C. Downhill: universal C.

### 5.5 Two-Phase Friction Factor
```
ftp = fn · exp(S)
S from y = λL/EL²  (Beggs-Brill friction ratio correlation)
```

### 5.6 Full Pressure Gradient
```
dP/dh = [ρm·sin(θ)/144 + ftp·ρns·vm²/(2·gc·d_ft)/144] / (1 - Ek)
```
where Ek = kinetic energy correction (acceleration term).

### 5.7 Depth Traverse
RK2 midpoint marching, same scheme as bhp_dry_gas.py.

---

## 6. Nodal Analysis (`math_engine/nodal_analysis.py`)

### 6.1 Inflow Performance (IPR)

**Houpeurt (pressure-squared):**
```
Pr² - Pwf² = a·q + b·q²
```

**Rawlins-Schellhardt (backpressure):**
```
q = C · (Pr² - Pwf²)^n
```
Fitted via log-log linear regression. n ∈ [0.5, 1.0].

### 6.2 Pseudopressure (Real-Gas Potential)
```
m(P) = 2 · ∫[P_ref to P] P'/(μg·z) dP'   (Simpson's rule, 200 steps)
m(Pr) - m(Pwf) = a·q + b·q²
```

### 6.3 Natural Flow Point
Bisection solver finding ALL intersections of IPR and VLP curves.
- `prefer="highest_rate"` → STABLE operating point (default).
- `prefer="lowest_rate"` → UNSTABLE point (for loading analysis).
- Classic liquid-loading signature: TWO crossings (J-curve).

### 6.4 VLP Factory Functions (`math_engine/nodal_helpers.py`)
- `build_avg_tz_vlp_func()` — dry gas, average T&z closed form.
- `build_dry_gas_vlp_func()` — dry gas, RK2 depth-marching.
- `build_beggs_brill_vlp_func()` — two-phase, full Beggs-Brill traverse.
- Friction multiplier: field-calibration factor on BB friction gradient.

---

## 7. Forecasting (`math_engine/forecast.py`)

### 7.1 Material Balance (p/z Plot)
For volumetric dry-gas reservoir:
```
P/Z = (Pi/Zi) · (1 - Gp/G)
```
Fitted via linear regression. G = -intercept/slope = OGIP (MMscf).

### 7.2 Pressure at Cumulative Production
Iterative Newton-Raphson: P/Z(P) = intercept + slope·Gp.

### 7.3 Well Life Forecast
Monthly time steps:
1. Compute Pr from Gp (material balance).
2. Rebuild IPR at new Pr.
3. Find natural flow point (Nodal).
4. Check liquid loading (Turner/Coleman).
5. Advance Gp by q·Δt.
Stops when well dies, loads up, or is depleted.

---

## 8. Backtesting (`math_engine/backtest.py`)

### 8.1 Walk-Forward Validation
For each cutoff k:
1. Fit p/z material balance on history[:k].
2. Run forecast from that point.
3. Record predicted death day.

### 8.2 Metrics
- **MAE (months):** mean absolute error of predicted death day.
- **Hit rate:** fraction within ±tol months of truth.

### 8.3 Synthetic Wells (`math_engine/synthetic.py`)
Seeded RNG generates physically-consistent mature gas wells:
- Random completion/fluid params (depth, ID, water, gravities).
- R-S IPR (AOF 3-9 MMscf/D, n 0.75-1.0).
- Volumetric p/z line → known death day as ground truth.

---

## 9. Economics (`math_engine/economics.py`)

### 9.1 Interventions Modeled
- **Velocity string:** smaller tubing ID → higher velocity, later loading.
- **Compression:** lower Pwh → more drawdown, higher rates.

### 9.2 Economics on Incremental Gas
```
Revenue = ΔMscf · gas_price ($/Mcf)
NPV = Σ(monthly discounted revenue) - Cost
ROI = (Revenue - Cost) / Cost · 100%
Payback = first month where cumulative discounted net ≥ 0
```

---

## 10. ML Residual Correction (`math_engine/ml_residuals.py`)

Random Forest on residual: `measured_pwf - physics_pwf(q)`.
Features: [q_gas_mscfd, q_water_bpd, day].
- **Physics always dominates:** ML can only correct, never replace.
- 120 trees, min_samples_leaf=2.
- Per-well models persisted via joblib.

---

## 11. Recommendations Engine (`math_engine/recommendations.py`)

### 11.1 Severity Bands
| Band | Condition |
|---|---|
| stable | Not loading, margin ≥ 20% |
| at_risk | Not loading, margin < 20% |
| mild | Loading, water < 10 bbl/D |
| moderate | Loading, water 10-30 bbl/D |
| severe | Loading, water > 30 bbl/D |

### 11.2 Mitigation Ladder
1. Capillary foamer (~$500/mo)
2. Plunger lift ($5K-$8K)
3. Velocity string ($15K-$25K)
4. Beam pump ($60K+)

---

## 12. Oil Well PVT (`math_engine/oil_pvt.py`)

### 12.1 Standing (1947)
- Solution GOR: Rs = γg · (P/18.2 + 1.4)^1.2048 · 10^(0.0125·API - 0.00091·T)
- Bubble point: Pb inverted from GOR.
- Oil FVF: Bo = 0.9759 + 0.00012·(Rs·√(γg/γo) + 1.25·T)^1.2

### 12.2 Beggs & Robinson (1975)
- Dead-oil viscosity, saturated oil viscosity.

### 12.3 Vasquez-Beggs
- Undersaturated viscosity correction.

### 12.4 Vogel (1968) IPR
```
qo = qo_max · (1 - 0.2·Pwf/Pr - 0.8·(Pwf/Pr)²)
```
Calibrated from one test point.

---

## 13. Artificial Lift (`math_engine/artificial_lift.py`)

### 13.1 ESP Sizing (Gould-style)
- Intake/discharge pressures, TDH, stage count, motor HP.
- Free-gas-at-intake warning (>10%).
- Gas anchor recommendation.

### 13.2 Beam Pump (API RP-11L spirit)
- Pump displacement: PD = 0.1166 · S · N · D²
- Feasibility checklist: displacement vs target, depth limit (9000 ft), gas interference, high water cut.

---

## 14. Data Quality & GIGO (`math_engine/data_quality.py`)

Pre-computation validation rules:
- Pwf ≥ Pr while producing → error (no drawdown).
- Pwh > Pshutin → error (sensor fault).
- Pwf < Pwh in producer → error (inverted gauges).
- Tpr ≤ 1.0 → error (two-phase region, DAK invalid).
- Tpr > 3.0, Ppr > 30 → warnings (extrapolation).
- γg outside 0.57-1.68 → warning (Sutton extrapolation).

---

## 15. Bulk Loader (`math_engine/bulk_loader.py`)

### 15.1 File Parsers
- JSON, CSV, Excel (.xlsx) with auto header detection.
- Flexible column alias mapping (English/Spanish).
- Auto metric → field unit conversion (MPa→psia, °C→°F, m³/d→Mscf/D, m→ft).

### 15.2 Bulk Analysis
- Per-well liquid loading analysis.
- Summary: accuracy, recall, false positive rate vs observed status.

---

## 16. Charts (`math_engine/charts.py`)

16 Plotly figure builders:

| Function | Tab | Description |
|---|---|---|
| `plot_operating_envelope` | Loading | P vs Qgas with loading zone |
| `plot_vcrit_vs_pressure` | Loading | v_crit and q_crit sensitivity to P |
| `plot_vcrit_vs_temperature` | Loading | v_crit and σ sensitivity to T |
| `plot_vcrit_vs_diameter` | Loading | v_crit and q_crit vs tubing ID |
| `plot_pz` | Nodal | p/z material balance plot |
| `plot_deliverability_loglog` | Nodal | Rawlins-Schellhardt log-log |
| `plot_temperature_profile` | Traverse | Geothermal gradient |
| `plot_erosional_velocity` | Ingeniería | API RP 14E erosional velocity |
| `plot_hydrate_curve` | Ingeniería | Methane hydrate equilibrium |
| `plot_multi_model_comparison` | Ingeniería | Turner vs Coleman vs Li vs Belfroid vs Film |
| `plot_belfroid_envelope` | Ingeniería | Angle vs rate loading map |
| `plot_decline_type_curves` | Forecast | Arps exponential/harmonic/hyperbolic |
| `plot_margins_histogram` | Bulk | Distribution of velocity margins |
| `plot_confusion_matrix` | Bulk | TP/TN/FP/FN heatmap |
| `plot_accuracy_by_pressure` | Bulk | Accuracy by pressure range |
| `plot_corey_rel_perm` | Petroleo | Corey relative permeability curves |

---

## 17. Reporting (`math_engine/reporting.py`)

One-page PDF via ReportLab. Shared by REST API and dashboard.
Structure: title → (heading, [lines]) sections → footer with citation.

---

## 18. API Endpoints (`api/routers/`)

### Gas Well Endpoints
| Method | Path | Tier | Description |
|---|---|---|---|
| GET | `/api/wells/{id}/analysis/loading` | basic | Liquid loading verdict |
| GET | `/api/wells/{id}/analysis/nodal` | pro | IPR/VLP intersections |
| GET | `/api/wells/{id}/analysis/traverse` | basic | Pressure vs depth |
| POST | `/api/wells/{id}/analysis/forecast` | pro | p/z decline + death day |
| GET | `/api/wells/{id}/analysis/forecast-view` | pro | Forecast preview (OGIP estimado, sin historial p/z) |
| GET | `/api/wells/{id}/analysis/charts` | basic | 4 figuras Plotly (operating envelope, vcrit vs P/T/D) |
| GET | `/api/wells/{id}/analysis/calibration` | pro | VLP vs measured BHFP |
| POST | `/api/wells/{id}/analysis/economics` | pro | Intervention what-if |
| GET | `/api/wells/{id}/analysis/report.pdf` | pro | PDF summary |
| GET | `/api/wells/alerts` | basic | Semáforo del portafolio (último snapshot o evaluación on-the-fly) |
| POST | `/api/wells/alerts/recompute` | pro | Recalcular y persistir snapshot ahora (+ notifica escalamientos) |

### Portfolio (Fase 3)
| Method | Path | Tier | Description |
|---|---|---|---|
| GET | `/api/portfolio/ranking` | pro | Mejor intervención por pozo, ordenado por NPV desc |
| POST | `/api/portfolio/budget` | pro | Knapsack 0/1 sobre el ranking bajo un capex tope |
| GET | `/api/portfolio/summary` | pro | KPIs de campo + (opcional) paquete óptimo para un presupuesto |
| GET | `/api/portfolio/report.pdf` | pro | PDF ejecutivo: resumen + ranking + paquete óptimo |
| POST | `/api/portfolio/runs` | pro | Encola evaluación batch del campo completo (202 + run_id) |
| GET | `/api/portfolio/runs` | pro | Runs recientes del key, newest first |
| GET | `/api/portfolio/runs/{id}` | pro | Run completo: status, summary, items |

### Oil Well Endpoints
| Method | Path | Description |
|---|---|---|
| POST | `/api/wells/{id}/analysis/oil-ipr` | Vogel IPR + Standing PVT |
| POST | `/api/wells/{id}/analysis/esp-sizing` | ESP design |
| POST | `/api/wells/{id}/analysis/rod-pump` | Beam pump screen |

### Bulk Endpoints
| Method | Path | Description |
|---|---|---|
| POST | `/api/wells/bulk` | JSON bulk import |
| POST | `/api/wells/bulk/upload` | File upload (JSON/CSV/XLSX) |

---

## 19. Dashboard Tabs (`app.py`)

| Tab | Content |
|---|---|
| 1. Liquid Loading | 4 charts + severity + recommendations |
| 2. Nodal Analysis | P/Z + deliverability log-log |
| 3. Pressure Traverse | Temperature profile + Beggs-Brill diagnostics |
| 4. Forecast | Arps type curves + p/z material balance |
| 5. Calibracion ML | RF residual correction + calibration metrics |
| 6. Petroleo | Corey rel-perm + Vogel IPR |
| 7. Ingenieria | Erosional velocity + hydrate + multi-model + Belfroid + D sensitivity |
| Bulk Loader | File upload + histograms + confusion matrix + accuracy by pressure |

---

## 20. Infrastructure

### Docker Stack (`docker-compose.yml`)
```
db        → PostgreSQL 15 (persistent volume pgdata)
api       → FastAPI + Alembic migrations → http://localhost:8000/docs
dashboard → Streamlit → http://localhost:8501
```

### Database Models (`api/models.py`)
- `Well` — completion params, type (gas/oil), IPR coefficients,
  `alert_margin_pct` (umbral de riesgo por pozo, default 20 %).
- `ApiKey` — authentication, ownership, tier (basic/pro).
- `ProductionHistory` — daily SCADA/time-series with optional pwf.
- `WellAlert` — snapshot persistido del semáforo por pozo (historia del alert engine).

### Auth
API key-based (`X-API-Key` header). Tiers: basic (reading), pro (full analytics).

### Alembic Migrations
10 versiones: schema creation, friction_multiplier, calibration, SCADA,
oil wells, well_alerts, alert_margin_pct, twin_models_versioned,
portfolio_runs (head `c5efab83421b`).

---

## 22. Digital Twin (Fase 2) — calibración por pozo

### TwinModel (`api/models.py`, migración `b3c9d1e5f6a7`)
Un pozo puede tener varios "gemelos" versionados. Train idempotente: sin
datos nuevos no se re-entrena (401/409 vs. último entrenamiento). Campos:
`version`, `active`, `n_points`, `r2`, `residual_std_psi`,
`feature_importances`, `created_at`.

### `api/ml_service.py`
- `train_twin` — entrena un Random Forest sobre `measured_pwf −
  physics_pwf(q)`, versión monótona, `latest` siempre apunta a la
  `train_key`, artefactos joblib en `AEROLIFT_ML_DIR` (por defecto junto a
  Postgres como fuente de verdad con fallback legacy al pickle).
- `get_active_twin` / `get_artifact` — exporta la banda ±1σ
  (`residual_std_psi`) y las feature importances.
- `delete_artifact` — borra los joblib al eliminar un pozo.

### Endpoints (`api/routers/ml.py`) — pro
| Method | Path | Descripción |
|---|---|---|
| GET | `/api/wells/{id}/ml/twins` | Historial versionado del twin |
| GET | `/api/wells/{id}/ml/status` | Estado (n_points, r2, última fecha) |
| POST | `/api/wells/{id}/ml/train` | Entrenar/re-entrenar (409 con `detail` si sin datos nuevos o 409 sin historial Pwf) |
| POST | `/api/wells/{id}/ml/predict` | Predict corregido: `pwf_physics_psia`, `pwf_ml_psia`, `correction_psi`, `band_psi` (±1σ) |

### Scheduler (`api/scheduler.py`) — `twin_calibration_loop`
Re-entrena cada pozo activo cuando llegan ≥ `ML_MIN_NEW_POINTS` (10)
registros nuevos; duerme `ML_POLL_SECONDS` (default 3600).
`ALERT_SCHEDULER_ENABLED` aplica también al loop del twin.

### UI (frontend Next.js)
Pestaña **"Digital Twin"** en `/dashboard/[wellId]`: historial de
versiones, banda ±1σ en el predict, botón Entrenar/Re-entrenar y estado
`MlStatus`. `frontend/src/lib/types.ts` + `api.ts` exponen `Twin`,
`TrainResult`, `MlStatus`, `getTwins`, `getMlStatus`, `trainTwin`.

### Higiene de datos
`crud.delete_well` limpia en cascada: `WellAlert`, `TwinModel` y
artefactos joblib del twin (`ml_service.delete_artifact`), evitando
residuos huérfanos en Postgres/disco y floats id de autoincrement.
`LoadingOut` y `loading_snapshot` exponen `method`, `mechanism`, `regime`
y `models` (aditivos, null si el método clásico no aplica).

---

## 23. Portfolio Optimizer (Fase 3)

### `math_engine/portfolio.py`
- `well_intervention_options(params, gp_list, p_list, well_id, tag, gas_price,
  costs_usd, targets, time_step_days, max_steps)` → opciones de
  intervención por pozo con NPV/ROI/payback/Δgas incremental y
  `life_extension_days`; opciones ordenadas por mejor NPV. Cada opción se
  evalúa con `economics.evaluate_intervention` sobre un historial p/z
  preview (deciline volumétrico).
- `rank_portfolio(rows, gas_price_usd_mcf, max_steps)` → reports ordenados
  por mejor NPV (mejor `None` → `-inf`); `portable_best(report)` aplana el
  `best_option` para transporte.
- `portfolio_summary(reports)` → KPIs: `wells_total/at_risk`,
  `gas_at_risk_mscfd`, `wells_actionable`, `gas_actionable_mscfd`,
  `wells_positive_npv`, `positive_npv_usd/cost_usd`,
  `positive_incremental_gas_mmscf`, `positive_roi_mean_pct`,
  `positive_payback_mean_months`.
- Intervenciones modeladas: `velocity_string` (costo $85,000, requiere
  `target_tubing_id_in`) y `compression` ($120,000, requiere
  `target_p_wh_psia`). Targets por defecto: velocity string → mayor ID
  estándar menor que el actual; compression → p_wh × 0.5 (mínimo 50 psia).
  Gas default $3.5/Mscf.

### `math_engine/budget.py`
- `optimize_budget(offers, budget_usd, one_per_well=True,
  dp_state_limit=1000000)` → knapsack 0/1 (DP en cents enteros, backtracking
  por bitsets). Devuelve `chosen`, `total_cost_usd`, `total_npv_usd`,
  `utilization_pct`, `wells_selected`, `total_incremental_gas_mmscf`.
  Score = NPV; me ata con `one_per_well` (compara NPV entre opciones del
  mismo well) y desempata por menor costo.

### Batch runner (rollout Fase 3)
- `api/portfolio_eval.py` — lógica compartida entre endpoints síncronos y
  el runner: `build_rows` (semáforo `at_risk` + preview p/z por pozo),
  `portfolio_reports` (todas las wells del key, rankeadas),
  `summary_of`, `rank_row_schema`/`flat_to_item` (forma portable → columnas
  de `PortfolioRunItem`).
- `api/portfolio_batch.py` — `ThreadPoolExecutor(max_workers=2)` que
  ejecuta runs en background con su propia `SessionLocal()`. Un run pasa
  por `queued → running → done | failed` y persiste summary + items
  (`PortfolioRun`, `PortfolioRunItem`, migración `c5efab83421b`).
  `submit_portfolio_run` encola y devuelve el id; `current_status`/
  `wait_for_run` para polling (tests/scripts). `_prune` mantiene ≤ 200
  runs por key. El frontend `/portfolio` muestra el último run y su barra
  "Recalcular en batch" con polling cada 2 s (cae a evaluación síncrona
  si no hay runs).

---

## 21. Alert Engine & Scheduler (Fase 1 - alertas activas)

### Motor (`api/alerts_engine.py`)
- `compute_portfolio_alerts(db, wells, source)` evalúa cada pozo a su tasa
  nominal, persiste un snapshot `WellAlert` (mantiene historial) y, si el
  pozo escala a peor severidad que la última notificada, dispara
  Slack y/o email (`_notify`, adaptadores no-op sin configuración).
  El snapshot incluye `days_to_risk` calculado con `forecast_view` (None
  si el forecast no aplica o falla).
- Semáforo: loaded→red, metastable→orange, at_risk→yellow (margen <
  `alert_margin_pct` del pozo), stable→green.

### Scheduler (`api/scheduler.py`) — "ingesta continua"
- Loop asyncio en el lifespan de FastAPI (un worker uvicorn).
- Env: `ALERT_SCHEDULER_ENABLED` (1/true enciende; default off),
  `ALERT_POLL_SECONDS` (default 300).

### Notificaciones (`api/notifications.py`)
- Slack incoming webhook vía `SLACK_WEBHOOK_URL` (sin dependencias, urllib).
- Email vía SMTP (stdlib `smtplib`) con env `EMAIL_SMTP_HOST`,
  `EMAIL_SMTP_PORT`, `EMAIL_SMTP_USER`, `EMAIL_SMTP_PASSWORD`, `EMAIL_FROM`,
  `EMAIL_TO` (lista separada por comas) y `EMAIL_TLS` (default on).
- Sin webhook/credenciales configura silenciosamente no-op; un fallo de
  fan-out nunca rompe la persistencia. `last_notified_severity` evita
  spam: un pozo solo pinge una vez por nivel de severidad alcanzado.

### Frontend
- `/dashboard` consulta `GET /api/wells/alerts` con polling cada
  `NEXT_PUBLIC_ALERT_POLL_MS` ms (default 60000) + botón "Actualizar".
- muestra "Actualizado HH:MM:SS" (timestamp `computed_at` del snapshot).
