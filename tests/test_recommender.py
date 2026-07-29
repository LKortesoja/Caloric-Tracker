"""Unit tests for the workout recommendation engine.

recommender.py and calculator.py are pure Python, so these run with
plain pytest and no Home Assistant installation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "custom_components" / "calorie_tracker")
)

import calculator as calc  # noqa: E402
import recommender  # noqa: E402
from recommender import TrainingSnapshot, evaluate  # noqa: E402


def make_snapshot(**overrides) -> TrainingSnapshot:
    """A quiet, healthy baseline snapshot; tests override what they probe."""
    defaults = dict(
        daily_loads_28d=[200.0] * 28,
        days_of_data=28,
        yesterday_load=200.0,
        consecutive_training_days=2,
        strength_yesterday=False,
        mobility_sessions_7d=2,
        cardio_sessions_14d=10,
        high_intensity_cardio_14d=2,
        cycling_sessions_14d=6,
        total_sessions_14d=12,
        strength_sessions_month=6,
        day_of_month=15,
        days_in_month=30,
        monthly_distance=60.0,
        monthly_distance_goal=100.0,
        monthly_strength_goal=12,
        weekly_rest_days_target=1,
        polarization_threshold_pct=25,
    )
    defaults.update(overrides)
    return TrainingSnapshot(**defaults)


# ---------------------------------------------------------------------------
# EWMA math
# ---------------------------------------------------------------------------


def test_ewma_lambda_values():
    assert calc.ewma_lambda(7) == pytest.approx(0.25)
    assert calc.ewma_lambda(28) == pytest.approx(2 / 29)


def test_ewma_matches_manual_recursion():
    loads = [100.0, 200.0, 300.0]
    lam = 0.25
    expected = 100.0
    expected = 200.0 * lam + expected * (1 - lam)  # 125.0
    expected = 300.0 * lam + expected * (1 - lam)  # 168.75
    assert calc.ewma(loads, lam) == pytest.approx(expected)
    assert calc.ewma(loads, lam) == pytest.approx(168.75)


def test_ewma_empty_series():
    assert calc.ewma([], 0.25) is None


def test_ewma_constant_load_converges_to_load():
    assert calc.ewma([500.0] * 60, calc.ewma_lambda(7)) == pytest.approx(500.0)


def test_acwr_steady_training_near_one():
    rec = evaluate(make_snapshot(daily_loads_28d=[300.0] * 28))
    assert rec.acwr_ratio == pytest.approx(1.0, abs=0.05)


def test_acwr_spike_detected():
    # Quiet month then three huge days: acute EWMA reacts faster than chronic.
    loads = [100.0] * 25 + [900.0, 900.0, 900.0]
    rec = evaluate(make_snapshot(daily_loads_28d=loads, yesterday_load=100.0))
    assert rec.acwr_ratio is not None
    assert rec.acwr_ratio > 1.5


# ---------------------------------------------------------------------------
# Percentile
# ---------------------------------------------------------------------------


def test_percentile_linear_interpolation():
    values = [1.0, 2.0, 3.0, 4.0]
    # rank = 0.75 * 3 = 2.25 -> 3 + 0.25*(4-3) = 3.25
    assert calc.percentile(values, 75) == pytest.approx(3.25)


def test_percentile_edges():
    assert calc.percentile([], 75) is None
    assert calc.percentile([42.0], 75) == 42.0
    assert calc.percentile([1.0, 2.0, 3.0], 0) == 1.0
    assert calc.percentile([1.0, 2.0, 3.0], 100) == 3.0


# ---------------------------------------------------------------------------
# Cold-start suppression
# ---------------------------------------------------------------------------


def test_cold_start_suppresses_acwr():
    rec = evaluate(make_snapshot(days_of_data=13))
    assert rec.is_cold_start is True
    assert rec.acwr_ratio is None


def test_cold_start_still_uses_percentile_trigger():
    # 27 modest days then a monster day yesterday: p75 trigger must still fire.
    loads = [100.0] * 27 + [0.0]
    rec = evaluate(
        make_snapshot(
            daily_loads_28d=loads, days_of_data=10, yesterday_load=800.0
        )
    )
    assert rec.is_cold_start is True
    assert rec.acute_fatigue is True
    assert "Active Recovery" in rec.primary


def test_fourteen_days_enables_acwr():
    rec = evaluate(make_snapshot(days_of_data=14))
    assert rec.is_cold_start is False
    assert rec.acwr_ratio is not None


# ---------------------------------------------------------------------------
# Decision matrix priorities
# ---------------------------------------------------------------------------


def test_priority_1_mandatory_rest_consecutive_days():
    # 7 - 1 rest day = 6 max consecutive training days
    rec = evaluate(make_snapshot(consecutive_training_days=6))
    assert rec.mandatory_rest is True
    assert rec.primary == "Full Passive Rest Day"


def test_priority_1_acwr_danger_zone():
    loads = [50.0] * 24 + [800.0] * 4
    rec = evaluate(make_snapshot(daily_loads_28d=loads, yesterday_load=50.0))
    assert rec.acwr_ratio is not None and rec.acwr_ratio > 2.0
    assert rec.primary == "Full Passive Rest Day"


def test_priority_1_beats_priority_2():
    rec = evaluate(
        make_snapshot(consecutive_training_days=6, yesterday_load=1000.0)
    )
    assert rec.primary == "Full Passive Rest Day"


def test_priority_2_acute_fatigue_from_percentile():
    loads = [100.0] * 27 + [0.0]
    rec = evaluate(make_snapshot(daily_loads_28d=loads, yesterday_load=500.0))
    assert rec.acute_fatigue is True
    assert "Active Recovery" in rec.primary


def test_priority_3_strength_priority():
    rec = evaluate(
        make_snapshot(
            strength_sessions_month=1,  # far behind 12/month pace at day 15
            cycling_sessions_14d=10,
            total_sessions_14d=12,
            yesterday_load=100.0,  # below p75, no fatigue
        )
    )
    assert rec.strength_priority_high is True
    assert rec.primary == "30 min Full Body / Upper Body Strength"


def test_strength_lockout_blocks_consecutive_strength_days():
    rec = evaluate(
        make_snapshot(
            strength_sessions_month=1,
            cycling_sessions_14d=10,
            total_sessions_14d=12,
            yesterday_load=100.0,
            strength_yesterday=True,
        )
    )
    assert rec.strength_lockout is True
    assert rec.primary != "30 min Full Body / Upper Body Strength"


def test_priority_4_polarization_high_skew():
    rec = evaluate(
        make_snapshot(
            high_intensity_cardio_14d=5,
            cardio_sessions_14d=10,  # 50% > 25% threshold
            yesterday_load=100.0,
        )
    )
    assert rec.polarization_high_skew is True
    assert rec.primary == "45-60 min Zone 2 / Endurance Ride"


def test_priority_5_behind_pace_endurance_ride():
    rec = evaluate(
        make_snapshot(
            monthly_distance=10.0,  # far behind 100 goal at day 15
            yesterday_load=100.0,
        )
    )
    assert rec.primary.startswith("45 min Endurance Ride")
    # (100 - 10) / 16 remaining days = 5.625/day
    assert rec.required_daily_pace == pytest.approx(90 / 16)


def test_priority_5_on_track_quality_session():
    rec = evaluate(
        make_snapshot(monthly_distance=60.0, yesterday_load=100.0)
    )
    assert rec.primary.startswith("30 min Climbs/Intervals or 20 min HIIT")


def test_mobility_deficit_appends_stretch():
    rec = evaluate(
        make_snapshot(
            monthly_distance=60.0, yesterday_load=100.0, mobility_sessions_7d=1
        )
    )
    assert rec.mobility_deficit is True
    assert "Post-Ride Stretch/Mobility" in rec.primary


# ---------------------------------------------------------------------------
# Session classification
# ---------------------------------------------------------------------------


def test_classify_activity_categories():
    assert recommender.classify_activity("weight_training_moderate") == "strength"
    assert recommender.classify_activity("yoga") == "mobility"
    assert recommender.classify_activity("cycling_moderate_12mph") == "cycling"
    assert recommender.classify_activity("Bike Bootcamp") == "cycling"
    assert recommender.classify_activity("running_6mph") == "cardio"


def test_high_intensity_by_keyword():
    assert recommender.is_high_intensity("hiit_circuit") is True
    assert recommender.is_high_intensity("Tabata Ride") is True
    assert recommender.is_high_intensity("cycling_moderate_12mph") is False


def test_high_intensity_by_heart_rate():
    hr_max = 220 - 36  # 184; 80% = 147.2
    assert recommender.is_high_intensity("cycling", avg_hr=150, hr_max=hr_max) is True
    assert recommender.is_high_intensity("cycling", avg_hr=140, hr_max=hr_max) is False
    assert recommender.is_high_intensity("cycling", avg_hr=None, hr_max=hr_max) is False


def test_polarization_ratio_no_cardio_sessions():
    rec = evaluate(
        make_snapshot(cardio_sessions_14d=0, high_intensity_cardio_14d=0)
    )
    assert rec.high_intensity_ratio == 0.0
    assert rec.polarization_high_skew is False
