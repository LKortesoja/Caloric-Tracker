"""The Calorie Tracker integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import (
    ATTR_ACTIVITY_TYPE,
    ATTR_BODY_FAT_PCT,
    ATTR_CALORIES,
    ATTR_DURATION_MINUTES,
    ATTR_FACTOR,
    ATTR_WEIGHT_KG,
    CORRECTION_FACTOR_MAX,
    CORRECTION_FACTOR_MIN,
    DOMAIN,
    SERVICE_LOG_BODY_FAT,
    SERVICE_LOG_EXERCISE,
    SERVICE_LOG_WEIGHT,
    SERVICE_RESET_DAILY,
    SERVICE_SET_CORRECTION_FACTOR,
)
from .coordinator import CalorieTrackerCoordinator

PLATFORMS = [Platform.SENSOR]

LOG_EXERCISE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ACTIVITY_TYPE): str,
        vol.Required(ATTR_DURATION_MINUTES): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_CALORIES): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)

SET_CORRECTION_FACTOR_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_FACTOR): vol.All(
            vol.Coerce(float),
            vol.Range(min=CORRECTION_FACTOR_MIN, max=CORRECTION_FACTOR_MAX),
        ),
    }
)

LOG_WEIGHT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_WEIGHT_KG): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=500)
        ),
    }
)

LOG_BODY_FAT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BODY_FAT_PCT): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=60)
        ),
    }
)


def _get_coordinator(hass: HomeAssistant) -> CalorieTrackerCoordinator:
    coordinators = list(hass.data.get(DOMAIN, {}).values())
    if not coordinators:
        raise HomeAssistantError("Calorie Tracker is not set up")
    return coordinators[0]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Calorie Tracker from a config entry."""
    coordinator = CalorieTrackerCoordinator(hass, entry)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: CalorieTrackerCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_unload()
        if not hass.data[DOMAIN]:
            for service in (
                SERVICE_LOG_EXERCISE,
                SERVICE_SET_CORRECTION_FACTOR,
                SERVICE_LOG_WEIGHT,
                SERVICE_LOG_BODY_FAT,
                SERVICE_RESET_DAILY,
            ):
                hass.services.async_remove(DOMAIN, service)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_LOG_EXERCISE):
        return

    async def handle_log_exercise(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        try:
            coordinator.log_manual_exercise(
                activity_type=call.data[ATTR_ACTIVITY_TYPE],
                duration_minutes=call.data[ATTR_DURATION_MINUTES],
                calories_override=call.data.get(ATTR_CALORIES),
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_set_correction_factor(call: ServiceCall) -> None:
        _get_coordinator(hass).set_correction_factor(call.data[ATTR_FACTOR])

    async def handle_log_weight(call: ServiceCall) -> None:
        _get_coordinator(hass).log_weight(call.data[ATTR_WEIGHT_KG])

    async def handle_log_body_fat(call: ServiceCall) -> None:
        try:
            _get_coordinator(hass).log_body_fat(call.data[ATTR_BODY_FAT_PCT])
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_reset_daily(call: ServiceCall) -> None:
        await _get_coordinator(hass).async_reset_daily()

    hass.services.async_register(
        DOMAIN, SERVICE_LOG_EXERCISE, handle_log_exercise, schema=LOG_EXERCISE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CORRECTION_FACTOR,
        handle_set_correction_factor,
        schema=SET_CORRECTION_FACTOR_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_LOG_WEIGHT, handle_log_weight, schema=LOG_WEIGHT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_LOG_BODY_FAT, handle_log_body_fat, schema=LOG_BODY_FAT_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_RESET_DAILY, handle_reset_daily)
