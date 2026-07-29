"""Pure calculation helpers for the Calorie Tracker integration.

Every function in this module is side-effect free and has no Home Assistant
dependencies, so the metabolic math can be unit tested in isolation.
All formulas follow the exact equations specified in the project spec.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

LBS_TO_KG = 0.453592
STONES_TO_KG = 6.35029
MINUTES_PER_DAY = 1440

CORRECTION_FACTOR_MIN = 0.50
CORRECTION_FACTOR_MAX = 1.00

_LB_UNITS = {"lb", "lbs", "pound", "pounds"}
_STONE_UNITS = {"st", "stone", "stones"}
_KG_UNITS = {"kg", "kilogram", "kilograms"}


def calculate_age(date_of_birth: date, today: date) -> int:
    """Return age in completed years as of *today*."""
    years = today.year - date_of_birth.year
    if (today.month, today.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return years


def mifflin_st_jeor(weight_kg: float, height_cm: float, age_years: float, sex: str) -> float:
    """Mifflin-St Jeor (1990) RMR in kcal/day."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age_years
    return base + 5 if sex == "male" else base - 161


def harris_benedict(weight_kg: float, height_cm: float, age_years: float, sex: str) -> float:
    """Harris-Benedict (1919) RMR in kcal/day."""
    if sex == "male":
        return 13.7516 * weight_kg + 5.0033 * height_cm - 6.7550 * age_years + 66.4730
    return 9.5634 * weight_kg + 1.8496 * height_cm - 4.6756 * age_years + 655.0955


def cunningham(fat_free_mass_kg: float) -> float:
    """Cunningham (1991) RMR in kcal/day from fat-free mass."""
    return 22 * fat_free_mass_kg + 500


def fat_free_mass(weight_kg: float, body_fat_percentage: float) -> float:
    """Fat-free mass in kg from weight and body fat percentage (0-100 scale)."""
    return weight_kg * (1 - body_fat_percentage / 100)


def resting_component_kcal(rmr_kcal_per_day: float, duration_minutes: float) -> float:
    """RMR calories that would have been burned anyway during the session."""
    return (rmr_kcal_per_day / MINUTES_PER_DAY) * duration_minutes


def net_exercise_kcal(
    gross_kcal: float,
    correction_factor: float,
    rmr_kcal_per_day: float,
    duration_minutes: float,
) -> float:
    """Net exercise calories from a device-reported gross value.

    The correction factor is applied before subtracting the resting
    component; negative results are clamped to 0.
    """
    corrected_gross = gross_kcal * correction_factor
    net = corrected_gross - resting_component_kcal(rmr_kcal_per_day, duration_minutes)
    return max(0.0, net)


def met_net_kcal(met_value: float, weight_kg: float, duration_minutes: float) -> float:
    """Net exercise calories from a MET value (net METs = MET - 1)."""
    net = (met_value - 1) * weight_kg * (duration_minutes / 60)
    return max(0.0, net)


def met_gross_kcal(met_value: float, weight_kg: float, duration_minutes: float) -> float:
    """Gross exercise calories from a MET value (for display alongside net)."""
    return max(0.0, met_value * weight_kg * (duration_minutes / 60))


def is_mass_unit(unit: str | None) -> bool:
    """True when the unit denotes a mass (kg/lb/stones) rather than a percent.

    Used to detect smart scales that report fat *mass* instead of body fat %.
    """
    if unit is None:
        return False
    normalized = unit.strip().lower().rstrip(".")
    return normalized in _LB_UNITS | _STONE_UNITS | _KG_UNITS


def fat_mass_to_percent(fat_mass_kg: float, weight_kg: float) -> float | None:
    """Convert an absolute fat mass reading to a body fat percentage."""
    if weight_kg <= 0:
        return None
    return (fat_mass_kg / weight_kg) * 100


def convert_weight_to_kg(value: float, unit: str | None) -> float:
    """Convert a weight reading to kg based on its unit of measurement.

    Unknown or missing units are assumed to already be kg.
    """
    normalized = (unit or "kg").strip().lower().rstrip(".")
    if normalized in _LB_UNITS:
        return value * LBS_TO_KG
    if normalized in _STONE_UNITS:
        return value * STONES_TO_KG
    return value


def clamp_correction_factor(factor: float) -> float:
    """Clamp the exercise correction factor to the allowed 0.50-1.00 range."""
    return min(max(factor, CORRECTION_FACTOR_MIN), CORRECTION_FACTOR_MAX)


def rolling_average_weight(
    readings: list[tuple[datetime, float]],
    now: datetime,
    window_days: int = 7,
) -> float | None:
    """Mean of weight readings within the trailing window, or None if empty."""
    cutoff = now - timedelta(days=window_days)
    values = [weight for ts, weight in readings if ts >= cutoff]
    if not values:
        return None
    return sum(values) / len(values)


def rolling_daily_average(
    history: dict[str, float],
    today_value: float,
    today: date,
    window_days: int,
) -> tuple[float, int]:
    """Average a per-day metric over the trailing window, including today.

    *history* maps ISO dates to completed-day values. Only recorded days
    count toward the divisor, so a fresh install is not dragged down by
    days that predate the integration. Returns (average, days_of_data).
    """
    cutoff = today - timedelta(days=window_days - 1)
    values = [
        value
        for day_iso, value in history.items()
        if cutoff <= date.fromisoformat(day_iso) < today
    ]
    values.append(today_value)
    return sum(values) / len(values), len(values)


def is_weight_stale(
    last_measurement: datetime | None,
    now: datetime,
    threshold_days: int,
) -> bool:
    """True when the scale has not reported within the threshold."""
    if last_measurement is None:
        return True
    return (now - last_measurement) > timedelta(days=threshold_days)


def body_mass_index(weight_kg: float, height_cm: float) -> float:
    """BMI in kg/m²."""
    height_m = height_cm / 100
    return weight_kg / (height_m * height_m)


def is_valid_body_fat(body_fat_percentage: float) -> bool:
    """Body fat readings outside 1-60% are treated as sensor glitches."""
    return 1.0 <= body_fat_percentage <= 60.0
