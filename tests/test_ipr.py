"""
Tests for math_engine.ipr (Step 1.5a - deliverability formulations).

Strategy:
- Rawlins-Schellhardt: generate synthetic test data FROM a known (C, n),
  refit, and require exact recovery (log-log regression on clean data).
- Pseudopressure: monotonicity + quadratic-solver self-consistency.
"""

import pytest

from math_engine.gas_properties import get_gas_properties
from math_engine.ipr import (
    fit_rawlins_schellhardt,
    rawlins_schellhardt_rate,
    absolute_open_flow,
    pseudopressure,
    fit_pseudopressure_ipr,
    pseudopressure_rate,
)


PR = 3200.0
C_TRUE = 0.0075
N_TRUE = 0.85


class TestRawlinsSchellhardt:
    def _synthetic_test_data(self):
        pwfs = [3000.0, 2800.0, 2500.0, 2100.0]
        qs = [rawlins_schellhardt_rate(PR, p, C_TRUE, N_TRUE)
              for p in pwfs]
        return pwfs, qs

    def test_perfect_fit_recovery(self):
        pwfs, qs = self._synthetic_test_data()
        C_fit, n_fit = fit_rawlins_schellhardt(PR, pwfs, qs)
        assert C_fit == pytest.approx(C_TRUE, rel=1e-6)
        assert n_fit == pytest.approx(N_TRUE, rel=1e-6)

    def test_aof_equals_rate_at_zero_pwf(self):
        aof = absolute_open_flow(PR, C_TRUE, N_TRUE)
        assert aof == pytest.approx(
            rawlins_schellhardt_rate(PR, 0.0, C_TRUE, N_TRUE), rel=1e-12)

    def test_rate_zero_at_reservoir_pressure(self):
        assert rawlins_schellhardt_rate(PR, PR, C_TRUE, N_TRUE) == 0.0

    def test_negative_drawdown_clamps_to_zero(self):
        assert rawlins_schellhardt_rate(PR, PR + 100.0, C_TRUE, N_TRUE) == 0.0

    def test_rate_monotonic_in_drawdown(self):
        qs = [rawlins_schellhardt_rate(PR, p, C_TRUE, N_TRUE)
              for p in [3100.0, 2800.0, 2400.0, 1800.0]]
        assert qs == sorted(qs)

    def test_insufficient_points_raise(self):
        with pytest.raises(ValueError):
            fit_rawlins_schellhardt(PR, [3000.0], [1500.0])

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            fit_rawlins_schellhardt(PR, [3000.0, 2500.0],
                                    [1500.0, 2600.0, 3000.0])


class TestPseudopressure:
    def test_monotonic_in_pressure(self):
        m1 = pseudopressure(500.0, 650.0, 0.65)
        m2 = pseudopressure(1500.0, 650.0, 0.65)
        m3 = pseudopressure(3000.0, 650.0, 0.65)
        assert 0 <= m1 < m2 < m3

    def test_below_reference_is_zero(self):
        assert pseudopressure(10.0, 650.0, 0.65) == 0.0

    def test_order_of_magnitude(self):
        # Real-gas pseudopressures at thousands of psia are ~1e7-1e9 psia^2/cp
        m = pseudopressure(3200.0, 650.0, 0.65)
        assert 1e7 < abs(m) < 1e10

    def test_quadratic_solver_consistency(self):
        """pseudopressure_rate must satisfy the equation it claims to
        solve: m_Pr - m_Pwf == a*q + b*q^2."""
        T = 650.0
        m_Pr = pseudopressure(3200.0, T, 0.65)
        m_1000 = pseudopressure(1000.0, T, 0.65)
        a, b = 3.9429e4, 3.4769  # values from reference data fit
        q = pseudopressure_rate(1000.0, T, 0.65, a, b, m_Pr)
        assert q > 0
        assert a * q + b * q * q == pytest.approx(m_Pr - m_1000, rel=1e-3)


class TestPseudopressureFit:
    def test_fit_recovers_synthetic_a_b(self):
        """Generate rates from known a,b via the forward solver, then
        verify the linear regression recovers them."""
        T = 650.0
        m_Pr = pseudopressure(3200.0, T, 0.65)
        a_true, b_true = 4.0e4, 3.5
        pwfs, qs = [], []
        for target_q in [800.0, 1600.0, 2600.0, 4000.0]:
            # invert a*q+b*q^2 = dm -> choose pwf giving that dm
            dm = a_true * target_q + b_true * target_q ** 2
            # find pwf by bisection on pseudopressure
            lo, hi = 14.7, 3200.0
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                if pseudopressure(mid, T, 0.65) > m_Pr - dm:
                    hi = mid
                else:
                    lo = mid
            pwfs.append(0.5 * (lo + hi))
            qs.append(target_q)

        a_fit, b_fit, m_fit = fit_pseudopressure_ipr(3200.0, T, 0.65,
                                                     pwfs, qs)
        assert a_fit == pytest.approx(a_true, rel=2e-2)
        assert b_fit == pytest.approx(b_true, rel=5e-2)
        assert m_fit == pytest.approx(m_Pr, rel=1e-9)
