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
# Underfueling tier (nutrition integration)
# ---------------------------------------------------------------------------


def fueled(**overrides) -> TrainingSnapshot:
    """Snapshot with nutrition data present and no underfueling by default."""
    defaults = dict(
        incomplete_logging=False,
        nutrition_connected=True,
        rolling_7d_deficit=-400.0,
        below_floor_days_7d=0,
        yesterday_load=100.0,
    )
    defaults.update(overrides)
    return make_snapshot(**defaults)


def test_underfueling_from_sustained_deficit():
    rec = evaluate(fueled(rolling_7d_deficit=-1200.0))
    assert rec.underfueling is True
    assert rec.primary == "Light Activity Only — Underfueling Detected"


def test_underfueling_from_below_floor_days():
    rec = evaluate(fueled(below_floor_days_7d=3))
    assert rec.underfueling is True
    assert rec.primary == "Light Activity Only — Underfueling Detected"


def test_underfueling_deficit_boundary():
    # Strictly below -1000 triggers; exactly -1000 does not.
    assert evaluate(fueled(rolling_7d_deficit=-1000.0)).underfueling is False
    assert evaluate(fueled(rolling_7d_deficit=-1000.1)).underfueling is True


def test_underfueling_below_floor_boundary():
    assert evaluate(fueled(below_floor_days_7d=2)).underfueling is False
    assert evaluate(fueled(below_floor_days_7d=3)).underfueling is True


def test_underfueling_suppressed_when_logging_incomplete():
    """A half-logged week must never be read as starvation."""
    rec = evaluate(
        fueled(rolling_7d_deficit=-2000.0, below_floor_days_7d=7,
               incomplete_logging=True)
    )
    assert rec.underfueling is False
    assert "Underfueling" not in rec.primary


def test_underfueling_without_nutrition_data():
    rec = evaluate(make_snapshot())  # defaults: no intake data at all
    assert rec.underfueling is False


def test_mandatory_rest_outranks_underfueling():
    rec = evaluate(fueled(rolling_7d_deficit=-2000.0, consecutive_training_days=6))
    assert rec.underfueling is True  # still reported as a flag
    assert rec.primary == "Full Passive Rest Day"


def test_acwr_danger_outranks_underfueling():
    loads = [50.0] * 24 + [800.0] * 4
    rec = evaluate(fueled(rolling_7d_deficit=-2000.0, daily_loads_28d=loads))
    assert rec.acwr_ratio > 2.0
    assert rec.primary == "Full Passive Rest Day"


def test_acute_fatigue_outranks_underfueling():
    loads = [100.0] * 27 + [0.0]
    rec = evaluate(
        fueled(rolling_7d_deficit=-2000.0, daily_loads_28d=loads,
               yesterday_load=500.0)
    )
    assert "Active Recovery" in rec.primary


def test_underfueling_outranks_strength_priority():
    rec = evaluate(
        fueled(
            rolling_7d_deficit=-1500.0,
            strength_sessions_month=1,
            cycling_sessions_14d=10,
            total_sessions_14d=12,
        )
    )
    assert rec.strength_priority_high is True  # condition still met
    assert rec.primary == "Light Activity Only — Underfueling Detected"


def test_underfueling_outranks_polarization():
    rec = evaluate(
        fueled(
            rolling_7d_deficit=-1500.0,
            high_intensity_cardio_14d=5,
            cardio_sessions_14d=10,
        )
    )
    assert rec.polarization_high_skew is True
    assert rec.primary == "Light Activity Only — Underfueling Detected"


# ---------------------------------------------------------------------------
# Secondary nutrition notes
# ---------------------------------------------------------------------------


def test_protein_note_only_on_strength_days():
    strength = fueled(
        protein_inadequate=True,
        strength_sessions_month=1,
        cycling_sessions_14d=10,
        total_sessions_14d=12,
    )
    rec = evaluate(strength)
    assert "Strength" in rec.primary
    assert any("Protein intake is below target" in n for n in rec.nutrition_notes)

    # Same protein deficit on a non-strength day: no resistance-training note.
    rec = evaluate(fueled(protein_inadequate=True))
    assert not any("resistance training" in n for n in rec.nutrition_notes)


def test_surplus_note_only_against_weight_loss_goal():
    rec = evaluate(fueled(energy_surplus_kcal=350.0, weight_goal_mode="loss"))
    assert any("surplus of 350 kcal" in n for n in rec.nutrition_notes)

    rec = evaluate(fueled(energy_surplus_kcal=350.0, weight_goal_mode="gain"))
    assert not any("surplus" in n for n in rec.nutrition_notes)


def test_note_when_nutrition_source_unavailable():
    rec = evaluate(fueled(nutrition_connected=False))
    assert any("Nutrition data unavailable" in n for n in rec.nutrition_notes)


def test_no_notes_when_everything_is_fine():
    assert evaluate(fueled()).nutrition_notes == ()


def test_engine_never_prescribes_an_intake_amount():
    """Guidance is status-only: no kcal/gram intake instructions."""
    snapshots = [
        fueled(rolling_7d_deficit=-1500.0),
        fueled(protein_inadequate=True, strength_sessions_month=1,
               cycling_sessions_14d=10, total_sessions_14d=12),
        fueled(energy_surplus_kcal=350.0, weight_goal_mode="loss"),
    ]
    for snapshot in snapshots:
        rec = evaluate(snapshot)
        text = " ".join((rec.primary, rec.reasoning, *rec.nutrition_notes)).lower()
        for phrase in ("eat ", "consume ", "you should eat", "increase to"):
            assert phrase not in text


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
