"""Diagnostics support for the Calorie Tracker integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_SPARKY_API_KEY,
    CONF_SPARKY_BASE_URL,
    CONF_SPARKY_USER_ID,
    DOMAIN,
)
from .coordinator import CalorieTrackerCoordinator

TO_REDACT = {CONF_SPARKY_API_KEY, CONF_SPARKY_BASE_URL, CONF_SPARKY_USER_ID}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator: CalorieTrackerCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "state": {
            "weight_source": coordinator.weight_source,
            "rmr": coordinator.rmr,
            "rmr_source": coordinator.rmr_source,
            "tdee": coordinator.tdee,
            "tdee_calculation_mode": coordinator.tdee_calculation_mode,
            "sessions_today": coordinator.exercise_count,
            "intake_entry_count": coordinator.intake_entry_count,
            "manual_entry_count": coordinator.manual_entry_count,
            "sparky_connected": coordinator.sparky_connected,
            "sparky_last_success": coordinator.sparky_last_success.isoformat()
            if coordinator.sparky_last_success
            else None,
            "incomplete_logging": coordinator.incomplete_logging,
            "deficit_classification": coordinator.deficit_classification,
            "history_days": len(coordinator.history),
        },
    }
