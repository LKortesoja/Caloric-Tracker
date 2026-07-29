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
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DISPLAY_UNIT_LB, DOMAIN
from .coordinator import CalorieTrackerCoordinator

UNIT_KCAL = "kcal"
UNIT_KCAL_PER_DAY = "kcal/d"


@dataclass(frozen=True, kw_only=True)
class CalorieTrackerSensorDescription(SensorEntityDescription):
    """Sensor description with a value function against the coordinator."""

    value_fn: Callable[[CalorieTrackerCoordinator], Any]
    attributes_fn: Callable[[CalorieTrackerCoordinator], dict[str, Any]] | None = None
    daily_total: bool = False


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def _tdee_attributes(coordinator: CalorieTrackerCoordinator) -> dict[str, Any]:
    return {
        "rmr_equation_used": coordinator.rmr_equation,
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
        attributes_fn=lambda c: {"goal": c.goal},
    ),
    CalorieTrackerSensorDescription(
        key="protein_target",
        translation_key="protein_target",
        native_unit_of_measurement="g",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:food-steak",
        suggested_display_precision=0,
        value_fn=lambda c: _round(c.protein_target_g),
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
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self.entity_id = f"sensor.{DOMAIN}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Calorie Tracker",
            manufacturer="Calorie Tracker",
            model="TDEE Calculator",
            entry_type=None,
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
