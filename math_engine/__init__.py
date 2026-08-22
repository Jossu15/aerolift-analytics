"""
AeroLift Analytics - Mathematical Engine
========================================
Field-unit gas well deliverability engine based on Lee &
Wattenbarger's "Gas Reservoir Engineering":

    gas_properties  : PVT (Sutton + DAK Z-factor + Lee-Gonzalez-Eakin)
    bhp_dry_gas     : single-phase BHP via RK2 depth-marching
    hydraulics      : friction factor + average T&z VLP (Eq. 4.39)
    multiphase      : Beggs & Brill two-phase gradients and traverses
    liquid_loading  : Turner / Coleman critical velocity diagnostics
    ipr             : Rawlins-Schellhardt and pseudopressure IPRs
    nodal_analysis  : multi-intersection natural flow point solver
    nodal_helpers   : factories wiring physics into solver callables
    forecast        : p/z material balance coupled to Nodal Analysis
    recommendations : deliquification decision tree (Step 2.4)
    data_quality    : GIGO outlier detection for input data

All functions use FIELD UNITS (see CONTEXT.md):
psia, R, ft, in, Mscf/D, bbl/D, lbm/ft3, cp.
"""

from math_engine.gas_properties import (
    sutton_pseudocriticals,
    z_factor,
    z_factor_dak,
    gas_density,
    gas_fvf,
    gas_compressibility,
    gas_viscosity_lee,
    get_gas_properties,
)
from math_engine.liquid_loading import (
    turner_critical_velocity,
    coleman_critical_velocity,
    actual_gas_velocity,
    minimum_flow_rate,
    loading_assessment,
    check_liquid_loading,
)
from math_engine.nodal_analysis import (
    calculate_pwf_ipr,
    calculate_pwf_vlp,
    find_all_intersections,
    find_natural_flow_point,
    find_well_flow_point,
    generate_curve,
)

__version__ = "0.2.0"
