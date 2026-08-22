"""
Tests for math_engine.data_quality (GIGO mitigation rules).
"""

import pytest

from math_engine.data_quality import (
    validate_well_inputs,
    has_blocking_errors,
    summarize_issues,
)


def _codes(issues):
    return {i["code"] for i in issues}


class TestPressureRules:
    def test_clean_inputs_pass(self):
        issues = validate_well_inputs(P_res=2200.0, P_wh=200.0,
                                      depth_ft=8000.0, d_in=1.995,
                                      gamma_g=0.65, T_bottomhole_R=630.0)
        assert not has_blocking_errors(issues)

    def test_wh_above_shutin_flagged(self):
        issues = validate_well_inputs(P_shutin_wh=1000.0, P_wh=1200.0)
        assert "wh_above_shutin" in _codes(issues)
        assert has_blocking_errors(issues)

    def test_wh_above_reservoir_flagged(self):
        issues = validate_well_inputs(P_res=2000.0, P_wh=2400.0)
        assert "wh_above_reservoir" in _codes(issues)

    def test_no_drawdown_while_producing(self):
        issues = validate_well_inputs(P_res=2000.0, P_wf=2100.0,
                                      q_gas_mscfd=500.0)
        assert "no_drawdown" in _codes(issues)

    def test_wf_below_wh_impossible_column(self):
        issues = validate_well_inputs(P_wf=150.0, P_wh=300.0)
        assert "wf_below_wh" in _codes(issues)

    def test_negative_pressure_error(self):
        issues = validate_well_inputs(P_res=-5.0)
        assert any(i["severity"] == "error" for i in issues)


class TestTemperatureRules:
    def test_fahrenheit_in_rankine_detected(self):
        # 120 passed where ~580 R expected -> below 460 R window
        issues = validate_well_inputs(T_surface_R=120.0)
        assert any("plausible wellbore range" in i["message"]
                   for i in issues)

    def test_zero_temperature_error(self):
        issues = validate_well_inputs(T_bottomhole_R=0.0)
        assert has_blocking_errors(issues)

    def test_geothermal_inversion_warning(self):
        issues = validate_well_inputs(T_surface_R=620.0,
                                      T_bottomhole_R=600.0)
        assert "temperature_inversion" in _codes(issues)
        assert not has_blocking_errors(issues)  # warning only


class TestRateGeometryFluidRules:
    def test_negative_gas_rate(self):
        issues = validate_well_inputs(q_gas_mscfd=-10.0)
        assert "q_gas" in _codes(issues)

    def test_zero_rate_on_flowing_well_warns(self):
        issues = validate_well_inputs(q_gas_mscfd=0.0)
        assert "q_gas_zero" in _codes(issues)

    def test_unusual_tubing_id_warns(self):
        issues = validate_well_inputs(d_in=9.0)
        assert "tubing_id_unusual" in _codes(issues)

    def test_out_of_range_gravity_warns(self):
        issues = validate_well_inputs(gamma_g=2.2)
        assert "gamma_out_of_range" in _codes(issues)

    def test_dak_two_phase_region_is_error(self):
        # Very low temperature: Tpr <= 1.0 at bottomhole
        issues = validate_well_inputs(gamma_g=0.65, T_bottomhole_R=350.0)
        assert "dak_two_phase" in _codes(issues)
        assert has_blocking_errors(issues)


class TestUtilities:
    def test_errors_listed_before_warnings(self):
        issues = validate_well_inputs(P_res=-1.0, gamma_g=2.5,
                                      d_in=9.0, T_bottomhole_R=0.0)
        severities = [i["severity"] for i in issues]
        assert severities == sorted(severities,
                                    key=lambda s: {"error": 0,
                                                   "warning": 1}[s])

    def test_summarize_returns_strings(self):
        lines = summarize_issues(validate_well_inputs(P_res=-1.0))
        assert len(lines) >= 1
        assert all(isinstance(s, str) for s in lines)
