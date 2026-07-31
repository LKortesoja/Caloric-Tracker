"""Sensor platform for the Calorie Tracker integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_PER_MEAL_PROTEIN_G,
    CONF_SPARKY_ENABLED,
    CONF_TEF_MODE,
    DEFAULT_PER_MEAL_PROTEIN_G,
    DISPLAY_UNIT_LB,
    DOMAIN,
    TEF_MODE_FLAT,
    TEF_MODE_MACRO,
)
from .coordinator import CalorieTrackerCoordinator

UNIT_KCAL = "kcal"
UNIT_KCAL_PER_DAY = "kcal/d"


@dataclass(frozen=True, kw_only=True)
class CalorieTrackerSensorDescription(SensorEntityDescription):
    """Sensor description with a value function against the coordinator."""

    value_fn: Callable[[CalorieTrackerCoordinator], Any]
    attributes_fn: Callable[[CalorieTrackerCoordinator], dict[str, Any]] | None = None
    daily_total: bool = False
    intake_sensor: bool = False  # unavailable when the source is down w/o cache


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def _tdee_attributes(coordinator: CalorieTrackerCoordinator) -> dict[str, Any]:
    return {
        "rmr_equation_used": coordinator.rmr_source,
        "tdee_calculation_mode": coordinator.tdee_calculation_mode,
        "rmr_value": _round(coordinator.rmr),
        "pal_factor": coordinator.pal_factor,
        "tef_percentage": coordinator.tef_percentage,
        "exercise_sessions": coordinator.sessions,
        "correction_factor": coordinator.correction_factor,
        "weight_source": coordinator.weight_source,
        "weight_value_kg": _round(coordinator.effective_weight_kg),
        "body_composition_available": coordinator.body_composition_available,
        "last_updated": coordinator.last_updated.isoformat(),
    }


def _recommendation_attributes(coordinator: CalorieTrackerCoordinator) -> dict[str, Any]:
    rec = coordinator.recommendation
    return {
        "recommendation_reason": rec.reasoning,
        "acwr_ratio": _round(rec.acwr_ratio, 2),
        "high_intensity_ratio": _round(rec.high_intensity_ratio, 2),
        "is_cold_start": rec.is_cold_start,
        "mandatory_rest": rec.mandatory_rest,
        "strength_lockout": rec.strength_lockout,
        "mobility_deficit": rec.mobility_deficit,
        "acute_fatigue": rec.acute_fatigue,
        "polarization_high_skew": rec.polarization_high_skew,
        "strength_priority_high": rec.strength_priority_high,
        "underfueling": rec.underfueling,
        "nutrition_notes": list(rec.nutrition_notes),
        "required_daily_pace": _round(rec.required_daily_pace, 2),
    }


def _acwr_value(coordinator: CalorieTrackerCoordinator) -> Any:
    rec = coordinator.recommendation
    if rec.acwr_ratio is None:
        return "initializing"
    return round(rec.acwr_ratio, 2)


def _intake_attributes(coordinator: CalorieTrackerCoordinator) -> dict[str, Any]:
    return {
        "source": coordinator.intake_source,
        "entry_count": coordinator.intake_entry_count,
        "manual_entry_count": coordinator.manual_entry_count,
        "last_sync": coordinator.sparky_last_success.isoformat()
        if coordinator.sparky_last_success
        else None,
        "macros_complete": coordinator.macros_complete,
    }


def _energy_balance_attributes(coordinator: CalorieTrackerCoordinator) -> dict[str, Any]:
    classification = coordinator.deficit_classification
    return {
        "deficit_classification": classification,
        "aggressive_deficit_flag": coordinator.energy_balance_is_aggressive,
        "below_intake_floor_flag": coordinator.below_intake_floor,
        "tdee_used": _round(coordinator.tdee),
        "intake_used": _round(coordinator.intake_calories),
        "tdee_calculation_mode": coordinator.tdee_calculation_mode,
        "intake_floor_kcal": coordinator.intake_floor_kcal,
    }


def _protein_adequacy_attributes(coordinator: CalorieTrackerCoordinator) -> dict[str, Any]:
    target_g, basis, basis_weight = coordinator.protein_target
    _, band, critical = coordinator.protein_adequacy
    per_kg = (
        coordinator.intake_protein_g / coordinator.effective_weight_kg
        if coordinator.effective_weight_kg
        else None
    )
    return {
        "protein_target_g": _round(target_g),
        "protein_g_actual": _round(coordinator.intake_protein_g),
        "protein_g_corrected": _round(coordinator.intake_protein_g_corrected),
        "protein_g_per_kg": _round(per_kg, 2),
        "target_basis": basis,
        "basis_weight_kg": _round(basis_weight),
        "status_band": band,
        "critical_low_protein_flag": critical,
        "high_protein_advisory_flag": coordinator.high_protein_advisory,
    }


def _weight_attributes(coordinator: CalorieTrackerCoordinator) -> dict[str, Any]:
    attributes = {
        "source": coordinator.weight_source,
        "last_measurement": coordinator.last_measurement.isoformat()
        if coordinator.last_measurement
        else None,
        "weight_data_stale": coordinator.weight_data_stale,
        "smoothing_enabled": coordinator.smoothing_enabled,
        "smoothing_window_days": coordinator.smoothing_window_days,
    }
    if coordinator.smoothing_enabled:
        attributes["raw_weight"] = _round(coordinator.raw_weight_kg)
    return attributes


SENSORS: tuple[CalorieTrackerSensorDescription, ...] = (
    CalorieTrackerSensorDescription(
        key="rmr",
        translation_key="rmr",
        native_unit_of_measurement=UNIT_KCAL_PER_DAY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        suggested_display_precision=0,
        value_fn=lambda c: _round(c.rmr),
        attributes_fn=lambda c: {
            "rmr_equation_used": c.rmr_equation,
            "fat_free_mass_kg": _round(c.fat_free_mass_kg),
        },
    ),
    CalorieTrackerSensorDescription(
        key="base_daily",
        translation_key="base_daily",
        native_unit_of_measurement=UNIT_KCAL_PER_DAY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-heart",
        suggested_display_precision=0,
        value_fn=lambda c: _round(c.base_daily_kcal),
        attributes_fn=lambda c: {"pal_factor": c.pal_factor},
    ),
    CalorieTrackerSensorDescription(
        key="exercise_gross",
        translation_key="exercise_gross",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:run-fast",
        suggested_display_precision=0,
        daily_total=True,
        value_fn=lambda c: _round(c.exercise_gross_kcal),
    ),
    CalorieTrackerSensorDescription(
        key="exercise_net",
        translation_key="exercise_net",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:run",
        suggested_display_precision=0,
        daily_total=True,
        value_fn=lambda c: _round(c.exercise_net_kcal),
        attributes_fn=lambda c: {"correction_factor": c.correction_factor},
    ),
    CalorieTrackerSensorDescription(
        key="tdee",
        translation_key="tdee",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt",
        suggested_display_precision=0,
        daily_total=True,
        value_fn=lambda c: _round(c.tdee),
        attributes_fn=_tdee_attributes,
    ),
    CalorieTrackerSensorDescription(
        key="tdee_7d_avg",
        translation_key="tdee_7d_avg",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-timeline-variant",
        suggested_display_precision=0,
        value_fn=lambda c: _round(c.tdee_7d_avg),
        attributes_fn=lambda c: {"days_of_data": c.rolling_days_of_data(7)},
    ),
    CalorieTrackerSensorDescription(
        key="tdee_30d_avg",
        translation_key="tdee_30d_avg",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-timeline-variant-shimmer",
        suggested_display_precision=0,
        value_fn=lambda c: _round(c.tdee_30d_avg),
        attributes_fn=lambda c: {"days_of_data": c.rolling_days_of_data(30)},
    ),
    CalorieTrackerSensorDescription(
        key="workout_recommendation",
        translation_key="workout_recommendation",
        icon="mdi:clipboard-text-play",
        value_fn=lambda c: c.recommendation.primary,
        attributes_fn=_recommendation_attributes,
    ),
    CalorieTrackerSensorDescription(
        key="acwr",
        translation_key="acwr",
        icon="mdi:speedometer",
        value_fn=_acwr_value,
        attributes_fn=lambda c: {
            "acute_ewma_7d": _round(c.recommendation.acute_ewma),
            "chronic_ewma_28d": _round(c.recommendation.chronic_ewma),
            "days_of_data": c.recommendation.days_of_data,
        },
    ),
    CalorieTrackerSensorDescription(
        key="weekly_aerobic_minutes",
        translation_key="weekly_aerobic_minutes",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-pulse",
        suggested_display_precision=0,
        value_fn=lambda c: _round(c.weekly_aerobic_minutes),
        attributes_fn=lambda c: {
            "target_minutes": c.weekly_aerobic_minutes_goal,
            "pct_complete": _round(
                100 * c.weekly_aerobic_minutes / c.weekly_aerobic_minutes_goal
            )
            if c.weekly_aerobic_minutes_goal
            else None,
        },
    ),
    CalorieTrackerSensorDescription(
        key="monthly_distance_progress",
        translation_key="monthly_distance_progress",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
        suggested_display_precision=1,
        value_fn=lambda c: _round(c.monthly_distance, 2),
        attributes_fn=lambda c: {
            "target_distance": c.monthly_distance_goal,
            "required_daily_pace": _round(c.recommendation.required_daily_pace, 2),
            "pct_complete": _round(100 * c.monthly_distance / c.monthly_distance_goal)
            if c.monthly_distance_goal
            else None,
        },
    ),
    CalorieTrackerSensorDescription(
        key="exercise_count",
        translation_key="exercise_count",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:counter",
        daily_total=True,
        value_fn=lambda c: c.exercise_count,
    ),
    CalorieTrackerSensorDescription(
        key="correction_factor",
        translation_key="correction_factor",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:tune",
        value_fn=lambda c: c.correction_factor,
    ),
    CalorieTrackerSensorDescription(
        key="daily_budget",
        translation_key="daily_budget",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:food-apple",
        suggested_display_precision=0,
        value_fn=lambda c: _round(c.daily_budget),
        attributes_fn=lambda c: {
            "goal": c.goal,
            "budget_mode": c.budget_mode,
            "tdee_used": _round(c.budget_tdee),
        },
    ),
    CalorieTrackerSensorDescription(
        key="protein_target",
        translation_key="protein_target",
        native_unit_of_measurement="g",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:food-steak",
        suggested_display_precision=0,
        value_fn=lambda c: _round(c.protein_target_g),
        attributes_fn=lambda c: {
            "target_basis": c.protein_target[1],
            "basis_weight_kg": _round(c.protein_target[2]),
        },
    ),
    CalorieTrackerSensorDescription(
        key="intake_calories",
        translation_key="intake_calories",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:silverware-fork-knife",
        suggested_display_precision=0,
        daily_total=True,
        intake_sensor=True,
        value_fn=lambda c: _round(c.intake_calories),
        attributes_fn=_intake_attributes,
    ),
    CalorieTrackerSensorDescription(
        key="intake_protein",
        translation_key="intake_protein",
        native_unit_of_measurement="g",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:food-drumstick",
        suggested_display_precision=0,
        daily_total=True,
        intake_sensor=True,
        value_fn=lambda c: _round(c.intake_protein_g),
        attributes_fn=_intake_attributes,
    ),
    CalorieTrackerSensorDescription(
        key="intake_carbs",
        translation_key="intake_carbs",
        native_unit_of_measurement="g",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:bread-slice",
        suggested_display_precision=0,
        daily_total=True,
        intake_sensor=True,
        value_fn=lambda c: _round(c.intake_carbs_g),
        attributes_fn=_intake_attributes,
    ),
    CalorieTrackerSensorDescription(
        key="intake_fat",
        translation_key="intake_fat",
        native_unit_of_measurement="g",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:oil",
        suggested_display_precision=0,
        daily_total=True,
        intake_sensor=True,
        value_fn=lambda c: _round(c.intake_fat_g),
        attributes_fn=_intake_attributes,
    ),
    CalorieTrackerSensorDescription(
        key="intake_fiber",
        translation_key="intake_fiber",
        native_unit_of_measurement="g",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:corn",
        suggested_display_precision=0,
        daily_total=True,
        intake_sensor=True,
        value_fn=lambda c: _round(c.intake_fiber_g),
        attributes_fn=_intake_attributes,
    ),
    CalorieTrackerSensorDescription(
        key="calories_remaining",
        translation_key="calories_remaining",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:food-apple-outline",
        suggested_display_precision=0,
        intake_sensor=True,
        value_fn=lambda c: _round(c.calories_remaining),
        attributes_fn=lambda c: {
            "daily_budget": _round(c.daily_budget),
            "intake_used": _round(c.intake_calories),
            "pct_of_budget_used": _round(
                100 * c.intake_calories / c.daily_budget
            )
            if c.daily_budget
            else None,
            "over_budget": c.calories_remaining < 0,
        },
    ),
    CalorieTrackerSensorDescription(
        key="energy_balance",
        translation_key="energy_balance",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:scale-balance",
        suggested_display_precision=0,
        intake_sensor=True,
        value_fn=lambda c: _round(c.energy_balance_kcal),
        attributes_fn=_energy_balance_attributes,
    ),
    CalorieTrackerSensorDescription(
        key="protein_adequacy",
        translation_key="protein_adequacy",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:food-steak",
        suggested_display_precision=0,
        intake_sensor=True,
        value_fn=lambda c: _round(c.protein_adequacy[0]),
        attributes_fn=_protein_adequacy_attributes,
    ),
    CalorieTrackerSensorDescription(
        key="tef",
        translation_key="tef",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire-circle",
        suggested_display_precision=0,
        intake_sensor=True,
        value_fn=lambda c: _round(c.tef_result.tef_kcal),
        attributes_fn=lambda c: {
            "calculation_mode": TEF_MODE_FLAT
            if c.tef_result.estimated
            else c._conf(CONF_TEF_MODE, TEF_MODE_MACRO),
            "tef_estimated": c.tef_result.estimated,
            "protein_tef_kcal": _round(c.tef_result.protein_kcal),
            "carbs_tef_kcal": _round(c.tef_result.carbs_kcal),
            "fat_tef_kcal": _round(c.tef_result.fat_kcal),
        },
    ),
    CalorieTrackerSensorDescription(
        key="protein_per_kg",
        translation_key="protein_per_kg",
        native_unit_of_measurement="g/kg",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weight-gram",
        suggested_display_precision=2,
        intake_sensor=True,
        value_fn=lambda c: _round(
            c.intake_protein_g / c.effective_weight_kg, 2
        )
        if c.effective_weight_kg
        else None,
        attributes_fn=lambda c: {
            "basis_weight_kg": _round(c.effective_weight_kg),
            "rolling_7d_g_per_kg": _round(c.rolling_7d_protein_g_per_kg, 2),
        },
    ),
    CalorieTrackerSensorDescription(
        key="rolling_7d_deficit",
        translation_key="rolling_7d_deficit",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-week",
        suggested_display_precision=0,
        value_fn=lambda c: _round(c.rolling_7d_energy_balance[0]),
        attributes_fn=lambda c: {
            "days_with_complete_data": c.rolling_7d_energy_balance[1],
        },
    ),
    CalorieTrackerSensorDescription(
        key="meal_protein_distribution",
        translation_key="meal_protein_distribution",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:silverware-variant",
        intake_sensor=True,
        value_fn=lambda c: c.meals_meeting_protein_target,
        attributes_fn=lambda c: {
            "per_meal_target_g": c._conf(
                CONF_PER_MEAL_PROTEIN_G, DEFAULT_PER_MEAL_PROTEIN_G
            ),
            "meals_logged": len(c.per_meal_breakdown),
            "meal_inferred": any(
                entry.get("meal_inferred") for entry in c.food_entries
            ),
            "per_meal_breakdown": {
                meal: _round(protein)
                for meal, protein in c.per_meal_breakdown.items()
            },
        },
    ),
    CalorieTrackerSensorDescription(
        key="weight",
        translation_key="weight",
        native_unit_of_measurement="kg",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:scale-bathroom",
        suggested_display_precision=1,
        value_fn=lambda c: c.effective_weight_kg,
        attributes_fn=_weight_attributes,
    ),
    CalorieTrackerSensorDescription(
        key="body_fat",
        translation_key="body_fat",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        suggested_display_precision=1,
        value_fn=lambda c: c.body_fat_pct,
        attributes_fn=lambda c: {"fat_mass_kg": _round(c.fat_mass_kg)},
    ),
    CalorieTrackerSensorDescription(
        key="fat_free_mass",
        translation_key="fat_free_mass",
        native_unit_of_measurement="kg",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arm-flex",
        suggested_display_precision=1,
        value_fn=lambda c: c.fat_free_mass_kg,
    ),
    CalorieTrackerSensorDescription(
        key="muscle_mass",
        translation_key="muscle_mass",
        native_unit_of_measurement="kg",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weight-lifter",
        suggested_display_precision=1,
        value_fn=lambda c: c.muscle_mass_kg,
    ),
    CalorieTrackerSensorDescription(
        key="bmi",
        translation_key="bmi",
        native_unit_of_measurement="kg/m²",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:human",
        suggested_display_precision=1,
        value_fn=lambda c: c.bmi,
    ),
    CalorieTrackerSensorDescription(
        key="weight_trend",
        translation_key="weight_trend",
        native_unit_of_measurement="kg",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line",
        suggested_display_precision=1,
        value_fn=lambda c: c.weight_trend_kg,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Calorie Tracker sensors."""
    coordinator: CalorieTrackerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CalorieTrackerSensor(coordinator, description) for description in SENSORS
    )


class CalorieTrackerSensor(SensorEntity):
    """A Calorie Tracker sensor backed by the coordinator."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    entity_description: CalorieTrackerSensorDescription

    def __init__(
        self,
        coordinator: CalorieTrackerCoordinator,
        description: CalorieTrackerSensorDescription,
    ) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        # Mass sensors stay kg natively (keeps long-term statistics stable);
        # HA converts the displayed state when the user prefers pounds.
        if (
            description.device_class is SensorDeviceClass.WEIGHT
            and coordinator.display_unit == DISPLAY_UNIT_LB
        ):
            self._attr_suggested_unit_of_measurement = DISPLAY_UNIT_LB
        if description.key == "monthly_distance_progress":
            # Distance follows the weight-unit preference: miles for lb users.
            self._attr_native_unit_of_measurement = (
                "mi" if coordinator.display_unit == DISPLAY_UNIT_LB else "km"
            )
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self.entity_id = f"sensor.{DOMAIN}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Calorie Tracker",
            manufacturer="Calorie Tracker",
            model="TDEE Calculator",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self.coordinator.signal, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Intake sensors go unavailable when the source is down with no cache."""
        if not self.entity_description.intake_sensor:
            return True
        coordinator = self.coordinator
        if not coordinator._conf(CONF_SPARKY_ENABLED):
            return True
        return coordinator.sparky_connected or bool(coordinator.food_entries)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def last_reset(self) -> datetime | None:
        """Daily totals reset at local midnight."""
        if self.entity_description.daily_total:
            return dt_util.start_of_local_day()
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator)
