"""Binary sensor platform for the Calorie Tracker integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CalorieTrackerCoordinator


@dataclass(frozen=True, kw_only=True)
class CalorieTrackerBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description with a value function."""

    value_fn: Callable[[CalorieTrackerCoordinator], bool]
    attributes_fn: Callable[[CalorieTrackerCoordinator], dict[str, Any]] | None = None


BINARY_SENSORS: tuple[CalorieTrackerBinarySensorDescription, ...] = (
    CalorieTrackerBinarySensorDescription(
        key="below_intake_floor",
        translation_key="below_intake_floor",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:food-off",
        value_fn=lambda c: c.below_intake_floor,
        attributes_fn=lambda c: {
            "intake_floor_kcal": c.intake_floor_kcal,
            "intake_kcal": round(c.intake_calories, 1),
        },
    ),
    CalorieTrackerBinarySensorDescription(
        key="protein_inadequate",
        translation_key="protein_inadequate",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:food-drumstick-off",
        value_fn=lambda c: c.protein_adequacy[1] == "inadequate",
        attributes_fn=lambda c: {"status_band": c.protein_adequacy[1]},
    ),
    CalorieTrackerBinarySensorDescription(
        key="aggressive_deficit",
        translation_key="aggressive_deficit",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:alert-decagram",
        value_fn=lambda c: c.energy_balance_is_aggressive,
        attributes_fn=lambda c: {
            "deficit_classification": c.deficit_classification,
        },
    ),
    CalorieTrackerBinarySensorDescription(
        key="incomplete_logging",
        translation_key="incomplete_logging",
        icon="mdi:progress-question",
        value_fn=lambda c: c.incomplete_logging,
        attributes_fn=lambda c: {
            "macros_complete": c.macros_complete,
            "source_stale": c.sparky_stale,
            "intake_kcal": round(c.intake_calories, 1),
        },
    ),
    CalorieTrackerBinarySensorDescription(
        key="sparkyfitness_connected",
        translation_key="sparkyfitness_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.sparky_connected,
        attributes_fn=lambda c: {
            "last_successful_sync": c.sparky_last_success.isoformat()
            if c.sparky_last_success
            else None,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Calorie Tracker binary sensors."""
    coordinator: CalorieTrackerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CalorieTrackerBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class CalorieTrackerBinarySensor(BinarySensorEntity):
    """A Calorie Tracker binary sensor backed by the coordinator."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    entity_description: CalorieTrackerBinarySensorDescription

    def __init__(
        self,
        coordinator: CalorieTrackerCoordinator,
        description: CalorieTrackerBinarySensorDescription,
    ) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self.entity_id = f"binary_sensor.{DOMAIN}_{description.key}"
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
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator)
