"""Pure nutrition and energy-balance calculations.

Zero Home Assistant dependencies so everything here is unit testable.
All formulas follow the Nutrition Intake & Energy Balance spec.
"""
from __future__ import annotations

from dataclasses import dataclass

TEF_PROTEIN_COEFFICIENT = 0.25
TEF_CARB_COEFFICIENT = 0.075
TEF_FAT_COEFFICIENT = 0.02
KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_CARB = 4
KCAL_PER_G_FAT = 9
TEF_FLAT_FRACTION = 0.10
TEF_MACRO_COVERAGE_MIN = 0.80

DEFICIT_MINIMAL_MAX = 249
DEFICIT_GUIDELINE_MAX = 750
DEFICIT_AGGRESSIVE_MAX = 1000

PROTEIN_CRITICAL_LOW_G_PER_KG = 0.5
PROTEIN_HIGH_ADVISORY_G_PER_KG = 2.0

ADAPTIVE_THERMO_FLOOR = 0.85
INCOMPLETE_INTAKE_THRESHOLD_KCAL = 500


@dataclass(frozen=True)
class TefResult:
    tef_kcal: float
    estimated: bool  # True when macro data was too sparse and flat 10% was used
    protein_kcal: float
    carbs_kcal: float
    fat_kcal: float


def calculate_tef(
    protein_g: float,
    carbs_g: float,
    fat_g: float,
    total_intake_kcal: float,
    macro_coverage: float,
    mode: str = "macronutrient_specific",
) -> TefResult:
    """Thermic effect of food for the day.

    *macro_coverage* is the fraction of the day's calories coming from
    entries whose macros are all known. Below 80% coverage the
    macronutrient-specific mode falls back to a flat 10% of intake and
    flags the result as estimated.
    """
    if mode == "flat_10_percent" or macro_coverage < TEF_MACRO_COVERAGE_MIN:
        return TefResult(
            tef_kcal=total_intake_kcal * TEF_FLAT_FRACTION,
            estimated=mode != "flat_10_percent",
            protein_kcal=0.0,
            carbs_kcal=0.0,
            fat_kcal=0.0,
        )
    protein_kcal = protein_g * KCAL_PER_G_PROTEIN * TEF_PROTEIN_COEFFICIENT
    carbs_kcal = carbs_g * KCAL_PER_G_CARB * TEF_CARB_COEFFICIENT
    fat_kcal = fat_g * KCAL_PER_G_FAT * TEF_FAT_COEFFICIENT
    return TefResult(
        tef_kcal=protein_kcal + carbs_kcal + fat_kcal,
        estimated=False,
        protein_kcal=protein_kcal,
        carbs_kcal=carbs_kcal,
        fat_kcal=fat_kcal,
    )


def base_expenditure_without_tef(
    rmr: float, pal_factor: float, assumed_tef_fraction: float
) -> float:
    """RMR x PAL with its implicit TEF share removed.

    The PAL multiplier already bakes in ~10% TEF. When TEF is computed
    explicitly from logged intake, remove the assumed component first so
    TDEE = (RMR x PAL - assumed TEF) + actual TEF + exercise does not
    double-count: NEAT = RMR*(PAL-1) - assumed_tef_component.
    """
    return rmr * pal_factor * (1 - assumed_tef_fraction)


def calculate_energy_balance(total_intake_kcal: float, tdee_kcal: float) -> float:
    """Signed energy balance: positive = surplus, negative = deficit."""
    return total_intake_kcal - tdee_kcal


def classify_deficit(energy_balance_kcal: float, incomplete_logging: bool) -> str:
    """Deficit band per the spec table; gated on data completeness."""
    if incomplete_logging:
        return "insufficient_data"
    deficit = -energy_balance_kcal
    if deficit < 0:
        return "surplus"
    if deficit <= DEFICIT_MINIMAL_MAX:
        return "minimal_deficit"
    if deficit <= DEFICIT_GUIDELINE_MAX:
        return "guideline_range"
    if deficit <= DEFICIT_AGGRESSIVE_MAX:
        return "aggressive"
    return "very_aggressive"


def is_aggressive_deficit(classification: str) -> bool:
    return classification in ("aggressive", "very_aggressive")


def resolve_protein_target(
    basis: str,
    weight_kg: float | None,
    fat_free_mass_kg: float | None,
    g_per_kg: float,
    g_per_kg_ffm: float,
    absolute_g: float,
) -> tuple[float | None, str, float | None]:
    """Return (target_g, basis_used, basis_weight_kg).

    The FFM basis falls back to total body weight when no body
    composition data is available; total-body-weight falls back to the
    absolute target when no weight is known.
    """
    if basis == "absolute_grams":
        return absolute_g, "absolute_grams", None
    if basis == "fat_free_mass":
        if fat_free_mass_kg is not None and fat_free_mass_kg > 0:
            return fat_free_mass_kg * g_per_kg_ffm, "fat_free_mass", fat_free_mass_kg
        basis = "total_body_weight"  # fall through
    if weight_kg is not None and weight_kg > 0:
        return weight_kg * g_per_kg, "total_body_weight", weight_kg
    return absolute_g, "absolute_grams", None


def protein_g_per_kg(protein_g: float, weight_kg: float | None) -> float | None:
    if weight_kg is None or weight_kg <= 0:
        return None
    return protein_g / weight_kg


def assess_protein_adequacy(
    protein_g: float,
    target_g: float | None,
    weight_kg: float | None,
) -> tuple[float | None, str, bool]:
    """Return (pct_of_target, status_band, critical_low_flag)."""
    per_kg = protein_g_per_kg(protein_g, weight_kg)
    critical = per_kg is not None and per_kg < PROTEIN_CRITICAL_LOW_G_PER_KG
    if target_g is None or target_g <= 0:
        return None, "unknown", critical
    pct = 100 * protein_g / target_g
    if pct < 80 or critical:
        band = "inadequate"
    elif pct < 100:
        band = "below_target"
    elif pct <= 120:
        band = "at_target"
    else:
        band = "above_target"
    return pct, band, critical


def is_high_protein_advisory(rolling_7d_g_per_kg: float | None) -> bool:
    return (
        rolling_7d_g_per_kg is not None
        and rolling_7d_g_per_kg >= PROTEIN_HIGH_ADVISORY_G_PER_KG
    )


def apply_adaptive_thermogenesis(
    tdee_kcal: float,
    baseline_weight_kg: float | None,
    current_weight_kg: float | None,
) -> tuple[float, float]:
    """First-order adaptive-thermogenesis correction: (adjusted_tdee, factor).

    Factor floors at 0.85; without both weights the TDEE is unchanged.
    """
    if (
        baseline_weight_kg is None
        or current_weight_kg is None
        or baseline_weight_kg <= 0
    ):
        return tdee_kcal, 1.0
    pct_weight_lost = (baseline_weight_kg - current_weight_kg) / baseline_weight_kg
    factor = max(ADAPTIVE_THERMO_FLOOR, 1 - pct_weight_lost * 0.5)
    factor = min(factor, 1.0)  # weight gain does not inflate TDEE
    return tdee_kcal * factor, factor


def detect_incomplete_logging(
    local_hour: int,
    total_intake_kcal: float,
    cutoff_hour: int,
    source_stale: bool,
    macros_complete: bool,
) -> bool:
    """True when the day's intake data cannot support a deficit verdict."""
    if source_stale:
        return True
    if not macros_complete:
        return True
    return (
        local_hour >= cutoff_hour
        and total_intake_kcal < INCOMPLETE_INTAKE_THRESHOLD_KCAL
    )


def infer_meal_from_hour(hour: int) -> str:
    """Timestamp-based meal bucketing when the meal field is absent."""
    if hour < 10:
        return "breakfast"
    if hour < 15:
        return "lunch"
    if hour < 21:
        return "dinner"
    return "snack"


def apply_protein_correction(protein_g: float, correction_pct: float) -> float:
    """User-applied underreporting adjustment; raw value is never replaced."""
    return protein_g * (1 + correction_pct / 100)
