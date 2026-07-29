"""Unit tests for the pure calculation helpers.

These tests import calculator.py directly (it has no Home Assistant
dependencies), so they run with plain pytest.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "custom_components" / "calorie_tracker")
)

import calculator as calc  # noqa: E402


# ---------------------------------------------------------------------------
# Age
# ---------------------------------------------------------------------------


def test_age_birthday_passed():
    assert calc.calculate_age(date(1990, 1, 15), date(2026, 7, 28)) == 36


def test_age_birthday_not_yet():
    assert calc.calculate_age(date(1990, 12, 1), date(2026, 7, 28)) == 35


def test_age_on_birthday():
    assert calc.calculate_age(date(1990, 7, 28), date(2026, 7, 28)) == 36


# ---------------------------------------------------------------------------
# RMR equations
# ---------------------------------------------------------------------------


def test_mifflin_st_jeor_male():
    # 10*80 + 6.25*180 - 5*36 + 5 = 800 + 1125 - 180 + 5 = 1750
    assert calc.mifflin_st_jeor(80, 180, 36, "male") == pytest.approx(1750)


def test_mifflin_st_jeor_female():
    # 10*65 + 6.25*165 - 5*30 - 161 = 650 + 1031.25 - 150 - 161 = 1370.25
    assert calc.mifflin_st_jeor(65, 165, 30, "female") == pytest.approx(1370.25)


def test_harris_benedict_male():
    expected = 13.7516 * 80 + 5.0033 * 180 - 6.7550 * 36 + 66.4730
    assert calc.harris_benedict(80, 180, 36, "male") == pytest.approx(expected)


def test_harris_benedict_female():
    expected = 9.5634 * 65 + 1.8496 * 165 - 4.6756 * 30 + 655.0955
    assert calc.harris_benedict(65, 165, 30, "female") == pytest.approx(expected)


def test_cunningham():
    assert calc.cunningham(60) == pytest.approx(22 * 60 + 500)  # 1820


def test_fat_free_mass():
    assert calc.fat_free_mass(80, 20) == pytest.approx(64.0)


def test_fat_free_mass_zero_body_fat():
    assert calc.fat_free_mass(80, 0) == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Net exercise calories (device gross -> net)
# ---------------------------------------------------------------------------


def test_resting_component():
    # RMR 1440 kcal/day -> exactly 1 kcal/min
    assert calc.resting_component_kcal(1440, 45) == pytest.approx(45)


def test_net_exercise_no_correction():
    # 400 gross, RMR 1440 (1 kcal/min), 60 min -> 400 - 60 = 340
    assert calc.net_exercise_kcal(400, 1.0, 1440, 60) == pytest.approx(340)


def test_net_exercise_with_correction():
    # Correction applied BEFORE subtracting resting component:
    # 400 * 0.8 = 320; 320 - 60 = 260
    assert calc.net_exercise_kcal(400, 0.8, 1440, 60) == pytest.approx(260)


def test_net_exercise_negative_clamped_to_zero():
    # 30 gross * 0.5 = 15; resting for 60 min = 60 -> negative -> clamp
    assert calc.net_exercise_kcal(30, 0.5, 1440, 60) == 0.0


def test_net_exercise_zero_duration():
    # Zero duration: no resting component subtracted
    assert calc.net_exercise_kcal(100, 1.0, 1800, 0) == pytest.approx(100)


# ---------------------------------------------------------------------------
# MET-based calculations
# ---------------------------------------------------------------------------


def test_met_net_kcal():
    # (8 - 1) * 80 kg * (30/60 h) = 280
    assert calc.met_net_kcal(8.0, 80, 30) == pytest.approx(280)


def test_met_net_kcal_uses_net_mets():
    # MET of exactly 1 (resting) burns nothing net
    assert calc.met_net_kcal(1.0, 80, 60) == 0.0


def test_met_net_kcal_zero_duration():
    assert calc.met_net_kcal(8.0, 80, 0) == 0.0


def test_met_gross_kcal():
    # 8 * 80 * 0.5 = 320
    assert calc.met_gross_kcal(8.0, 80, 30) == pytest.approx(320)


# ---------------------------------------------------------------------------
# Correction factor
# ---------------------------------------------------------------------------


def test_correction_factor_clamped_low():
    assert calc.clamp_correction_factor(0.3) == 0.50


def test_correction_factor_clamped_high():
    assert calc.clamp_correction_factor(1.5) == 1.00


def test_correction_factor_in_range():
    assert calc.clamp_correction_factor(0.85) == 0.85


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------


def test_lbs_to_kg():
    assert calc.convert_weight_to_kg(180, "lb") == pytest.approx(81.64656)
    assert calc.convert_weight_to_kg(180, "lbs") == pytest.approx(81.64656)


def test_stones_to_kg():
    assert calc.convert_weight_to_kg(12, "st") == pytest.approx(76.20348)
    assert calc.convert_weight_to_kg(12, "stones") == pytest.approx(76.20348)


def test_kg_passthrough():
    assert calc.convert_weight_to_kg(82.5, "kg") == pytest.approx(82.5)


def test_unknown_unit_assumed_kg():
    assert calc.convert_weight_to_kg(82.5, None) == pytest.approx(82.5)
    assert calc.convert_weight_to_kg(82.5, "") == pytest.approx(82.5)


def test_unit_case_insensitive():
    assert calc.convert_weight_to_kg(180, "LBS") == pytest.approx(81.64656)


# ---------------------------------------------------------------------------
# Weight smoothing
# ---------------------------------------------------------------------------


def test_rolling_average_within_window():
    now = datetime(2026, 7, 28, 8, 0)
    readings = [
        (now - timedelta(days=2), 80.0),
        (now - timedelta(days=1), 81.0),
        (now, 82.0),
    ]
    assert calc.rolling_average_weight(readings, now, 7) == pytest.approx(81.0)


def test_rolling_average_excludes_old_readings():
    now = datetime(2026, 7, 28, 8, 0)
    readings = [
        (now - timedelta(days=10), 100.0),  # outside window, ignored
        (now - timedelta(days=1), 80.0),
        (now, 82.0),
    ]
    assert calc.rolling_average_weight(readings, now, 7) == pytest.approx(81.0)


def test_rolling_average_empty():
    now = datetime(2026, 7, 28, 8, 0)
    assert calc.rolling_average_weight([], now, 7) is None
    old = [(now - timedelta(days=30), 80.0)]
    assert calc.rolling_average_weight(old, now, 7) is None


# ---------------------------------------------------------------------------
# Stale data detection
# ---------------------------------------------------------------------------


def test_stale_when_never_measured():
    assert calc.is_weight_stale(None, datetime(2026, 7, 28), 7) is True


def test_not_stale_within_threshold():
    now = datetime(2026, 7, 28)
    assert calc.is_weight_stale(now - timedelta(days=6), now, 7) is False


def test_stale_beyond_threshold():
    now = datetime(2026, 7, 28)
    assert calc.is_weight_stale(now - timedelta(days=8), now, 7) is True


def test_exactly_at_threshold_not_stale():
    now = datetime(2026, 7, 28)
    assert calc.is_weight_stale(now - timedelta(days=7), now, 7) is False


# ---------------------------------------------------------------------------
# BMI and body fat validation
# ---------------------------------------------------------------------------


def test_bmi():
    assert calc.body_mass_index(80, 180) == pytest.approx(24.69, abs=0.01)


def test_body_fat_validation():
    assert calc.is_valid_body_fat(20.0) is True
    assert calc.is_valid_body_fat(1.0) is True
    assert calc.is_valid_body_fat(60.0) is True
    assert calc.is_valid_body_fat(0.5) is False
    assert calc.is_valid_body_fat(75.0) is False
    assert calc.is_valid_body_fat(-5.0) is False


# ---------------------------------------------------------------------------
# End-to-end TDEE composition
# ---------------------------------------------------------------------------


def test_tdee_composition():
    """base = RMR * PAL; TDEE = base + sum(net exercise)."""
    rmr = calc.mifflin_st_jeor(80, 180, 36, "male")  # 1750
    base = rmr * 1.2  # sedentary -> 2100
    peloton_net = calc.net_exercise_kcal(500, 0.85, rmr, 45)
    manual_net = calc.met_net_kcal(7.0, 80, 30)  # jogging_5mph -> 240
    tdee = base + peloton_net + manual_net

    expected_peloton = 500 * 0.85 - (1750 / 1440) * 45
    assert peloton_net == pytest.approx(expected_peloton)
    assert manual_net == pytest.approx(240)
    assert tdee == pytest.approx(2100 + expected_peloton + 240)


def test_daily_budget_offsets():
    tdee = 2500
    assert tdee - 500 == 2000  # weight loss
    assert tdee + 300 == 2800  # muscle gain
