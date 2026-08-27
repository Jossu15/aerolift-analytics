# AeroLift Intelligence Platform — Roadmap Unificado

**Visión:** una sola app web que evoluciona en tres fases — de "avisarte que un pozo se está cargando" a "decirte qué hacer con todo tu campo y cuánto vas a ganar con ello". Cada fase es funcional y vendible por sí sola; juntas forman el producto completo.

---

## 0. Decisión de arquitectura (aplica a todo el proyecto)

Hoy tienes Streamlit + FastAPI + Postgres en Docker. Streamlit es genial para prototipar pero no aguanta un producto multi-usuario, con auth por tiers, alertas en tiempo real y dashboards ejecutivos. Propuesta:

| Capa | Hoy | Propuesta |
|---|---|---|
| Backend | FastAPI (mantener) | FastAPI — ya tienes 227 tests, no se toca la lógica de `math_engine/` |
| Frontend | Streamlit | **Next.js (React) + Tailwind + Recharts/Plotly.js** — Streamlit se retira para el producto final, pero puede quedar como "modo ingeniero avanzado" interno |
| Auth/tiers | ApiKey header | Mantener API keys para integraciones, añadir sesiones de usuario (JWT) para la web app |
| Tiempo real | No existe | WebSockets o polling corto para el módulo de alertas (Fase 1) |
| Jobs en background | No existe | Celery/RQ + Redis, para correr el ensemble sobre cientos de pozos sin bloquear la API (necesario desde Fase 1 si hay SCADA, imprescindible en Fase 3) |

`math_engine/` no cambia de arquitectura — es tu activo más valioso. Todo lo nuevo se apoya en él.

---

## FASE 1 — Early Warning (Monitoreo continuo)
**Objetivo:** que un pozo nunca se cargue "por sorpresa". Es el gancho comercial más fácil de vender porque resuelve dolor diario.

### Qué se construye
- **Ingesta continua**: cron/worker que jala producción diaria (CSV/SCADA/API del cliente) y corre `liquid_loading.py` (ensemble) + `nodal_analysis.py` sobre cada pozo automáticamente.
- **Módulo de flujo metaestable (nuevo, del paper Dousi et al. 2006)**: hoy tu `forecast.py` asume que al cruzar Turner el pozo "muere". Dousi muestra que existe una tasa metaestable estable por debajo del crítico. Sin esto, tus predicciones de "día de muerte" en `backtest.py` van a ser sistemáticamente pesimistas. Se implementa como módulo nuevo `math_engine/metastable.py` que se engancha al forecast existente.
- **Motor de alertas**: no solo "cargado / no cargado" sino un score de días-hasta-crítico usando la tendencia de p/z + IPR actual, con umbrales configurables por el cliente.
- **UI web**: dashboard tipo semáforo por pozo (verde/amarillo/rojo), con drill-down a los 4 charts que ya tienes (`plot_operating_envelope`, etc.) renderizados en React.
- **Notificaciones**: email/Slack cuando un pozo cruza umbral.

### Se apoya en (ya existe)
`liquid_loading.py`, `nodal_analysis.py`, `forecast.py`, `charts.py`, `bulk_loader.py`, endpoints `/analysis/loading` y `/analysis/forecast`.

### Entregable de fase
App web funcional, multi-pozo, con alertas activas. Vendible a un operador con >20 pozos maduros.

---

## FASE 2 — Digital Twin (auto-calibración por pozo)
**Objetivo:** que el modelo de cada pozo mejore solo con cada dato nuevo, en vez de ser una correlación genérica de 1969.

### Qué se construye
- **Loop de calibración automática**: hoy `ml_residuals.py` ya entrena un Random Forest sobre `measured_pwf - physics_pwf`. Se convierte en un job programado que re-entrena cada vez que llega suficiente producción nueva, y versiona los modelos (ya usas joblib — se le agrega tracking de versión/fecha/métricas).
- **Selección dinámica de modelo crítico**: usar Barnea (1986) para decidir automáticamente, según el patrón de flujo calculado, si el pozo está en régimen donde domina el modelo de gota (Turner/Li) o el de película (Wallis/Barnea/Liu 2018 film-reversal). Hoy el ensemble usa reglas fijas (θ, P, D); esto lo hace físicamente más correcto.
- **Corrección para pozos desviados/horizontales (Chen et al. 2016)**: tu Belfroid actual es una corrección angular simple; Chen da una corrección basada en balance de fuerzas del film que valida mejor contra campo en pozos direccionales. Se agrega como opción de modelo dentro del ensemble para pozos con θ significativo.
- **UI de confianza**: cada predicción muestra banda de incertidumbre y "qué tan calibrado" está el twin de ese pozo (cuántos ciclos de aprendizaje lleva, error histórico).
- **Comparación físico vs. calibrado**: vista lado a lado para que el ingeniero vea qué está corrigiendo el ML y decida si confía en ello.

### Se apoya en (ya existe)
`ml_residuals.py`, `hydraulics.py`, `multiphase.py`, `gas_properties.py`.

### Entregable de fase
Cada pozo tiene su "gemelo" con predicciones que mejoran con el tiempo y trazabilidad de por qué difieren de la física pura. Este es tu diferenciador defendible frente a competidores que solo aplican Turner/Coleman estático.

---

## FASE 3 — Portfolio Optimizer (nivel campo/activo)
**Objetivo:** pasar de "este pozo está cargado" a "así es como debes gastar tu presupuesto de intervención este año".

### Qué se construye
- **Batch runner a escala**: correr Fase 1+2 sobre todo el campo en paralelo (aquí sí se necesita Celery/RQ en serio — cientos de pozos, no docenas).
- **Ranking de intervención**: usar `economics.py` (velocity string, compresión) + `recommendations.py` (escalera de mitigación) para generar, por cada pozo cargado o en riesgo, el NPV/ROI/payback de cada intervención posible, y ordenar todo el portafolio por mejor retorno.
- **Simulador de presupuesto**: el usuario mete "tengo $500K este trimestre" y el sistema arma el paquete óptimo de intervenciones (mochila/knapsack sobre el ranking anterior).
- **Dashboard ejecutivo**: vista de gerencia — Mscf/D en riesgo, $ en riesgo, $ recuperable con el presupuesto propuesto, curva de producción del campo con/sin intervención.
- **Exportables**: PDF de portafolio (ya tienes `reporting.py`) para llevar a comité.

### Se apoya en (ya existe)
`economics.py`, `recommendations.py`, `bulk_loader.py`, `reporting.py`.

### Entregable de fase
Producto que se vende no al ingeniero sino al gerente de producción/activo — ticket de venta más alto, ciclo de decisión distinto.

---

## Resumen de físicas nuevas a incorporar (transversales, no de una sola fase)

| Modelo/paper | Dónde se engancha | Por qué importa |
|---|---|---|
| Dousi et al. 2006 (metaestable) | Fase 1 — `forecast.py` | Evita predicciones de muerte prematura/pesimistas |
| Barnea 1986 (transición de patrones) | Fase 2 — selección de modelo en ensemble | Selección de modelo físicamente justificada, no por reglas ad hoc |
| Chen et al. 2016 (pozos desviados) | Fase 2 — ensemble para θ alto | Mejor que solo corrección angular de Belfroid |
| Liu et al. 2018 (film reversal) | Fase 2 — alternativa a modelo de gota | Más robusto en diámetros grandes / baja tasa |
| Ikpeka 2018 (coef. deformación gota) | Fase 2 — refinamiento Turner/Li | Reduce error reportado de 35%→20% según el paper |

---

## Orden sugerido de ejecución (siguiente conversación)

1. Migrar el esqueleto de la web app (Next.js) conectado a tu FastAPI existente, sin tocar `math_engine/`.
2. Implementar `metastable.py` y engancharlo a `forecast.py` + `backtest.py` (mejora medible con tus 227 tests como base).
3. Construir el dashboard semáforo de Fase 1 sobre 1-2 pozos reales/sintéticos.
4. Recién ahí entrar a Fase 2 (calibración) y Fase 3 (portafolio).

¿Por cuál de estos cuatro pasos quieres que empecemos a escribir código?
