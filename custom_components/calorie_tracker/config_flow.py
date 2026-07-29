"""Config flow for the Calorie Tracker integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ACTIVITY_LEVEL,
    CONF_BMI_ENTITY,
    CONF_BODY_FAT_ENTITY,
    CONF_BODY_FAT_PCT,
    CONF_BONE_MASS_ENTITY,
    CONF_CORRECTION_FACTOR,
    CONF_DATE_OF_BIRTH,
    CONF_GOAL,
    CONF_HEIGHT_CM,
    CONF_MUSCLE_MASS_ENTITY,
    CONF_PELOTON_CALORIES_ENTITY,
    CONF_PELOTON_DURATION_ENTITY,
    CONF_PELOTON_ENABLED,
    CONF_PELOTON_HR_ENTITY,
    CONF_PELOTON_WORKOUT_ENTITY,
    CONF_PROTEIN_MULTIPLIER,
    CONF_RMR_EQUATION,
    CONF_SCALE_ENABLED,
    CONF_SEX,
    CONF_STALE_THRESHOLD_DAYS,
    CONF_TEF_PERCENTAGE,
    CONF_WATER_PCT_ENTITY,
    CONF_WEIGHT_ENTITY,
    CONF_WEIGHT_KG,
    CONF_WEIGHT_SMOOTHING,
    DEFAULT_ACTIVITY_LEVEL,
    DEFAULT_CORRECTION_FACTOR,
    DEFAULT_GOAL,
    DEFAULT_PROTEIN_MULTIPLIER,
    DEFAULT_RMR_EQUATION,
    DEFAULT_SMOOTHING,
    DEFAULT_STALE_THRESHOLD_DAYS,
    DEFAULT_TEF_PERCENTAGE,
    DOMAIN,
    EQUATION_CUNNINGHAM,
    GOAL_MAINTENANCE,
    GOAL_MUSCLE_GAIN,
    GOAL_WEIGHT_LOSS,
    RMR_EQUATIONS,
    SEX_FEMALE,
    SEX_MALE,
    SMOOTHING_NONE,
    SMOOTHING_ROLLING,
)

_LOGGER = logging.getLogger(__name__)


def _sensor_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _select(options: list[str], translation_key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key=translation_key,
        )
    )


class CalorieTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the multi-step setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # ---------------- Step 1: user profile ----------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_smart_scale()

        schema = vol.Schema(
            {
                vol.Optional(CONF_WEIGHT_KG): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=20, max=500, step=0.1, unit_of_measurement="kg",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_HEIGHT_CM): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=100, max=250, step=0.5, unit_of_measurement="cm",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_DATE_OF_BIRTH): selector.DateSelector(),
                vol.Required(CONF_SEX): _select([SEX_MALE, SEX_FEMALE], "sex"),
                vol.Optional(CONF_BODY_FAT_PCT): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=60, step=0.1, unit_of_measurement="%",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    # ---------------- Step 2: smart scale ----------------

    async def async_step_smart_scale(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            enabled = user_input.get(CONF_SCALE_ENABLED, False)
            if enabled and not user_input.get(CONF_WEIGHT_ENTITY):
                errors[CONF_WEIGHT_ENTITY] = "weight_entity_required"
            elif not enabled and self._data.get(CONF_WEIGHT_KG) is None:
                errors["base"] = "weight_required"
            else:
                self._data.update(user_input)
                return await self.async_step_metabolic()

        schema = vol.Schema(
            {
                vol.Required(CONF_SCALE_ENABLED, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_WEIGHT_ENTITY): _sensor_selector(),
                vol.Optional(CONF_BODY_FAT_ENTITY): _sensor_selector(),
                vol.Optional(CONF_MUSCLE_MASS_ENTITY): _sensor_selector(),
                vol.Optional(CONF_BONE_MASS_ENTITY): _sensor_selector(),
                vol.Optional(CONF_WATER_PCT_ENTITY): _sensor_selector(),
                vol.Optional(CONF_BMI_ENTITY): _sensor_selector(),
                vol.Required(
                    CONF_WEIGHT_SMOOTHING, default=DEFAULT_SMOOTHING
                ): _select([SMOOTHING_NONE, SMOOTHING_ROLLING], "weight_smoothing"),
                vol.Required(
                    CONF_STALE_THRESHOLD_DAYS, default=DEFAULT_STALE_THRESHOLD_DAYS
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=60, step=1, unit_of_measurement="days",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="smart_scale", data_schema=schema, errors=errors
        )

    # ---------------- Step 3: metabolic settings ----------------

    async def async_step_metabolic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            body_fat_available = (
                self._data.get(CONF_BODY_FAT_PCT) is not None
                or self._data.get(CONF_BODY_FAT_ENTITY) is not None
            )
            if (
                user_input[CONF_RMR_EQUATION] == EQUATION_CUNNINGHAM
                and not body_fat_available
            ):
                errors[CONF_RMR_EQUATION] = "cunningham_requires_body_fat"
            else:
                self._data.update(user_input)
                return await self.async_step_goals()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RMR_EQUATION, default=DEFAULT_RMR_EQUATION
                ): _select(RMR_EQUATIONS, "rmr_equation"),
                vol.Required(
                    CONF_ACTIVITY_LEVEL, default=DEFAULT_ACTIVITY_LEVEL
                ): _select(
                    ["sedentary", "lightly_active", "moderately_active", "very_active"],
                    "activity_level",
                ),
            }
        )
        return self.async_show_form(
            step_id="metabolic", data_schema=schema, errors=errors
        )

    # ---------------- Step 4: goals ----------------

    async def async_step_goals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_exercise()

        schema = vol.Schema(
            {
                vol.Required(CONF_GOAL, default=DEFAULT_GOAL): _select(
                    [GOAL_WEIGHT_LOSS, GOAL_MAINTENANCE, GOAL_MUSCLE_GAIN], "goal"
                ),
                vol.Required(
                    CONF_PROTEIN_MULTIPLIER, default=DEFAULT_PROTEIN_MULTIPLIER
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5, max=3.0, step=0.1, unit_of_measurement="g/kg",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="goals", data_schema=schema)

    # ---------------- Step 5: exercise sources ----------------

    async def async_step_exercise(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_PELOTON_ENABLED) and not user_input.get(
                CONF_PELOTON_CALORIES_ENTITY
            ):
                errors[CONF_PELOTON_CALORIES_ENTITY] = "peloton_calories_required"
            else:
                self._data.update(user_input)
                return await self.async_step_optional()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PELOTON_ENABLED, default=False
                ): selector.BooleanSelector(),
                vol.Optional(CONF_PELOTON_WORKOUT_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "binary_sensor"])
                ),
                vol.Optional(CONF_PELOTON_CALORIES_ENTITY): _sensor_selector(),
                vol.Optional(CONF_PELOTON_DURATION_ENTITY): _sensor_selector(),
                vol.Optional(CONF_PELOTON_HR_ENTITY): _sensor_selector(),
                vol.Required(
                    CONF_CORRECTION_FACTOR, default=DEFAULT_CORRECTION_FACTOR
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.50, max=1.00, step=0.01,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="exercise", data_schema=schema, errors=errors
        )

    # ---------------- Step 6: optional ----------------

    async def async_step_optional(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="Calorie Tracker", data=self._data)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TEF_PERCENTAGE, default=DEFAULT_TEF_PERCENTAGE
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=15, step=1, unit_of_measurement="%",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="optional", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CalorieTrackerOptionsFlow()


class CalorieTrackerOptionsFlow(OptionsFlow):
    """Adjust tunable settings without re-running the full setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        def current(key: str, default: Any) -> Any:
            return self.config_entry.options.get(
                key, self.config_entry.data.get(key, default)
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CORRECTION_FACTOR,
                    default=current(CONF_CORRECTION_FACTOR, DEFAULT_CORRECTION_FACTOR),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.50, max=1.00, step=0.01,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Required(
                    CONF_GOAL, default=current(CONF_GOAL, DEFAULT_GOAL)
                ): _select(
                    [GOAL_WEIGHT_LOSS, GOAL_MAINTENANCE, GOAL_MUSCLE_GAIN], "goal"
                ),
                vol.Required(
                    CONF_PROTEIN_MULTIPLIER,
                    default=current(CONF_PROTEIN_MULTIPLIER, DEFAULT_PROTEIN_MULTIPLIER),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5, max=3.0, step=0.1, unit_of_measurement="g/kg",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_ACTIVITY_LEVEL,
                    default=current(CONF_ACTIVITY_LEVEL, DEFAULT_ACTIVITY_LEVEL),
                ): _select(
                    ["sedentary", "lightly_active", "moderately_active", "very_active"],
                    "activity_level",
                ),
                vol.Required(
                    CONF_WEIGHT_SMOOTHING,
                    default=current(CONF_WEIGHT_SMOOTHING, DEFAULT_SMOOTHING),
                ): _select([SMOOTHING_NONE, SMOOTHING_ROLLING], "weight_smoothing"),
                vol.Required(
                    CONF_STALE_THRESHOLD_DAYS,
                    default=current(
                        CONF_STALE_THRESHOLD_DAYS, DEFAULT_STALE_THRESHOLD_DAYS
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=60, step=1, unit_of_measurement="days",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_TEF_PERCENTAGE,
                    default=current(CONF_TEF_PERCENTAGE, DEFAULT_TEF_PERCENTAGE),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=15, step=1, unit_of_measurement="%",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
