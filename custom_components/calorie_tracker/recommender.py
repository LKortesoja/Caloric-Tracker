"""Deterministic workout recommendation and load-management engine.

Implements the EWMA Acute:Chronic Workload Ratio (ACWR), ACSM-based
recovery spacing rules, polarized-training distribution checks, and a
hierarchical decision matrix. Pure Python with no Home Assistant
dependencies so the logic is fully unit testable.
"""
from __future__ import annotations

from dataclasses import dataclass

try:  # package context inside Home Assistant
    from . import calculator as calc
except ImportError:  # direct import in unit tests
    import calculator as calc

ACUTE_WINDOW_DAYS = 7
CHRONIC_WINDOW_DAYS = 28
COLD_START_MIN_DAYS = 14

ACWR_ELEVATED = 1.5
ACWR_DANGER = 2.0

# Session classification keywords (matched against lowercased activity type).
STRENGTH_KEYWORDS = ("strength", "weight", "resistance", "lifting")
MOBILITY_KEYWORDS = ("yoga", "stretch", "mobility", "pilates", "foam_roll")
CYCLING_KEYWORDS = ("cycling", "bike", "ride", "spin", "peloton")
HIGH_INTENSITY_KEYWORDS = ("hiit", "interval", "tabata", "sprint", "circuit")

CATEGORY_STRENGTH = "strength"
CATEGORY_MOBILITY = "mobility"
CATEGORY_CYCLING = "cycling"
CATEGORY_CARDIO = "cardio"

INTENSITY_HIGH = "high"
INTENSITY_LOW = "low"

HR_HIGH_INTENSITY_FRACTION = 0.80


def classify_activity(activity_type: str) -> str:
    """Bucket an activity into strength / mobility / cycling / cardio."""
    name = activity_type.lower()
    if any(keyword in name for keyword in STRENGTH_KEYWORDS):
        return CATEGORY_STRENGTH
    if any(keyword in name for keyword in MOBILITY_KEYWORDS):
        return CATEGORY_MOBILITY
    if any(keyword in name for keyword in CYCLING_KEYWORDS):
        return CATEGORY_CYCLING
    return CATEGORY_CARDIO


def is_high_intensity(
    activity_type: str,
    avg_hr: float | None = None,
    hr_max: float | None = None,
) -> bool:
    """High intensity when tagged HIIT/interval/tabata or avg HR > 80% HRmax."""
    name = activity_type.lower()
    if any(keyword in name for keyword in HIGH_INTENSITY_KEYWORDS):
        return True
    if avg_hr is not None and hr_max is not None and hr_max > 0:
        return avg_hr > HR_HIGH_INTENSITY_FRACTION * hr_max
    return False


def is_aerobic(category: str) -> bool:
    return category in (CATEGORY_CYCLING, CATEGORY_CARDIO)


@dataclass
class TrainingSnapshot:
    """Inputs the decision matrix needs, gathered by the coordinator."""

    daily_loads_28d: list[float]  # chronological net kcal per day, today last
    days_of_data: int
    yesterday_load: float
    consecutive_training_days: int
    strength_yesterday: bool
    mobility_sessions_7d: int
    cardio_sessions_14d: int
    high_intensity_cardio_14d: int
    cycling_sessions_14d: int
    total_sessions_14d: int
    strength_sessions_month: int
    day_of_month: int
    days_in_month: int
    monthly_distance: float
    monthly_distance_goal: float
    monthly_strength_goal: int
    weekly_rest_days_target: int
    polarization_threshold_pct: int


@dataclass
class Recommendation:
    """Engine output: the daily recommendation plus every derived signal."""

    primary: str
    reasoning: str
    acwr_ratio: float | None
    acute_ewma: float | None
    chronic_ewma: float | None
    high_intensity_ratio: float
    required_daily_pace: float
    days_of_data: int
    is_cold_start: bool
    mandatory_rest: bool
    strength_lockout: bool
    mobility_deficit: bool
    acute_fatigue: bool
    polarization_high_skew: bool
    strength_priority_high: bool


def evaluate(snapshot: TrainingSnapshot) -> Recommendation:
    """Run the hierarchical decision matrix over a training snapshot."""
    loads = snapshot.daily_loads_28d

    acute_ewma = calc.ewma(loads, calc.ewma_lambda(ACUTE_WINDOW_DAYS))
    chronic_ewma = calc.ewma(loads, calc.ewma_lambda(CHRONIC_WINDOW_DAYS))

    is_cold_start = snapshot.days_of_data < COLD_START_MIN_DAYS
    acwr_ratio: float | None = None
    if not is_cold_start and acute_ewma is not None and chronic_ewma:
        acwr_ratio = acute_ewma / chronic_ewma

    # Session-level 75th percentile trigger (nonzero training days only).
    nonzero_loads = [load for load in loads if load > 0]
    p75 = calc.percentile(nonzero_loads, 75)
    acute_fatigue = (
        p75 is not None
        and snapshot.yesterday_load > 0
        and snapshot.yesterday_load > p75
    )

    max_consecutive = 7 - snapshot.weekly_rest_days_target
    mandatory_rest = snapshot.consecutive_training_days >= max_consecutive

    strength_lockout = snapshot.strength_yesterday
    mobility_deficit = snapshot.mobility_sessions_7d < 2

    if snapshot.cardio_sessions_14d > 0:
        high_intensity_ratio = (
            snapshot.high_intensity_cardio_14d / snapshot.cardio_sessions_14d
        )
    else:
        high_intensity_ratio = 0.0
    polarization_high_skew = (
        high_intensity_ratio > snapshot.polarization_threshold_pct / 100
    )

    # Strength priority: behind < 50% of expected monthly pace while cycling
    # dominates recent training.
    expected_strength_by_now = snapshot.monthly_strength_goal * (
        snapshot.day_of_month / snapshot.days_in_month
    )
    cycling_share = (
        snapshot.cycling_sessions_14d / snapshot.total_sessions_14d
        if snapshot.total_sessions_14d > 0
        else 0.0
    )
    strength_priority_high = (
        snapshot.strength_sessions_month < 0.5 * expected_strength_by_now
        and cycling_share > 0.75
    )

    # Monthly distance pacing.
    days_remaining = max(1, snapshot.days_in_month - snapshot.day_of_month + 1)
    distance_deficit = max(0.0, snapshot.monthly_distance_goal - snapshot.monthly_distance)
    required_daily_pace = distance_deficit / days_remaining
    baseline_daily_pace = (
        snapshot.monthly_distance_goal / snapshot.days_in_month
        if snapshot.days_in_month
        else 0.0
    )

    # ------------------------------------------------------------------
    # Hierarchical decision matrix (injury prevention first).
    # ------------------------------------------------------------------
    acwr_danger = acwr_ratio is not None and acwr_ratio > ACWR_DANGER
    acwr_elevated = (
        acwr_ratio is not None and ACWR_ELEVATED < acwr_ratio <= ACWR_DANGER
    )

    if mandatory_rest or acwr_danger:
        primary = "Full Passive Rest Day"
        reasoning = (
            "Max consecutive training days reached, or ACWR indicates a "
            "dangerous load spike (>2.0). Tissue adaptation requires "
            "passive recovery."
        )
    elif acute_fatigue or acwr_elevated:
        primary = "Active Recovery (20 min Low Impact Ride) or Mobility Work"
        reasoning = (
            "Elevated load detected. Promote blood flow without generating "
            "central fatigue."
        )
    elif strength_priority_high and not strength_lockout:
        primary = "30 min Full Body / Upper Body Strength"
        reasoning = (
            "Concurrent training balance requires resistance work. "
            "ACWR is stable."
        )
    elif polarization_high_skew:
        primary = "45-60 min Zone 2 / Endurance Ride"
        reasoning = (
            "Training distribution is skewed heavily toward high intensity. "
            "Build aerobic base with steady-state, low-intensity volume."
        )
    else:
        if required_daily_pace > baseline_daily_pace:
            primary = "45 min Endurance Ride"
            reasoning = (
                "Behind monthly distance pace: "
                f"{required_daily_pace:.1f}/day needed to reach the goal."
            )
        else:
            primary = "30 min Climbs/Intervals or 20 min HIIT"
            reasoning = "On track for the monthly cycling goal; quality session."
        if mobility_deficit:
            primary += " + 10 min Post-Ride Stretch/Mobility"
            reasoning += " Fewer than 2 mobility sessions this week."

    return Recommendation(
        primary=primary,
        reasoning=reasoning,
        acwr_ratio=acwr_ratio,
        acute_ewma=acute_ewma,
        chronic_ewma=chronic_ewma,
        high_intensity_ratio=high_intensity_ratio,
        required_daily_pace=required_daily_pace,
        days_of_data=snapshot.days_of_data,
        is_cold_start=is_cold_start,
        mandatory_rest=mandatory_rest,
        strength_lockout=strength_lockout,
        mobility_deficit=mobility_deficit,
        acute_fatigue=acute_fatigue,
        polarization_high_skew=polarization_high_skew,
        strength_priority_high=strength_priority_high,
    )
