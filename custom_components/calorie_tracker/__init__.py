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
    ATTR_DISTANCE,
    ATTR_DURATION_MINUTES,
    ATTR_FACTOR,
    ATTR_WEIGHT,
    ATTR_WEIGHT_UNIT,
    CONF_PROTEIN_ABSOLUTE_G,
    CONF_PROTEIN_BASIS,
    CONF_PROTEIN_G_PER_KG,
    CONF_PROTEIN_G_PER_KG_FFM,
    CONF_TARGET_DAILY_DEFICIT,
    CORRECTION_FACTOR_MAX,
    CORRECTION_FACTOR_MIN,
    DISPLAY_UNIT_KG,
    DISPLAY_UNIT_LB,
    DOMAIN,
    PROTEIN_BASES,
    PROTEIN_BASIS_ABSOLUTE,
    PROTEIN_BASIS_FFM,
    SERVICE_CLEAR_FOOD_LOG,
    SERVICE_LOG_BODY_FAT,
    SERVICE_LOG_EXERCISE,
    SERVICE_LOG_FOOD,
    SERVICE_LOG_WEIGHT,
    SERVICE_RESET_DAILY,
    SERVICE_SET_CORRECTION_FACTOR,
    SERVICE_SET_DEFICIT_TARGET,
    SERVICE_SET_PROTEIN_TARGET,
    SERVICE_SYNC_SPARKYFITNESS,
)
from .coordinator import CalorieTrackerCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

ALL_SERVICES = (
    SERVICE_LOG_EXERCISE,
    SERVICE_SET_CORRECTION_FACTOR,
    SERVICE_LOG_WEIGHT,
    SERVICE_LOG_BODY_FAT,
    SERVICE_RESET_DAILY,
    SERVICE_LOG_FOOD,
    SERVICE_SET_PROTEIN_TARGET,
    SERVICE_SET_DEFICIT_TARGET,
    SERVICE_SYNC_SPARKYFITNESS,
    SERVICE_CLEAR_FOOD_LOG,
)

LOG_EXERCISE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ACTIVITY_TYPE): str,
        vol.Required(ATTR_DURATION_MINUTES): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_CALORIES): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional(ATTR_DISTANCE): vol.All(vol.Coerce(float), vol.Range(min=0)),
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
        vol.Required(ATTR_WEIGHT): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=1200)
        ),
        vol.Optional(ATTR_WEIGHT_UNIT): vol.In([DISPLAY_UNIT_KG, DISPLAY_UNIT_LB]),
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
            for service in ALL_SERVICES:
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
                distance=call.data.get(ATTR_DISTANCE),
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_set_correction_factor(call: ServiceCall) -> None:
        _get_coordinator(hass).set_correction_factor(call.data[ATTR_FACTOR])

    async def handle_log_weight(call: ServiceCall) -> None:
        _get_coordinator(hass).log_weight(
            call.data[ATTR_WEIGHT], call.data.get(ATTR_WEIGHT_UNIT)
        )

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
    async def handle_log_food(call: ServiceCall) -> None:
        try:
            _get_coordinator(hass).log_food(
                food_name=call.data["food_name"],
                calories=call.data["calories"],
                protein_g=call.data.get("protein_g"),
                carbs_g=call.data.get("carbs_g"),
                fat_g=call.data.get("fat_g"),
                fiber_g=call.data.get("fiber_g"),
                meal=call.data.get("meal"),
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_set_protein_target(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        entry = coordinator.entry
        options = dict(entry.options)
        basis = call.data.get("basis")
        if basis:
            options[CONF_PROTEIN_BASIS] = basis
        else:
            basis = options.get(
                CONF_PROTEIN_BASIS, entry.data.get(CONF_PROTEIN_BASIS)
            )
        value = call.data["value"]
        if basis == PROTEIN_BASIS_ABSOLUTE:
            options[CONF_PROTEIN_ABSOLUTE_G] = value
        elif basis == PROTEIN_BASIS_FFM:
            options[CONF_PROTEIN_G_PER_KG_FFM] = value
        else:
            options[CONF_PROTEIN_G_PER_KG] = value
        hass.config_entries.async_update_entry(entry, options=options)

    async def handle_set_deficit_target(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        entry = coordinator.entry
        options = dict(entry.options)
        options[CONF_TARGET_DAILY_DEFICIT] = call.data["kcal"]
        hass.config_entries.async_update_entry(entry, options=options)

    async def handle_sync_sparkyfitness(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        if coordinator.sparky_coordinator is None:
            raise HomeAssistantError("SparkyFitness is not configured")
        await coordinator.sparky_coordinator.async_request_refresh()

    async def handle_clear_food_log(call: ServiceCall) -> None:
        _get_coordinator(hass).clear_todays_food_log()

    hass.services.async_register(DOMAIN, SERVICE_RESET_DAILY, handle_reset_daily)
    hass.services.async_register(
        DOMAIN,
        SERVICE_LOG_FOOD,
        handle_log_food,
        schema=vol.Schema(
            {
                vol.Required("food_name"): str,
                vol.Required("calories"): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=10000)
                ),
                vol.Optional("protein_g"): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=500)
                ),
                vol.Optional("carbs_g"): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=2000)
                ),
                vol.Optional("fat_g"): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=1000)
                ),
                vol.Optional("fiber_g"): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=300)
                ),
                vol.Optional("meal"): vol.In(
                    ["breakfast", "lunch", "dinner", "snack"]
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PROTEIN_TARGET,
        handle_set_protein_target,
        schema=vol.Schema(
            {
                vol.Required("value"): vol.All(
                    vol.Coerce(float), vol.Range(min=0.4, max=300)
                ),
                vol.Optional("basis"): vol.In(PROTEIN_BASES),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DEFICIT_TARGET,
        handle_set_deficit_target,
        schema=vol.Schema(
            {
                vol.Required("kcal"): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=1000)
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SYNC_SPARKYFITNESS, handle_sync_sparkyfitness
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_FOOD_LOG, handle_clear_food_log
    )
