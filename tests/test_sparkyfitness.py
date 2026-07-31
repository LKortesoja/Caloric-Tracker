"""Unit tests for the SparkyFitness client.

The client takes an injected session object, so these tests use a small
fake implementing the aiohttp request interface — no network, no aiohttp
dependency, and plain asyncio.run() instead of pytest-asyncio.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timezone
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "custom_components" / "calorie_tracker")
)

import sparkyfitness as sf  # noqa: E402


class FakeResponse:
    def __init__(self, status: int = 200, json_data=None, json_error: bool = False):
        self.status = status
        self._json_data = json_data
        self._json_error = json_error

    async def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Duck-typed aiohttp session recording requests."""

    def __init__(self, responses=None, exception: Exception | None = None):
        self.responses = list(responses or [])
        self.exception = exception
        self.requests: list[dict] = []

    def request(self, method, url, params=None, json=None, **kwargs):
        self.requests.append(
            {"method": method, "url": url, "params": params, "json": json, **kwargs}
        )
        if self.exception is not None:
            raise self.exception
        return self.responses.pop(0)


def make_client(session, **kwargs) -> sf.SparkyFitnessClient:
    defaults = dict(
        base_url="http://sparky.local:3004",
        api_key="secret-key",
        user_id=None,
        verify_ssl=True,
    )
    defaults.update(kwargs)
    return sf.SparkyFitnessClient(session, **defaults)


DAY = date(2026, 7, 31)

HAPPY_ENTRY = {
    "id": 101,
    "meal_type": "breakfast",
    "food_name": "Oatmeal",
    "calories": 300,
    "protein": 10,
    "carbs": 54,
    "fat": 5,
    "fiber": 8,
    "logged_at": "2026-07-31T07:30:00+00:00",
}


# ---------------------------------------------------------------------------
# Happy path and normalization
# ---------------------------------------------------------------------------


def test_happy_path_fetch():
    session = FakeSession([FakeResponse(200, [HAPPY_ENTRY])])
    entries = asyncio.run(make_client(session).async_get_food_diary(DAY, timezone.utc))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.entry_id == "101"
    assert entry.meal == "breakfast"
    assert entry.meal_inferred is False
    assert entry.calories == 300
    assert entry.protein_g == 10
    assert entry.macros_complete is True
    assert entry.timestamp.tzinfo is not None
    # Auth headers sent
    assert session.requests[0]["headers"]["Authorization"] == "Bearer secret-key"


def test_wrapped_payload_and_nested_keys():
    raw = {
        "entry_id": "abc",
        "food": {"name": "Chicken"},
        "nutrients": {"calories": 400, "protein": 45},
        "logged_at": "2026-07-31T12:15:00+00:00",
    }
    session = FakeSession([FakeResponse(200, {"entries": [raw]})])
    entries = asyncio.run(make_client(session).async_get_food_diary(DAY, timezone.utc))
    assert entries[0].food_name == "Chicken"
    assert entries[0].calories == 400
    # meal absent -> inferred from 12:15 timestamp
    assert entries[0].meal == "lunch"
    assert entries[0].meal_inferred is True


def test_missing_macros_stay_none():
    raw = {"id": 1, "calories": 250, "meal_type": "snack"}
    session = FakeSession([FakeResponse(200, [raw])])
    entries = asyncio.run(make_client(session).async_get_food_diary(DAY, timezone.utc))
    assert entries[0].protein_g is None
    assert entries[0].carbs_g is None
    assert entries[0].fat_g is None
    assert entries[0].macros_complete is False


def test_mid_day_deletion_replaces_list():
    """Each poll returns the full day; deletions upstream shrink the list."""
    client_session = FakeSession(
        [
            FakeResponse(200, [HAPPY_ENTRY, {**HAPPY_ENTRY, "id": 102}]),
            FakeResponse(200, [HAPPY_ENTRY]),
        ]
    )
    client = make_client(client_session)
    first = asyncio.run(client.async_get_food_diary(DAY, timezone.utc))
    second = asyncio.run(client.async_get_food_diary(DAY, timezone.utc))
    assert len(first) == 2
    assert len(second) == 1


def test_user_id_param_forwarded():
    session = FakeSession([FakeResponse(200, [])])
    asyncio.run(
        make_client(session, user_id="u42").async_get_food_diary(DAY, timezone.utc)
    )
    assert session.requests[0]["params"]["user_id"] == "u42"


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------


def test_401_raises_auth_error():
    session = FakeSession([FakeResponse(401)])
    with pytest.raises(sf.SparkyFitnessAuthError):
        asyncio.run(make_client(session).async_get_food_diary(DAY, timezone.utc))


def test_500_raises_connection_error():
    session = FakeSession([FakeResponse(500)])
    with pytest.raises(sf.SparkyFitnessConnectionError):
        asyncio.run(make_client(session).async_get_food_diary(DAY, timezone.utc))


def test_malformed_json_raises_schema_error():
    session = FakeSession([FakeResponse(200, json_error=True)])
    with pytest.raises(sf.SparkyFitnessSchemaError):
        asyncio.run(make_client(session).async_get_food_diary(DAY, timezone.utc))


def test_non_list_payload_raises_schema_error():
    session = FakeSession([FakeResponse(200, {"unexpected": "shape"})])
    with pytest.raises(sf.SparkyFitnessSchemaError):
        asyncio.run(make_client(session).async_get_food_diary(DAY, timezone.utc))


def test_entry_without_calories_raises_schema_error():
    session = FakeSession([FakeResponse(200, [{"id": 1, "food_name": "?"}])])
    with pytest.raises(sf.SparkyFitnessSchemaError):
        asyncio.run(make_client(session).async_get_food_diary(DAY, timezone.utc))


def test_os_error_maps_to_connection_error():
    session = FakeSession(exception=ConnectionRefusedError("refused"))
    with pytest.raises(sf.SparkyFitnessConnectionError):
        asyncio.run(make_client(session).async_get_food_diary(DAY, timezone.utc))


def test_timeout_maps_to_connection_error():
    class HangingSession:
        def request(self, *args, **kwargs):
            class Hanging:
                async def __aenter__(self):
                    await asyncio.sleep(999)

                async def __aexit__(self, *exc):
                    return False

            return Hanging()

    original = sf.REQUEST_TIMEOUT_S
    sf.REQUEST_TIMEOUT_S = 0.05
    try:
        with pytest.raises(sf.SparkyFitnessConnectionError):
            asyncio.run(
                make_client(HangingSession()).async_get_food_diary(DAY, timezone.utc)
            )
    finally:
        sf.REQUEST_TIMEOUT_S = original


# ---------------------------------------------------------------------------
# Exercise write-back
# ---------------------------------------------------------------------------

SESSION_RECORD = {
    "type": "cycling",
    "duration_minutes": 30.0,
    "gross_kcal": 452.0,
    "net_kcal": 400.0,
    "timestamp": "2026-07-31T06:30:00-04:00",
}


def test_push_exercise_success():
    session = FakeSession([FakeResponse(200, {"id": 7})])
    pushed = asyncio.run(make_client(session).async_push_exercise(SESSION_RECORD))
    assert pushed is True
    payload = session.requests[0]["json"]
    assert payload["name"] == "cycling"
    assert payload["duration_minutes"] == 30.0
    assert payload["calories_burned"] == 400.0
    assert payload["entry_date"] == "2026-07-31"
    assert payload["external_id"] == sf.exercise_external_id(SESSION_RECORD)


def test_push_exercise_conflict_is_not_error():
    session = FakeSession([FakeResponse(409)])
    pushed = asyncio.run(make_client(session).async_push_exercise(SESSION_RECORD))
    assert pushed is False


def test_external_id_stable_and_distinct():
    assert sf.exercise_external_id(SESSION_RECORD) == sf.exercise_external_id(
        dict(SESSION_RECORD)
    )
    other = {**SESSION_RECORD, "timestamp": "2026-07-31T18:00:00-04:00"}
    assert sf.exercise_external_id(SESSION_RECORD) != sf.exercise_external_id(other)


# ---------------------------------------------------------------------------
# Cache restore shape (round-trip through as_dict)
# ---------------------------------------------------------------------------


def test_entry_dict_round_trip_shape():
    session = FakeSession([FakeResponse(200, [HAPPY_ENTRY])])
    entries = asyncio.run(make_client(session).async_get_food_diary(DAY, timezone.utc))
    stored = entries[0].as_dict()
    # The coordinator persists exactly this shape into .storage.
    for key in (
        "entry_id",
        "timestamp",
        "meal",
        "meal_inferred",
        "food_name",
        "calories",
        "protein_g",
        "carbs_g",
        "fat_g",
        "fiber_g",
    ):
        assert key in stored
