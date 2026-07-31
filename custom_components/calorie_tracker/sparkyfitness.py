"""Async client for a self-hosted SparkyFitness instance.

Design notes:
- The HTTP session is injected (Home Assistant's shared aiohttp session in
  production, a lightweight fake in unit tests), so this module has no HA
  imports and only optionally touches aiohttp for exception mapping.
- SparkyFitness resolves foods to nutrient values at logging time, so this
  client performs no food search, barcode lookup, or nutrient imputation.
- Upstream schema knowledge is isolated in ``normalize_entry``; if a
  SparkyFitness release changes its payload shape, that is the only
  function that should need editing (endpoint paths live in const.py).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, tzinfo
from typing import Any

try:  # aiohttp is always present inside Home Assistant
    import aiohttp
except ImportError:  # pragma: no cover - exercised only in bare test envs
    aiohttp = None  # type: ignore[assignment]

try:  # package context inside Home Assistant
    from .const import SPARKY_EXERCISE_PATH, SPARKY_FOOD_DIARY_PATH
except ImportError:  # direct import in unit tests
    from const import SPARKY_EXERCISE_PATH, SPARKY_FOOD_DIARY_PATH

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 15

MEALS = {"breakfast", "lunch", "dinner", "snack"}


class SparkyFitnessError(Exception):
    """Base error for SparkyFitness communication."""


class SparkyFitnessConnectionError(SparkyFitnessError):
    """Host unreachable or timed out."""


class SparkyFitnessSslError(SparkyFitnessConnectionError):
    """TLS certificate verification failed."""


class SparkyFitnessAuthError(SparkyFitnessError):
    """API key rejected (401/403)."""


class SparkyFitnessSchemaError(SparkyFitnessError):
    """Response did not match the expected payload shape."""


@dataclass(frozen=True)
class FoodEntry:
    """Normalized food diary entry."""

    entry_id: str
    timestamp: datetime  # timezone-aware
    meal: str  # breakfast | lunch | dinner | snack | unknown
    meal_inferred: bool
    food_name: str
    calories: float
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    fiber_g: float | None

    @property
    def macros_complete(self) -> bool:
        return (
            self.protein_g is not None
            and self.carbs_g is not None
            and self.fat_g is not None
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "meal": self.meal,
            "meal_inferred": self.meal_inferred,
            "food_name": self.food_name,
            "calories": self.calories,
            "protein_g": self.protein_g,
            "carbs_g": self.carbs_g,
            "fat_g": self.fat_g,
            "fiber_g": self.fiber_g,
        }


def _first(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _infer_meal_from_hour(hour: int) -> str:
    if hour < 10:
        return "breakfast"
    if hour < 15:
        return "lunch"
    if hour < 21:
        return "dinner"
    return "snack"


def normalize_entry(
    raw: dict[str, Any], day: date, tz: tzinfo | None
) -> FoodEntry:
    """Map one upstream diary record onto the stable FoodEntry shape.

    All upstream schema assumptions live here. Nested ``food`` /
    ``nutrients`` objects and several key aliases are tolerated; missing
    macros stay None — never imputed to 0.
    """
    nested_food = raw.get("food") if isinstance(raw.get("food"), dict) else {}
    nutrients = (
        raw.get("nutrients") if isinstance(raw.get("nutrients"), dict) else {}
    )
    merged = {**nutrients, **raw}

    entry_id = _first(raw, ("id", "entry_id", "uuid"))
    if entry_id is None:
        raise SparkyFitnessSchemaError(f"Diary entry has no id: {raw!r}")

    calories = _as_float(_first(merged, ("calories", "kcal", "energy")))
    if calories is None:
        raise SparkyFitnessSchemaError(
            f"Diary entry {entry_id} has no calorie value"
        )

    food_name = str(
        _first(raw, ("food_name", "name"))
        or nested_food.get("name")
        or "unknown food"
    )

    timestamp: datetime | None = None
    raw_ts = _first(raw, ("logged_at", "created_at", "timestamp", "entry_time"))
    if isinstance(raw_ts, str):
        try:
            timestamp = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except ValueError:
            timestamp = None
    if timestamp is None:
        timestamp = datetime.combine(day, time(hour=12))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=tz)

    meal_raw = _first(raw, ("meal_type", "meal"))
    meal_inferred = False
    meal = str(meal_raw).lower() if meal_raw is not None else ""
    if meal not in MEALS:
        if raw_ts is not None:
            meal = _infer_meal_from_hour(timestamp.hour)
            meal_inferred = True
        else:
            meal = "unknown"

    return FoodEntry(
        entry_id=str(entry_id),
        timestamp=timestamp,
        meal=meal,
        meal_inferred=meal_inferred,
        food_name=food_name,
        calories=calories,
        protein_g=_as_float(_first(merged, ("protein", "protein_g"))),
        carbs_g=_as_float(
            _first(merged, ("carbs", "carbohydrates", "carbs_g", "carbohydrates_g"))
        ),
        fat_g=_as_float(_first(merged, ("fat", "fat_g"))),
        fiber_g=_as_float(
            _first(merged, ("fiber", "fiber_g", "dietary_fiber"))
        ),
    )


def exercise_external_id(session: dict[str, Any]) -> str:
    """Stable dedupe id for a logged exercise session."""
    basis = (
        f"{session.get('type')}|{session.get('timestamp')}|"
        f"{session.get('gross_kcal')}|{session.get('duration_minutes')}"
    )
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


class SparkyFitnessClient:
    """Minimal async client for the SparkyFitness REST API."""

    def __init__(
        self,
        session: Any,
        base_url: str,
        api_key: str,
        user_id: str | None = None,
        verify_ssl: bool = True,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._user_id = user_id
        self._verify_ssl = verify_ssl

    @property
    def _headers(self) -> dict[str, str]:
        # Both header styles are sent for compatibility across versions.
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-Api-Key": self._api_key,
            "Accept": "application/json",
        }

    def _request_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"headers": self._headers}
        if not self._verify_ssl:
            kwargs["ssl"] = False
        return kwargs

    async def _request(
        self, method: str, path: str, params: dict | None = None, json: Any = None
    ) -> Any:
        url = f"{self._base_url}{path}"
        params = dict(params or {})
        if self._user_id:
            params.setdefault("user_id", self._user_id)
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_S):
                async with self._session.request(
                    method, url, params=params or None, json=json,
                    **self._request_kwargs(),
                ) as response:
                    if response.status in (401, 403):
                        raise SparkyFitnessAuthError(
                            f"SparkyFitness rejected the API key ({response.status})"
                        )
                    if response.status == 409:
                        return {"conflict": True}
                    if response.status >= 400:
                        raise SparkyFitnessConnectionError(
                            f"SparkyFitness returned HTTP {response.status} for {path}"
                        )
                    try:
                        return await response.json()
                    except Exception as err:
                        raise SparkyFitnessSchemaError(
                            f"Non-JSON response from {path}: {err}"
                        ) from err
        except SparkyFitnessError:
            raise
        except TimeoutError as err:
            raise SparkyFitnessConnectionError(
                f"Timeout talking to SparkyFitness at {url}"
            ) from err
        except Exception as err:
            if aiohttp is not None and isinstance(
                err, aiohttp.ClientConnectorCertificateError
            ):
                raise SparkyFitnessSslError(
                    f"TLS verification failed for {url}: {err}"
                ) from err
            if aiohttp is not None and isinstance(err, aiohttp.ClientError):
                raise SparkyFitnessConnectionError(
                    f"Cannot reach SparkyFitness at {url}: {err}"
                ) from err
            if isinstance(err, OSError):
                raise SparkyFitnessConnectionError(
                    f"Cannot reach SparkyFitness at {url}: {err}"
                ) from err
            raise

    async def async_validate(self) -> None:
        """Lightweight authenticated request used by the config flow."""
        await self.async_get_food_diary(date.today(), tz=None)

    async def async_get_food_diary(
        self, day: date, tz: tzinfo | None
    ) -> list[FoodEntry]:
        """Fetch and normalize the food diary for a local date.

        The full day's list replaces prior state on every poll, so mid-day
        edits and deletions upstream are reflected automatically.
        """
        payload = await self._request(
            "GET", SPARKY_FOOD_DIARY_PATH, params={"date": day.isoformat()}
        )
        if isinstance(payload, dict):
            for key in ("entries", "items", "data", "food_entries"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
        if not isinstance(payload, list):
            raise SparkyFitnessSchemaError(
                f"Unexpected food diary payload type: {type(payload).__name__}"
            )
        return [normalize_entry(raw, day, tz) for raw in payload]

    async def async_push_exercise(self, session_record: dict[str, Any]) -> bool:
        """Push a completed exercise session; True if written, False on conflict.

        The external id makes the push idempotent so a coordinator reload
        cannot duplicate entries upstream.
        """
        external_id = exercise_external_id(session_record)
        timestamp = str(session_record.get("timestamp", ""))
        payload = {
            "name": session_record.get("type", "workout"),
            "duration_minutes": session_record.get("duration_minutes", 0),
            "calories_burned": session_record.get("net_kcal", 0),
            "entry_date": timestamp[:10],
            "logged_at": timestamp,
            "source": "home_assistant_calorie_tracker",
            "external_id": external_id,
            "notes": f"Synced from Home Assistant Calorie Tracker ({external_id})",
        }
        result = await self._request("POST", SPARKY_EXERCISE_PATH, json=payload)
        if isinstance(result, dict) and result.get("conflict"):
            _LOGGER.debug("Exercise %s already exists upstream", external_id)
            return False
        return True
