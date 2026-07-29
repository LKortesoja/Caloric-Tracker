"""State manager for the Calorie Tracker integration.

Deliberately not a DataUpdateCoordinator: there is no polling. All updates
are event-driven via async_track_state_change_event on the mapped smart
scale / Peloton entities, service calls, and a midnight reset timer.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import calculator as calc
from .const import (
    ACTIVITY_LEVELS,
    BODY_FAT_MAX,
    BODY_FAT_MIN,
    BUDGET_MODE_7D,
    BUDGET_MODE_30D,
    CONF_BUDGET_MODE,
    CONF_ACTIVITY_LEVEL,
    CONF_BMI_ENTITY,
    CONF_BODY_FAT_ENTITY,
    CONF_BODY_FAT_PCT,
    CONF_BONE_MASS_ENTITY,
    CONF_CORRECTION_FACTOR,
    CONF_DATE_OF_BIRTH,
    CONF_DISPLAY_UNIT,
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
    DEFAULT_BUDGET_MODE,
    DEFAULT_CORRECTION_FACTOR,
    DEFAULT_DISPLAY_UNIT,
    DEFAULT_GOAL,
    DEFAULT_PROTEIN_MULTIPLIER,
    DEFAULT_RMR_EQUATION,
    DEFAULT_SMOOTHING,
    DEFAULT_STALE_THRESHOLD_DAYS,
    DEFAULT_TEF_PERCENTAGE,
    DOMAIN,
    EQUATION_CUNNINGHAM,
    EQUATION_HARRIS,
    EQUATION_MIFFLIN,
    EXERCISE_SOURCE_MANUAL,
    EXERCISE_SOURCE_PELOTON,
    GOAL_OFFSETS,
    HISTORY_RETENTION_DAYS,
    MET_VALUES,
    SIGNAL_UPDATE,
    SMOOTHING_ROLLING,
    SMOOTHING_WINDOW_DAYS,
    SOURCE_LAST_KNOWN,
    SOURCE_MANUAL,
    SOURCE_SMART_SCALE,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

# Peloton workout-entity states that indicate a session in progress.
_ACTIVE_WORKOUT_STATES = {"in_progress", "in progress", "active", "riding", "on"}


class CalorieTrackerCoordinator:
    """Holds all runtime state and recomputes derived metrics on events."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubscribers: list[Callable[[], None]] = []

        # Weight / body composition state
        self.weight_kg: float | None = None
        self.weight_source: str = SOURCE_MANUAL
        self.last_measurement: datetime | None = None
        self.weight_readings: list[tuple[datetime, float]] = []
        self.body_fat_pct: float | None = None
        self.fat_mass_kg: float | None = None
        self._body_fat_from_fat_mass = False
        self.muscle_mass_kg: float | None = None
        self.bone_mass_kg: float | None = None
        self.water_pct: float | None = None
        self.scale_bmi: float | None = None

        # Exercise state
        self.sessions: list[dict[str, Any]] = []
        # Completed-day summaries keyed by ISO date, for rolling averages.
        self.history: dict[str, dict[str, float]] = {}
        self.correction_factor: float = self._conf(
            CONF_CORRECTION_FACTOR, DEFAULT_CORRECTION_FACTOR
        )

        self.last_reset: date = dt_util.now().date()
        self.last_updated: datetime = dt_util.now()
        self._peloton_workout_active = False
        self._stale_notified = False

    # ------------------------------------------------------------------
    # Config access (options override data)
    # ------------------------------------------------------------------

    def _conf(self, key: str, default: Any = None) -> Any:
        return self.entry.options.get(key, self.entry.data.get(key, default))

    @property
    def signal(self) -> str:
        return SIGNAL_UPDATE.format(self.entry.entry_id)

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Load persisted state and subscribe to entity + time events."""
        await self._async_load()

        # Seed weight from config if nothing persisted yet.
        if self.weight_kg is None and self._conf(CONF_WEIGHT_KG) is not None:
            self.weight_kg = float(self._conf(CONF_WEIGHT_KG))
            self.weight_source = SOURCE_MANUAL
        if self.body_fat_pct is None and self._conf(CONF_BODY_FAT_PCT) is not None:
            self.body_fat_pct = float(self._conf(CONF_BODY_FAT_PCT))

        if self.age is not None and self.age < 18:
            _LOGGER.warning(
                "Calorie Tracker profile age is %s; predictive RMR equations "
                "are validated for adults 18-65 and may be inaccurate",
                self.age,
            )

        if self._conf(CONF_SCALE_ENABLED):
            self._subscribe_scale_entities()
            self._seed_from_scale_entities()

        if self._conf(CONF_PELOTON_ENABLED):
            self._subscribe_peloton_entities()

        # Midnight reset in the Home Assistant local timezone.
        self._unsubscribers.append(
            async_track_time_change(
                self.hass, self._handle_midnight, hour=0, minute=0, second=0
            )
        )

        # Catch up if HA was down over midnight.
        if self.last_reset != dt_util.now().date():
            await self._async_daily_reset()

        self._check_staleness()
        self.async_update_listeners()

    async def async_unload(self) -> None:
        for unsub in self._unsubscribers:
            unsub()
        self._unsubscribers.clear()
        await self._async_save()

    @callback
    def async_update_listeners(self) -> None:
        self.last_updated = dt_util.now()
        async_dispatcher_send(self.hass, self.signal)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _async_load(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        self.weight_kg = data.get("weight_kg")
        self.weight_source = data.get("weight_source", SOURCE_MANUAL)
        self.body_fat_pct = data.get("body_fat_pct")
        self.fat_mass_kg = data.get("fat_mass_kg")
        self._body_fat_from_fat_mass = data.get("body_fat_from_fat_mass", False)
        self.muscle_mass_kg = data.get("muscle_mass_kg")
        self.bone_mass_kg = data.get("bone_mass_kg")
        self.water_pct = data.get("water_pct")
        self.scale_bmi = data.get("scale_bmi")
        self.sessions = data.get("sessions", [])
        self.history = data.get("history", {})
        self.correction_factor = data.get(
            "correction_factor", self._conf(CONF_CORRECTION_FACTOR, DEFAULT_CORRECTION_FACTOR)
        )
        if last_measurement := data.get("last_measurement"):
            self.last_measurement = dt_util.parse_datetime(last_measurement)
        if last_reset := data.get("last_reset"):
            parsed = dt_util.parse_date(last_reset)
            if parsed:
                self.last_reset = parsed
        self.weight_readings = [
            (parsed_ts, reading["kg"])
            for reading in data.get("weight_readings", [])
            if (parsed_ts := dt_util.parse_datetime(reading["ts"])) is not None
        ]

    async def _async_save(self) -> None:
        await self._store.async_save(self._as_dict())

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._as_dict, 10)

    def _as_dict(self) -> dict[str, Any]:
        return {
            "weight_kg": self.weight_kg,
            "weight_source": self.weight_source,
            "body_fat_pct": self.body_fat_pct,
            "fat_mass_kg": self.fat_mass_kg,
            "body_fat_from_fat_mass": self._body_fat_from_fat_mass,
            "muscle_mass_kg": self.muscle_mass_kg,
            "bone_mass_kg": self.bone_mass_kg,
            "water_pct": self.water_pct,
            "scale_bmi": self.scale_bmi,
            "sessions": self.sessions,
            "history": self.history,
            "correction_factor": self.correction_factor,
            "last_measurement": self.last_measurement.isoformat()
            if self.last_measurement
            else None,
            "last_reset": self.last_reset.isoformat(),
            "weight_readings": [
                {"ts": ts.isoformat(), "kg": kg} for ts, kg in self.weight_readings
            ],
        }

    # ------------------------------------------------------------------
    # Smart scale handling
    # ------------------------------------------------------------------

    def _subscribe_scale_entities(self) -> None:
        mapping = {
            CONF_WEIGHT_ENTITY: self._handle_weight_event,
            CONF_BODY_FAT_ENTITY: self._handle_body_fat_event,
            CONF_MUSCLE_MASS_ENTITY: self._handle_muscle_mass_event,
            CONF_BONE_MASS_ENTITY: self._handle_bone_mass_event,
            CONF_WATER_PCT_ENTITY: self._handle_water_event,
            CONF_BMI_ENTITY: self._handle_bmi_event,
        }
        for conf_key, handler in mapping.items():
            if entity_id := self._conf(conf_key):
                self._unsubscribers.append(
                    async_track_state_change_event(self.hass, [entity_id], handler)
                )

    def _seed_from_scale_entities(self) -> None:
        """Read current scale entity states once at startup."""
        if entity_id := self._conf(CONF_WEIGHT_ENTITY):
            if (value := self._numeric_state(entity_id)) is not None:
                state = self.hass.states.get(entity_id)
                unit = state.attributes.get("unit_of_measurement") if state else None
                self._apply_scale_weight(calc.convert_weight_to_kg(value, unit))
        if entity_id := self._conf(CONF_BODY_FAT_ENTITY):
            if (value := self._numeric_state(entity_id)) is not None:
                self._apply_body_fat_reading(value, self._state_unit(entity_id))
        for conf_key, attr in (
            (CONF_MUSCLE_MASS_ENTITY, "muscle_mass_kg"),
            (CONF_BONE_MASS_ENTITY, "bone_mass_kg"),
        ):
            if entity_id := self._conf(conf_key):
                if (value := self._numeric_state(entity_id)) is not None:
                    setattr(
                        self,
                        attr,
                        calc.convert_weight_to_kg(value, self._state_unit(entity_id)),
                    )
        for conf_key, attr in (
            (CONF_WATER_PCT_ENTITY, "water_pct"),
            (CONF_BMI_ENTITY, "scale_bmi"),
        ):
            if entity_id := self._conf(conf_key):
                if (value := self._numeric_state(entity_id)) is not None:
                    setattr(self, attr, value)

    def _state_unit(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        return state.attributes.get("unit_of_measurement") if state else None

    def _numeric_state(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _event_value(event: Event) -> tuple[float | None, str | None]:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None, None
        try:
            value = float(new_state.state)
        except (TypeError, ValueError):
            return None, None
        return value, new_state.attributes.get("unit_of_measurement")

    @callback
    def _handle_weight_event(self, event: Event) -> None:
        value, unit = self._event_value(event)
        if value is None:
            # Entity became unavailable/unknown: retain last valid value.
            if self.weight_kg is not None:
                self.weight_source = SOURCE_LAST_KNOWN
                self.async_update_listeners()
            return
        self._apply_scale_weight(calc.convert_weight_to_kg(value, unit))
        if self._body_fat_from_fat_mass:
            # Body fat came from a fat-mass entity: keep % in sync with weight.
            self._derive_percent_from_fat_mass()
        self._check_staleness()
        self._schedule_save()
        self.async_update_listeners()

    def _apply_scale_weight(self, weight_kg: float) -> None:
        now = dt_util.now()
        self.weight_kg = weight_kg
        self.weight_source = SOURCE_SMART_SCALE
        self.last_measurement = now
        self._stale_notified = False
        self.weight_readings.append((now, weight_kg))
        # Keep only the smoothing window (plus a small margin).
        cutoff = now - timedelta(days=self.smoothing_window_days + 1)
        self.weight_readings = [(ts, kg) for ts, kg in self.weight_readings if ts >= cutoff]

    @callback
    def _handle_body_fat_event(self, event: Event) -> None:
        value, unit = self._event_value(event)
        if value is None:
            return
        if not self._apply_body_fat_reading(value, unit):
            return
        self._schedule_save()
        self.async_update_listeners()

    def _apply_body_fat_reading(self, value: float, unit: str | None) -> bool:
        """Apply a body fat reading that may be a percentage or a fat mass.

        Scales such as Withings and Xiaomi report fat *mass* (kg/lb) rather
        than a percentage; the unit of measurement decides how the value is
        interpreted. Returns True when state changed.
        """
        if calc.is_mass_unit(unit):
            fat_mass_kg = calc.convert_weight_to_kg(value, unit)
            self.fat_mass_kg = fat_mass_kg
            self._body_fat_from_fat_mass = True
            return self._derive_percent_from_fat_mass()
        if not calc.is_valid_body_fat(value):
            _LOGGER.warning(
                "Ignoring body fat reading %.1f%% outside the plausible %s-%s%% range",
                value,
                BODY_FAT_MIN,
                BODY_FAT_MAX,
            )
            return False
        self.body_fat_pct = value
        self._body_fat_from_fat_mass = False
        return True

    def _derive_percent_from_fat_mass(self) -> bool:
        """Recompute body fat % from the stored fat mass and current weight."""
        if self.fat_mass_kg is None or self.weight_kg is None:
            _LOGGER.debug("Fat mass received but no weight available yet")
            return False
        percent = calc.fat_mass_to_percent(self.fat_mass_kg, self.weight_kg)
        if percent is None or not calc.is_valid_body_fat(percent):
            _LOGGER.warning(
                "Derived body fat %s%% from fat mass %.1f kg / weight %.1f kg "
                "is implausible; ignoring",
                f"{percent:.1f}" if percent is not None else "?",
                self.fat_mass_kg,
                self.weight_kg,
            )
            return False
        self.body_fat_pct = percent
        return True

    @callback
    def _handle_muscle_mass_event(self, event: Event) -> None:
        value, unit = self._event_value(event)
        if value is None:
            return
        self.muscle_mass_kg = calc.convert_weight_to_kg(value, unit)
        self._schedule_save()
        self.async_update_listeners()

    @callback
    def _handle_bone_mass_event(self, event: Event) -> None:
        value, unit = self._event_value(event)
        if value is None:
            return
        self.bone_mass_kg = calc.convert_weight_to_kg(value, unit)
        self._schedule_save()
        self.async_update_listeners()

    @callback
    def _handle_water_event(self, event: Event) -> None:
        value, _ = self._event_value(event)
        if value is None:
            return
        self.water_pct = value
        self._schedule_save()
        self.async_update_listeners()

    @callback
    def _handle_bmi_event(self, event: Event) -> None:
        value, _ = self._event_value(event)
        if value is None:
            return
        self.scale_bmi = value
        self._schedule_save()
        self.async_update_listeners()

    def _check_staleness(self) -> None:
        if not self._conf(CONF_SCALE_ENABLED) or not self._conf(CONF_WEIGHT_ENTITY):
            return
        if self.last_measurement is None:
            return
        if self.weight_data_stale and not self._stale_notified:
            self._stale_notified = True
            threshold = self.stale_threshold_days
            persistent_notification.async_create(
                self.hass,
                f"Your smart scale has not reported a weight in over {threshold} "
                f"days. Calorie Tracker is still using the last known weight "
                f"({self.weight_kg:.1f} kg).",
                title="Calorie Tracker: scale data is stale",
                notification_id=f"{DOMAIN}_stale_weight",
            )

    # ------------------------------------------------------------------
    # Peloton handling
    # ------------------------------------------------------------------

    def _subscribe_peloton_entities(self) -> None:
        if workout_entity := self._conf(CONF_PELOTON_WORKOUT_ENTITY):
            self._unsubscribers.append(
                async_track_state_change_event(
                    self.hass, [workout_entity], self._handle_peloton_workout_event
                )
            )
        elif calories_entity := self._conf(CONF_PELOTON_CALORIES_ENTITY):
            # No workout-state entity mapped: fall back to logging a session
            # whenever the calories sensor settles on a new value.
            self._unsubscribers.append(
                async_track_state_change_event(
                    self.hass, [calories_entity], self._handle_peloton_calories_event
                )
            )

    @callback
    def _handle_peloton_workout_event(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        is_active = new_state.state.lower() in _ACTIVE_WORKOUT_STATES
        if is_active:
            self._peloton_workout_active = True
            return
        # Workout just ended: capture calories/duration from mapped sensors.
        if self._peloton_workout_active:
            self._peloton_workout_active = False
            self._record_peloton_session(new_state.attributes)

    @callback
    def _handle_peloton_calories_event(self, event: Event) -> None:
        value, _ = self._event_value(event)
        old_state = event.data.get("old_state")
        if value is None or value <= 0:
            return
        # Only log when the value actually changes to avoid duplicates from
        # attribute-only updates.
        if old_state is not None:
            try:
                if float(old_state.state) == value:
                    return
            except (TypeError, ValueError):
                pass
        self._record_peloton_session({})

    def _record_peloton_session(self, workout_attributes: dict[str, Any]) -> None:
        gross = self._numeric_state(self._conf(CONF_PELOTON_CALORIES_ENTITY) or "")
        duration = self._numeric_state(self._conf(CONF_PELOTON_DURATION_ENTITY) or "")
        if gross is None:
            gross = workout_attributes.get("total_calories") or workout_attributes.get(
                "calories"
            )
        if duration is None:
            duration = workout_attributes.get("duration_min") or workout_attributes.get(
                "duration"
            )
        if gross is None:
            _LOGGER.warning("Peloton workout ended but no calorie value was available")
            return
        gross = float(gross)
        duration = float(duration or 0)
        hr_connected = False
        if hr_entity := self._conf(CONF_PELOTON_HR_ENTITY):
            hr_connected = self._numeric_state(hr_entity) is not None
        workout_type = str(
            workout_attributes.get("workout_type")
            or workout_attributes.get("fitness_discipline")
            or "peloton_workout"
        )
        self.add_session(
            activity_type=workout_type,
            duration_minutes=duration,
            gross_kcal=gross,
            source=EXERCISE_SOURCE_PELOTON,
            hr_monitor=hr_connected,
        )

    # ------------------------------------------------------------------
    # Exercise logging (shared by Peloton + services)
    # ------------------------------------------------------------------

    def add_session(
        self,
        activity_type: str,
        duration_minutes: float,
        gross_kcal: float,
        source: str,
        hr_monitor: bool = False,
        apply_correction: bool | None = None,
    ) -> None:
        """Add an exercise session with a device-reported gross calorie value."""
        if apply_correction is None:
            apply_correction = source == EXERCISE_SOURCE_PELOTON
        factor = self.correction_factor if apply_correction else 1.0
        net = calc.net_exercise_kcal(gross_kcal, factor, self.rmr, duration_minutes)
        self.sessions.append(
            {
                "type": activity_type,
                "duration_minutes": round(duration_minutes, 1),
                "gross_kcal": round(gross_kcal, 1),
                "net_kcal": round(net, 1),
                "source": source,
                "hr_monitor": hr_monitor,
                "timestamp": dt_util.now().isoformat(),
            }
        )
        self._schedule_save()
        self.async_update_listeners()

    def log_manual_exercise(
        self,
        activity_type: str,
        duration_minutes: float,
        calories_override: float | None = None,
    ) -> None:
        """Log a manual session; MET-based unless a calorie override is given."""
        if calories_override is not None:
            self.add_session(
                activity_type=activity_type,
                duration_minutes=duration_minutes,
                gross_kcal=calories_override,
                source=EXERCISE_SOURCE_MANUAL,
                apply_correction=False,
            )
            return
        met = MET_VALUES.get(activity_type)
        if met is None:
            raise ValueError(
                f"Unknown activity_type '{activity_type}'. Known activities: "
                f"{', '.join(sorted(MET_VALUES))}. Alternatively pass an "
                "explicit 'calories' value."
            )
        weight = self.effective_weight_kg
        if weight is None:
            raise ValueError("Cannot compute MET calories: no weight is available")
        net = calc.met_net_kcal(met, weight, duration_minutes)
        gross = calc.met_gross_kcal(met, weight, duration_minutes)
        self.sessions.append(
            {
                "type": activity_type,
                "duration_minutes": round(duration_minutes, 1),
                "gross_kcal": round(gross, 1),
                "net_kcal": round(net, 1),
                "source": EXERCISE_SOURCE_MANUAL,
                "hr_monitor": False,
                "timestamp": dt_util.now().isoformat(),
            }
        )
        self._schedule_save()
        self.async_update_listeners()

    def set_correction_factor(self, factor: float) -> None:
        self.correction_factor = calc.clamp_correction_factor(factor)
        self._schedule_save()
        self.async_update_listeners()

    def log_weight(self, weight: float, unit: str | None = None) -> None:
        now = dt_util.now()
        weight_kg = calc.convert_weight_to_kg(weight, unit or self.display_unit)
        self.weight_kg = weight_kg
        self.weight_source = SOURCE_MANUAL
        self.last_measurement = now
        self.weight_readings.append((now, weight_kg))
        if self._body_fat_from_fat_mass:
            self._derive_percent_from_fat_mass()
        self._schedule_save()
        self.async_update_listeners()

    def log_body_fat(self, body_fat_pct: float) -> None:
        if not calc.is_valid_body_fat(body_fat_pct):
            raise ValueError(
                f"Body fat must be between {BODY_FAT_MIN} and {BODY_FAT_MAX} percent"
            )
        self.body_fat_pct = body_fat_pct
        self._body_fat_from_fat_mass = False
        self._schedule_save()
        self.async_update_listeners()

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    @callback
    def _handle_midnight(self, _now: datetime) -> None:
        self.hass.async_create_task(self._async_daily_reset())

    async def _async_daily_reset(self) -> None:
        """Archive the finished day's totals and clear session data.

        Weight and body composition persist; only exercise resets. A manual
        same-day reset discards today's sessions without archiving.
        """
        _LOGGER.debug("Running daily reset (previous day: %s)", self.last_reset)
        today = dt_util.now().date()
        if self.last_reset != today:
            self._archive_day(self.last_reset)
        self.sessions = []
        self.last_reset = today
        self._check_staleness()
        await self._async_save()
        self.async_update_listeners()

    def _archive_day(self, day: date) -> None:
        """Store the day's final totals for rolling averages."""
        self.history[day.isoformat()] = {
            "exercise_gross": round(self.exercise_gross_kcal, 1),
            "exercise_net": round(self.exercise_net_kcal, 1),
            "tdee": round(self.tdee, 1),
            "sessions": self.exercise_count,
        }
        cutoff = (dt_util.now().date() - timedelta(days=HISTORY_RETENTION_DAYS)).isoformat()
        self.history = {d: v for d, v in self.history.items() if d >= cutoff}

    async def async_reset_daily(self) -> None:
        """Service-triggered manual reset."""
        await self._async_daily_reset()

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------

    @property
    def age(self) -> int | None:
        dob = self._conf(CONF_DATE_OF_BIRTH)
        if dob is None:
            return None
        if isinstance(dob, str):
            dob = dt_util.parse_date(dob)
        if dob is None:
            return None
        return calc.calculate_age(dob, dt_util.now().date())

    @property
    def display_unit(self) -> str:
        return self._conf(CONF_DISPLAY_UNIT, DEFAULT_DISPLAY_UNIT)

    @property
    def smoothing_enabled(self) -> bool:
        return self._conf(CONF_WEIGHT_SMOOTHING, DEFAULT_SMOOTHING) == SMOOTHING_ROLLING

    @property
    def smoothing_window_days(self) -> int:
        return SMOOTHING_WINDOW_DAYS

    @property
    def stale_threshold_days(self) -> int:
        return int(self._conf(CONF_STALE_THRESHOLD_DAYS, DEFAULT_STALE_THRESHOLD_DAYS))

    @property
    def raw_weight_kg(self) -> float | None:
        return self.weight_kg

    @property
    def effective_weight_kg(self) -> float | None:
        """Weight used in all calculations (smoothed when enabled)."""
        if self.smoothing_enabled:
            smoothed = calc.rolling_average_weight(
                self.weight_readings, dt_util.now(), self.smoothing_window_days
            )
            if smoothed is not None:
                return smoothed
        return self.weight_kg

    @property
    def weight_trend_kg(self) -> float | None:
        return calc.rolling_average_weight(
            self.weight_readings, dt_util.now(), self.smoothing_window_days
        )

    @property
    def weight_data_stale(self) -> bool:
        return calc.is_weight_stale(
            self.last_measurement, dt_util.now(), self.stale_threshold_days
        )

    @property
    def fat_free_mass_kg(self) -> float | None:
        weight = self.effective_weight_kg
        if weight is None or self.body_fat_pct is None:
            return None
        return calc.fat_free_mass(weight, self.body_fat_pct)

    @property
    def rmr_equation(self) -> str:
        equation = self._conf(CONF_RMR_EQUATION, DEFAULT_RMR_EQUATION)
        # Cunningham needs body composition; fall back gracefully if it is
        # configured but no body fat data has ever arrived.
        if equation == EQUATION_CUNNINGHAM and self.fat_free_mass_kg is None:
            return EQUATION_MIFFLIN
        return equation

    @property
    def rmr(self) -> float:
        """Resting Metabolic Rate in kcal/day (0.0 when weight is missing)."""
        weight = self.effective_weight_kg
        height = self._conf(CONF_HEIGHT_CM)
        age = self.age
        sex = self._conf(CONF_SEX)
        equation = self.rmr_equation
        if equation == EQUATION_CUNNINGHAM:
            ffm = self.fat_free_mass_kg
            if ffm is not None:
                return calc.cunningham(ffm)
            equation = EQUATION_MIFFLIN
        if weight is None or height is None or age is None or sex is None:
            _LOGGER.debug("Missing profile data; RMR unavailable")
            return 0.0
        if equation == EQUATION_HARRIS:
            return calc.harris_benedict(weight, float(height), age, sex)
        return calc.mifflin_st_jeor(weight, float(height), age, sex)

    @property
    def pal_factor(self) -> float:
        level = self._conf(CONF_ACTIVITY_LEVEL, DEFAULT_ACTIVITY_LEVEL)
        return ACTIVITY_LEVELS.get(level, ACTIVITY_LEVELS[DEFAULT_ACTIVITY_LEVEL])

    @property
    def base_daily_kcal(self) -> float:
        return self.rmr * self.pal_factor

    @property
    def exercise_gross_kcal(self) -> float:
        return sum(session["gross_kcal"] for session in self.sessions)

    @property
    def exercise_net_kcal(self) -> float:
        return sum(session["net_kcal"] for session in self.sessions)

    @property
    def exercise_count(self) -> int:
        return len(self.sessions)

    @property
    def tdee(self) -> float:
        return self.base_daily_kcal + self.exercise_net_kcal

    def _exercise_net_average(self, window_days: int) -> tuple[float, int]:
        history = {
            day: values["exercise_net"] for day, values in self.history.items()
        }
        return calc.rolling_daily_average(
            history, self.exercise_net_kcal, dt_util.now().date(), window_days
        )

    def tdee_rolling_avg(self, window_days: int) -> float:
        """Base expenditure plus average daily net exercise over the window."""
        average_net, _ = self._exercise_net_average(window_days)
        return self.base_daily_kcal + average_net

    def rolling_days_of_data(self, window_days: int) -> int:
        _, days = self._exercise_net_average(window_days)
        return days

    @property
    def tdee_7d_avg(self) -> float:
        return self.tdee_rolling_avg(7)

    @property
    def tdee_30d_avg(self) -> float:
        return self.tdee_rolling_avg(30)

    @property
    def goal(self) -> str:
        return self._conf(CONF_GOAL, DEFAULT_GOAL)

    @property
    def budget_mode(self) -> str:
        return self._conf(CONF_BUDGET_MODE, DEFAULT_BUDGET_MODE)

    @property
    def budget_tdee(self) -> float:
        """The TDEE figure the daily budget is derived from."""
        mode = self.budget_mode
        if mode == BUDGET_MODE_7D:
            return self.tdee_7d_avg
        if mode == BUDGET_MODE_30D:
            return self.tdee_30d_avg
        return self.tdee

    @property
    def daily_budget(self) -> float:
        return self.budget_tdee + GOAL_OFFSETS.get(self.goal, 0)

    @property
    def protein_target_g(self) -> float | None:
        weight = self.effective_weight_kg
        if weight is None:
            return None
        multiplier = float(self._conf(CONF_PROTEIN_MULTIPLIER, DEFAULT_PROTEIN_MULTIPLIER))
        return weight * multiplier

    @property
    def tef_percentage(self) -> float:
        return float(self._conf(CONF_TEF_PERCENTAGE, DEFAULT_TEF_PERCENTAGE))

    @property
    def bmi(self) -> float | None:
        if self.scale_bmi is not None:
            return self.scale_bmi
        weight = self.effective_weight_kg
        height = self._conf(CONF_HEIGHT_CM)
        if weight is None or not height:
            return None
        return calc.body_mass_index(weight, float(height))

    @property
    def body_composition_available(self) -> bool:
        return self.body_fat_pct is not None
