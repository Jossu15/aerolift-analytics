"""
Tests for math_engine.recommendations (Step 2.4 - decision tree).
"""

import math

import pytest

from math_engine.recommendations import (
    classify_loading_severity,
    recommend_interventions,
)


class TestSeverityClassification:
    def test_stable_with_healthy_margin(self):
        assert classify_loading_severity(False, 0.5) == "stable"

    def test_at_risk_with_thin_margin(self):
        assert classify_loading_severity(False, 0.10) == "at_risk"

    def test_nan_margin_is_at_risk(self):
        assert classify_loading_severity(False, float("nan")) == "at_risk"

    def test_mild_loading_low_water(self):
        assert classify_loading_severity(True, -0.3,
                                         water_rate_bpd=5.0) == "mild"

    def test_moderate_loading_mid_water(self):
        assert classify_loading_severity(True, -0.5,
                                         water_rate_bpd=20.0) == "moderate"

    def test_severe_loading_high_water(self):
        assert classify_loading_severity(True, -0.7,
                                         water_rate_bpd=45.0) == "severe"


class TestRecommendationTree:
    def test_stable_recommends_monitoring_only(self):
        out = recommend_interventions(False, 0.5)
        assert out["severity"] == "stable"
        assert all("monitor" in a["action"].lower()
                   or "budget" in a["action"].lower()
                   for a in out["actions"])

    def test_mild_leads_with_foamer(self):
        out = recommend_interventions(True, -0.4, water_rate_bpd=5.0,
                                      d_in=2.441, q_actual_mscfd=400.0,
                                      q_crit_mscfd=900.0)
        assert out["actions"][0]["priority"] <= \
               out["actions"][-1]["priority"]
        assert any("foamer" in a["action"].lower() or
                   "capillary" in a["action"].lower()
                   for a in out["actions"])

    def test_moderate_leads_with_plunger_or_velocity_string(self):
        out = recommend_interventions(True, -0.5, water_rate_bpd=20.0,
                                      d_in=2.441, q_actual_mscfd=300.0,
                                      q_crit_mscfd=900.0)
        top_actions = [a["action"] for a in out["actions"]
                       if a["priority"] == 1]
        joined = " ".join(top_actions).lower()
        assert ("plunger" in joined) or ("velocity string" in joined)

    def test_severe_high_water_avoids_foamer_as_first_choice(self):
        out = recommend_interventions(True, -0.7, water_rate_bpd=50.0,
                                      d_in=2.441, q_actual_mscfd=250.0,
                                      q_crit_mscfd=900.0)
        first = out["actions"][0]["action"].lower()
        assert "foamer" not in first

    def test_velocity_string_target_id_smaller_and_standard(self):
        out = recommend_interventions(True, -0.6, water_rate_bpd=25.0,
                                      d_in=2.441, q_actual_mscfd=300.0,
                                      q_crit_mscfd=900.0)
        vs = [a for a in out["actions"]
              if "velocity string" in a["action"].lower()]
        if vs:  # target exists only when downsizing helps
            import re
            m = re.search(r'(\d\.\d+)"', vs[0]["action"])
            target_id = float(m.group(1))
            assert target_id < 2.441
            from math_engine.recommendations import _STANDARD_TUBING_IDS
            assert target_id in _STANDARD_TUBING_IDS

    def test_unloaded_well_gets_no_downsizing_target(self):
        out = recommend_interventions(False, 0.5, d_in=2.441,
                                      q_actual_mscfd=2000.0,
                                      q_crit_mscfd=900.0)
        assert all("velocity string" not in a["action"].lower()
                   for a in out["actions"])

    def test_actions_sorted_by_priority(self):
        for args in [(False, 0.5), (True, -0.4), (True, -0.8)]:
            out = recommend_interventions(*args, water_rate_bpd=40.0)
            priorities = [a["priority"] for a in out["actions"]]
            assert priorities == sorted(priorities)

    def test_every_action_has_cost_and_rationale(self):
        out = recommend_interventions(True, -0.5, water_rate_bpd=15.0)
        for a in out["actions"]:
            assert a.get("why")
            assert a.get("typical_cost")
