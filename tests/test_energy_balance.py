"""Unit tests for the pure energy-balance and nutrition math."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "custom_components" / "calorie_tracker")
)

import energy_balance as eb  # noqa: E402


# ---------------------------------------------------------------------------
# TEF
# ---------------------------------------------------------------------------


def test_tef_macronutrient_specific():
    # 100 g protein, 200 g carbs, 70 g fat
    result = eb.calculate_tef(100, 200, 70, 2500, macro_coverage=1.0)
    assert result.protein_kcal == pytest.approx(100 * 4 * 0.25)  # 100
    assert result.carbs_kcal == pytest.approx(200 * 4 * 0.075)  # 60
    assert result.fat_kcal == pytest.approx(70 * 9 * 0.02)  # 12.6
    assert result.tef_kcal == pytest.approx(172.6)
    assert result.estimated is False


def test_tef_flat_mode():
    result = eb.calculate_tef(100, 200, 70, 2500, 1.0, mode="flat_10_percent")
    assert result.tef_kcal == pytest.approx(250.0)
    assert result.estimated is False


def test_tef_fallback_on_sparse_macros():
    # Below 80% coverage -> flat 10%, flagged as estimated
    result = eb.calculate_tef(50, 100, 30, 2000, macro_coverage=0.79)
    assert result.tef_kcal == pytest.approx(200.0)
    assert result.estimated is True


def test_tef_coverage_at_threshold_uses_macros():
    result = eb.calculate_tef(50, 100, 30, 2000, macro_coverage=0.80)
    assert result.estimated is False


def test_no_double_counting_of_tef():
    """base_without_tef + actual TEF must not re-add the assumed share."""
    rmr, pal = 2000.0, 1.2
    base_with_implicit = rmr * pal  # 2400, includes ~10% assumed TEF
    base_without = eb.base_expenditure_without_tef(rmr, pal, 0.10)  # 2160
    assert base_without == pytest.approx(2160.0)
    actual_tef = 240.0  # if actual TEF equals the assumed share...
    assert base_without + actual_tef == pytest.approx(base_with_implicit)


# ---------------------------------------------------------------------------
# Energy balance and deficit bands
# ---------------------------------------------------------------------------


def test_energy_balance_signed():
    assert eb.calculate_energy_balance(2000, 2500) == -500
    assert eb.calculate_energy_balance(2800, 2500) == 300


@pytest.mark.parametrize(
    ("deficit", "expected"),
    [
        (-100, "surplus"),
        (0, "minimal_deficit"),
        (249, "minimal_deficit"),
        (250, "guideline_range"),
        (750, "guideline_range"),
        (751, "aggressive"),
        (1000, "aggressive"),
        (1001, "very_aggressive"),
    ],
)
def test_deficit_band_boundaries(deficit, expected):
    assert eb.classify_deficit(-deficit, incomplete_logging=False) == expected


def test_deficit_gated_by_incomplete_logging():
    assert eb.classify_deficit(-2000, incomplete_logging=True) == "insufficient_data"


def test_aggressive_flag():
    assert eb.is_aggressive_deficit("aggressive") is True
    assert eb.is_aggressive_deficit("very_aggressive") is True
    assert eb.is_aggressive_deficit("guideline_range") is False


# ---------------------------------------------------------------------------
# Protein target resolution
# ---------------------------------------------------------------------------


def test_protein_target_total_body_weight():
    target, basis, basis_weight = eb.resolve_protein_target(
        "total_body_weight", 100.0, 75.0, 1.4, 1.5, 100
    )
    assert target == pytest.approx(140.0)
    assert basis == "total_body_weight"
    assert basis_weight == 100.0


def test_protein_target_ffm():
    target, basis, basis_weight = eb.resolve_protein_target(
        "fat_free_mass", 100.0, 75.0, 1.4, 1.5, 100
    )
    assert target == pytest.approx(112.5)
    assert basis == "fat_free_mass"
    assert basis_weight == 75.0


def test_protein_target_ffm_fallback_to_tbw():
    target, basis, _ = eb.resolve_protein_target(
        "fat_free_mass", 100.0, None, 1.4, 1.5, 100
    )
    assert target == pytest.approx(140.0)
    assert basis == "total_body_weight"


def test_protein_target_absolute():
    target, basis, basis_weight = eb.resolve_protein_target(
        "absolute_grams", 100.0, 75.0, 1.4, 1.5, 110
    )
    assert target == 110
    assert basis == "absolute_grams"
    assert basis_weight is None


def test_protein_target_no_weight_falls_back_to_absolute():
    target, basis, _ = eb.resolve_protein_target(
        "total_body_weight", None, None, 1.4, 1.5, 100
    )
    assert target == 100
    assert basis == "absolute_grams"


# ---------------------------------------------------------------------------
# Protein adequacy and flags
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("protein", "target", "expected_band"),
    [
        (79, 100, "inadequate"),
        (80, 100, "below_target"),
        (99, 100, "below_target"),
        (100, 100, "at_target"),
        (120, 100, "at_target"),
        (121, 100, "above_target"),
    ],
)
def test_adequacy_bands(protein, target, expected_band):
    _, band, _ = eb.assess_protein_adequacy(protein, target, weight_kg=100.0)
    assert band == expected_band


def test_critical_low_protein_boundary():
    # 0.49 g/kg -> critical; 0.50 g/kg -> not critical
    _, band, critical = eb.assess_protein_adequacy(49, 140, weight_kg=100.0)
    assert critical is True
    assert band == "inadequate"  # critical forces inadequate
    _, _, critical = eb.assess_protein_adequacy(50, 140, weight_kg=100.0)
    assert critical is False


def test_high_protein_advisory_boundary():
    assert eb.is_high_protein_advisory(1.99) is False
    assert eb.is_high_protein_advisory(2.00) is True
    assert eb.is_high_protein_advisory(None) is False


def test_adequacy_division_by_zero_guards():
    pct, band, critical = eb.assess_protein_adequacy(100, None, weight_kg=100.0)
    assert pct is None and band == "unknown"
    pct, band, _ = eb.assess_protein_adequacy(100, 0, weight_kg=100.0)
    assert pct is None and band == "unknown"
    assert eb.protein_g_per_kg(100, None) is None
    assert eb.protein_g_per_kg(100, 0) is None


# ---------------------------------------------------------------------------
# Adaptive thermogenesis
# ---------------------------------------------------------------------------


def test_adaptive_thermogenesis_scaling():
    # 10% weight lost -> factor 1 - 0.05 = 0.95
    adjusted, factor = eb.apply_adaptive_thermogenesis(2000, 100.0, 90.0)
    assert factor == pytest.approx(0.95)
    assert adjusted == pytest.approx(1900.0)


def test_adaptive_thermogenesis_floor():
    # 50% weight lost would give 0.75 -> floored at 0.85
    _, factor = eb.apply_adaptive_thermogenesis(2000, 100.0, 50.0)
    assert factor == 0.85


def test_adaptive_thermogenesis_weight_gain_no_inflation():
    adjusted, factor = eb.apply_adaptive_thermogenesis(2000, 100.0, 110.0)
    assert factor == 1.0
    assert adjusted == 2000


def test_adaptive_thermogenesis_missing_data():
    adjusted, factor = eb.apply_adaptive_thermogenesis(2000, None, 90.0)
    assert factor == 1.0 and adjusted == 2000
    adjusted, factor = eb.apply_adaptive_thermogenesis(2000, 0, 90.0)
    assert factor == 1.0 and adjusted == 2000


# ---------------------------------------------------------------------------
# Incomplete logging
# ---------------------------------------------------------------------------


def test_incomplete_low_intake_after_cutoff():
    assert eb.detect_incomplete_logging(20, 400, 20, False, True) is True
    assert eb.detect_incomplete_logging(19, 400, 20, False, True) is False
    assert eb.detect_incomplete_logging(20, 500, 20, False, True) is False


def test_incomplete_when_source_stale():
    assert eb.detect_incomplete_logging(12, 1500, 20, True, True) is True


def test_incomplete_when_macros_missing():
    assert eb.detect_incomplete_logging(12, 1500, 20, False, False) is True


# ---------------------------------------------------------------------------
# Meal inference and protein correction
# ---------------------------------------------------------------------------


def test_meal_inference_buckets():
    assert eb.infer_meal_from_hour(7) == "breakfast"
    assert eb.infer_meal_from_hour(9) == "breakfast"
    assert eb.infer_meal_from_hour(10) == "lunch"
    assert eb.infer_meal_from_hour(14) == "lunch"
    assert eb.infer_meal_from_hour(15) == "dinner"
    assert eb.infer_meal_from_hour(20) == "dinner"
    assert eb.infer_meal_from_hour(21) == "snack"
    assert eb.infer_meal_from_hour(23) == "snack"


def test_protein_correction_never_replaces_raw():
    raw = 100.0
    corrected = eb.apply_protein_correction(raw, 10)
    assert corrected == pytest.approx(110.0)
    assert raw == 100.0  # untouched
    assert eb.apply_protein_correction(raw, 0) == 100.0
