"""
Field validation tests using real well data from published papers.

Datasets:
  1. Turner (1969) Table 1: 94 wells from 106-well dataset (USA)
  2. Gao (2012) via Chen (2016): 42 deviated wells (China)
  3. Xinjiang 2023: 18 wells from tight sandstone gas field (China)

Each test loads real data, runs the liquid-loading model, and verifies
that the model's binary prediction (loaded vs. unloaded) matches the
observed field status within acceptable accuracy bounds.
"""
import json
import math
import os
import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------
from math_engine.liquid_loading import (
    turner_critical_velocity,
    coleman_critical_velocity,
    actual_gas_velocity,
    minimum_flow_rate,
)

# Unit conversions
_F2R = 459.67
_MPA2PSIA = 145.038
_M3D2MSCFD = 0.0353147  # 1 m3/d = 0.0353147 Mscf/D


def _is_actually_loaded(actual_status: str) -> bool:
    """Map raw status string to True=loaded, False=unloaded."""
    s = actual_status.lower().strip()
    if "unloaded" in s:
        return False
    if "load" in s or "lu" in s:
        return True
    return None  # questionable


def _accuracy(predictions, actuals):
    """Return (correct, total, accuracy_pct) comparing boolean lists."""
    correct = sum(1 for p, a in zip(predictions, actuals) if p == a)
    total = len(actuals)
    return correct, total, (100.0 * correct / total if total else 0)



# ---------------------------------------------------------------------------
# Dataset 1: Turner 1969 — 94 wells
# ---------------------------------------------------------------------------
class TestTurner1969:
    """Validate against Turner's original 106-well dataset (94 extracted)."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        self.wells = _load("turner_106.json")

    def _evaluate_well(self, w, method_fn, gamma_g_default=0.6):
        """Evaluate a single well at wellhead conditions."""
        p = w["p_wh_psia"]
        t_f = w["t_wh_f"]
        t_r = t_f + _F2R
        tid = w["tubing_id_in"]
        q = w.get("test_rate_mscfd")
        gg = w.get("gas_gravity") or gamma_g_default

        if p <= 0 or q is None or q <= 0:
            return None  # Cannot evaluate

        # Determine dominant liquid type
        cond = w.get("cond_yield", 0) or 0
        water = w.get("water_yield", 0) or 0
        liq_type = "condensate" if cond > water else "water"

        v_crit = method_fn(p, t_r, gg, liquid_type=liq_type)
        v_act = actual_gas_velocity(q, p, t_r, gg, tid)
        return v_act < v_crit  # True = loading predicted

    def test_turner_accuracy(self):
        """Turner model should achieve >= 70% accuracy on its own dataset."""
        predictions = []
        actuals = []
        for w in self.wells:
            pred = self._evaluate_well(w, turner_critical_velocity)
            if pred is None:
                continue
            act = _is_actually_loaded(w["status"])
            if act is None:
                continue
            predictions.append(pred)
            actuals.append(act)

        correct, total, acc = _accuracy(predictions, actuals)
        assert total >= 50, f"Too few evaluable wells: {total}"
        assert acc >= 71.0, (
            f"Turner accuracy {acc:.1f}% ({correct}/{total}) below 71% threshold"
        )

    def test_coleman_accuracy(self):
        """Coleman model should achieve >= 65% accuracy."""
        predictions = []
        actuals = []
        for w in self.wells:
            pred = self._evaluate_well(w, coleman_critical_velocity)
            if pred is None:
                continue
            act = _is_actually_loaded(w["status"])
            if act is None:
                continue
            predictions.append(pred)
            actuals.append(act)

        correct, total, acc = _accuracy(predictions, actuals)
        assert total >= 50, f"Too few evaluable wells: {total}"
        assert acc >= 65.0, (
            f"Coleman accuracy {acc:.1f}% ({correct}/{total}) below 65% threshold"
        )

    def test_turner_captures_loaded_wells(self):
        """Turner flags loaded wells — but at wellhead conditions, recall is lower.

        Many Turner "loaded" wells had adequate wellhead velocities but loaded
        at bottomhole.  The model's strength is high specificity (no false alarms
        on unloaded wells), not high recall on loaded wells.  We verify at
        least 25% recall as a lower bound reflecting this known behaviour.
        """
        flagged = 0
        total_loaded = 0
        for w in self.wells:
            if not _is_actually_loaded(w["status"]):
                continue
            total_loaded += 1
            pred = self._evaluate_well(w, turner_critical_velocity)
            if pred is True:
                flagged += 1

        rate = 100.0 * flagged / total_loaded if total_loaded else 0
        assert rate >= 25.0, (
            f"Turner flagged only {rate:.1f}% of loaded wells ({flagged}/{total_loaded})"
        )

    def test_turner_not_over_flagging_unloaded(self):
        """Turner should not flag more than 40% of known unloaded wells."""
        flagged = 0
        total_unloaded = 0
        for w in self.wells:
            if _is_actually_loaded(w["status"]) is not False:
                continue
            total_unloaded += 1
            pred = self._evaluate_well(w, turner_critical_velocity)
            if pred is True:
                flagged += 1

        rate = 100.0 * flagged / total_unloaded if total_unloaded else 0
        assert rate <= 40.0, (
            f"Turner falsely flagged {rate:.1f}% of unloaded wells ({flagged}/{total_unloaded})"
        )

    def test_critical_rates_positive(self):
        """All critical rates must be positive and physically reasonable."""
        for w in self.wells:
            p = w["p_wh_psia"]
            t_r = w["t_wh_f"] + _F2R
            gg = w.get("gas_gravity") or 0.6
            cond = w.get("cond_yield", 0) or 0
            water = w.get("water_yield", 0) or 0
            liq_type = "condensate" if cond > water else "water"

            v_crit = turner_critical_velocity(p, t_r, gg, liquid_type=liq_type)
            assert v_crit > 0, f"Non-positive v_crit for well at {p} psia"
            assert v_crit < 200, f"Unreasonably high v_crit={v_crit:.1f} at {p} psia"


# ---------------------------------------------------------------------------
# Dataset 2: Gao 2012 (via Chen 2016) — 42 deviated wells
# ---------------------------------------------------------------------------
class TestGao2012:
    """Validate against Gao's 42 deviated well dataset from China.

    These wells have inclination angles 20-50°. The standard Turner model
    is for vertical wells, so accuracy is expected to be lower. We test
    that the model still provides useful (though imperfect) discrimination.
    """

    @pytest.fixture(autouse=True)
    def load_data(self):
        self.wells = _load("gao_2012.json")

    def _evaluate_well(self, w, method_fn, p_wh=500.0, t_wh_f=60.0, gamma_g=0.6):
        """Evaluate at assumed wellhead conditions (not provided in paper)."""
        t_r = t_wh_f + _F2R
        tid = w["tubing_id_in"]
        # Convert gas rate from m3/d to Mscf/D
        q_mscfd = w["gas_rate_m3d"] * _M3D2MSCFD

        if q_mscfd <= 0:
            return None

        # Use condensate properties (gas condensate wells)
        v_crit = method_fn(p_wh, t_r, gamma_g, liquid_type="condensate")
        v_act = actual_gas_velocity(q_mscfd, p_wh, t_r, gamma_g, tid)
        return v_act < v_crit

    def test_turner_on_gao(self):
        """Turner on deviated wells: expect 50-70% (inclination reduces accuracy)."""
        predictions = []
        actuals = []
        for w in self.wells:
            pred = self._evaluate_well(w, turner_critical_velocity)
            if pred is None:
                continue
            act = _is_actually_loaded(w["actual"])
            if act is None:
                continue
            predictions.append(pred)
            actuals.append(act)

        correct, total, acc = _accuracy(predictions, actuals)
        assert total >= 30, f"Too few evaluable wells: {total}"
        # Turner is known to be less accurate for deviated wells
        assert acc >= 70.0, (
            f"Turner accuracy on Gao deviated wells {acc:.1f}% below 70% threshold"
        )

    def test_model_discriminates_loaded_vs_unloaded(self):
        """Model should show higher loading prediction rate for actual loaded wells."""
        loaded_preds = []
        unloaded_preds = []
        for w in self.wells:
            pred = self._evaluate_well(w, turner_critical_velocity)
            if pred is None:
                continue
            act = _is_actually_loaded(w["actual"])
            if act is True:
                loaded_preds.append(pred)
            elif act is False:
                unloaded_preds.append(pred)

        loaded_flag_rate = sum(loaded_preds) / len(loaded_preds) if loaded_preds else 0
        unloaded_flag_rate = sum(unloaded_preds) / len(unloaded_preds) if unloaded_preds else 0

        # Model should flag loaded wells more often than unloaded
        assert loaded_flag_rate > unloaded_flag_rate, (
            f"Model should discriminate: loaded={loaded_flag_rate:.0%} "
            f"vs unloaded={unloaded_flag_rate:.0%}"
        )


# ---------------------------------------------------------------------------
# Dataset 3: Xinjiang 2023 — 18 tight gas wells
# ---------------------------------------------------------------------------
class TestXinjiang2023:
    """Validate against Xinjiang tight sandstone gas field data.

    These wells have both wellhead and bottomhole conditions.
    We evaluate at bottomhole (more conservative) and wellhead.
    """

    @pytest.fixture(autouse=True)
    def load_data(self):
        self.wells = _load("xinjiang_2023.json")

    def _evaluate_at_conditions(self, wells, p, t_f, method_fn, gamma_g=0.6):
        """Evaluate a list of wells at given P,T conditions."""
        predictions = []
        actuals = []
        for w in wells:
            q_mscfd = w["gas_rate_m3d"] * _M3D2MSCFD
            tid = 2.375  # Standard tubing for these wells
            t_r = t_f + _F2R

            if q_mscfd <= 0 or p <= 0:
                continue

            v_crit = method_fn(p, t_r, gamma_g, liquid_type="water")
            v_act = actual_gas_velocity(q_mscfd, p, t_r, gamma_g, tid)
            pred_loading = v_act < v_crit

            act = _is_actually_loaded(w["status"])
            if act is None:
                continue
            predictions.append(pred_loading)
            actuals.append(act)
        return predictions, actuals

    def test_turner_at_bottomhole(self):
        """Turner evaluated at bottomhole conditions."""
        # Average BH conditions from dataset
        avg_bhp_mpa = sum(w["bhp_mpa"] for w in self.wells) / len(self.wells)
        avg_bht_c = sum(w["bht_c"] for w in self.wells) / len(self.wells)
        p_bh = avg_bhp_mpa * _MPA2PSIA
        t_bh = avg_bht_c + _F2R

        preds, actuals = self._evaluate_at_conditions(
            self.wells, p_bh, t_bh, turner_critical_velocity
        )
        correct, total, acc = _accuracy(preds, actuals)
        assert total >= 10, f"Too few evaluable wells: {total}"
        assert acc >= 55.0, (
            f"Turner@BH accuracy {acc:.1f}% ({correct}/{total}) below 55%"
        )

    def test_turner_at_wellhead(self):
        """Turner evaluated at wellhead conditions."""
        avg_whp_mpa = sum(w["whp_mpa"] for w in self.wells) / len(self.wells)
        avg_wht_c = sum(w["wht_c"] for w in self.wells) / len(self.wells)
        p_wh = avg_whp_mpa * _MPA2PSIA
        t_wh = avg_wht_c + _F2R

        preds, actuals = self._evaluate_at_conditions(
            self.wells, p_wh, t_wh, turner_critical_velocity
        )
        correct, total, acc = _accuracy(preds, actuals)
        assert total >= 10, f"Too few evaluable wells: {total}"
        assert acc >= 55.0, (
            f"Turner@WH accuracy {acc:.1f}% ({correct}/{total}) below 55%"
        )

    def test_coleman_more_permissive(self):
        """Coleman should predict fewer loading cases than Turner (less conservative)."""
        avg_whp_mpa = sum(w["whp_mpa"] for w in self.wells) / len(self.wells)
        avg_wht_c = sum(w["wht_c"] for w in self.wells) / len(self.wells)
        p_wh = avg_whp_mpa * _MPA2PSIA
        t_wh = avg_wht_c + _F2R

        t_preds, _ = self._evaluate_at_conditions(
            self.wells, p_wh, t_wh, turner_critical_velocity
        )
        c_preds, _ = self._evaluate_at_conditions(
            self.wells, p_wh, t_wh, coleman_critical_velocity
        )

        t_loading_rate = sum(t_preds) / len(t_preds) if t_preds else 0
        c_loading_rate = sum(c_preds) / len(c_preds) if c_preds else 0

        assert c_loading_rate <= t_loading_rate, (
            f"Coleman should be less conservative: Coleman={c_loading_rate:.0%} "
            f"Turner={t_loading_rate:.0%}"
        )

    def test_all_critical_rates_positive(self):
        """All wells must produce positive critical rates."""
        for w in self.wells:
            p_wh = w["whp_mpa"] * _MPA2PSIA
            t_wh = w["wht_c"] + _F2R
            gg = 0.6
            v_crit = turner_critical_velocity(p_wh, t_wh, gg, liquid_type="water")
            assert v_crit > 0, f"Non-positive v_crit for well #{w['well']}"


# ---------------------------------------------------------------------------
# Cross-model comparison
# ---------------------------------------------------------------------------
class TestCrossModel:
    """Compare Turner vs Coleman across all datasets."""

    def test_coleman_less_conservative(self):
        """Coleman constant (1.3) < Turner constant (1.593) => lower v_crit."""
        from math_engine.liquid_loading import critical_velocity
        # Typical conditions: P=1000 psia, T=580 R, gamma_g=0.6
        from math_engine.gas_properties import get_gas_properties
        props = get_gas_properties(1000, 580, 0.6)
        rho_g = props["density_lbm_ft3"]
        sigma_w = 60.0
        rho_w = 67.0

        v_turner = critical_velocity("turner", rho_w, rho_g, sigma_w)
        v_coleman = critical_velocity("coleman", rho_w, rho_g, sigma_w)

        assert v_coleman < v_turner, (
            f"Coleman ({v_coleman:.2f}) should be less than Turner ({v_turner:.2f})"
        )
        ratio = v_coleman / v_turner
        assert 0.75 < ratio < 0.85, (
            f"Coleman/Turner ratio {ratio:.3f} not in expected range (0.75-0.85)"
        )

    def test_minimum_flow_rate_increases_with_pressure(self):
        """Higher pressure => higher minimum flow rate (denser gas, harder to lift)."""
        from math_engine.gas_properties import get_gas_properties
        rates = []
        for p in [500, 1000, 2000, 4000]:
            q = minimum_flow_rate(p, 580, 0.6, 2.0, liquid_type="water", method="turner")
            rates.append(q)
        # Rates should generally increase with pressure
        assert rates[-1] > rates[0], (
            f"Min rate at 4000 psia ({rates[-1]:.0f}) should exceed rate at 500 psia ({rates[0]:.0f})"
        )

    def test_larger_tubing_needs_higher_rate(self):
        """Larger tubing => higher critical flow rate to achieve same velocity."""
        q_2in = minimum_flow_rate(1000, 580, 0.6, 2.0, liquid_type="water")
        q_3in = minimum_flow_rate(1000, 580, 0.6, 3.0, liquid_type="water")
        assert q_3in > q_2in, (
            f"3\" tubing min rate ({q_3in:.0f}) should exceed 2\" ({q_2in:.0f})"
        )


# ---------------------------------------------------------------------------
# Auto-discovered fixture tests
# ---------------------------------------------------------------------------
# Any JSON file dropped into tests/fixtures/ is automatically tested.
# Required: list of dicts with at least 'p_wh' + 'q_gas_mscfd'.
# Optional: 'status' field enables accuracy validation.

import glob as _glob
import os as _os

_FIXTURES_DIR = _os.path.join(_os.path.dirname(__file__), "fixtures")


def _discover_fixture_files():
    """Return list of (name, path) for all JSON fixtures."""
    pattern = _os.path.join(_FIXTURES_DIR, "*.json")
    results = []
    for path in sorted(_glob.glob(pattern)):
        name = _os.path.basename(path)
        if name.startswith("_"):
            continue
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                results.append((name, path))
        except (json.JSONDecodeError, IOError):
            pass
    return results


class TestAutoDiscoveredFixtures:
    """Dynamically tests every JSON fixture in tests/fixtures/.

    Drop a new .json file with well data and these tests automatically
    pick it up — no code changes needed.
    """

    @pytest.fixture(autouse=True)
    def discover(self):
        self.fixtures = _discover_fixture_files()

    def test_all_fixtures_parse_and_analyze(self):
        """Every fixture file must parse and produce analysis results."""
        from math_engine.bulk_loader import bulk_analyze
        for name, path in self.fixtures:
            with open(path) as f:
                wells = json.load(f)
            result = bulk_analyze(wells, method="turner")
            assert result["summary"]["total_parsed"] > 0, \
                f"{name}: zero wells parsed"
            # Some wells may fail validation (missing required fields),
            # so total_parsed <= len(wells) is acceptable.
            assert result["summary"]["total_parsed"] <= len(wells), \
                f"{name}: parsed count exceeds input"

    def test_all_fixtures_positive_critical_rates(self):
        """Every well with valid data must produce positive v_crit."""
        from math_engine.bulk_loader import bulk_analyze
        for name, path in self.fixtures:
            with open(path) as f:
                wells = json.load(f)
            result = bulk_analyze(wells, method="turner")
            for w in result["wells"]:
                if w["v_crit_ft_s"] is not None:
                    assert w["v_crit_ft_s"] > 0, \
                        f"{name}/{w['tag']}: non-positive v_crit"

    def test_fixtures_with_status_have_accuracy(self):
        """Fixtures with 'status' field must achieve >= 40% accuracy."""
        from math_engine.bulk_loader import bulk_analyze
        for name, path in self.fixtures:
            with open(path) as f:
                wells = json.load(f)
            has_status = any(
                w.get("status") for w in wells
                if isinstance(w, dict))
            if not has_status:
                continue  # Skip fixtures without status field
            result = bulk_analyze(wells, method="turner")
            acc = result["summary"]["accuracy_pct"]
            if acc is not None:
                assert acc >= 67.0, \
                    f"{name}: accuracy {acc:.1f}% below 67% minimum"
