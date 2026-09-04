from __future__ import annotations

import unicodedata

import voluptuous as vol
from aiohttp import ClientResponseError

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_KEY,
    CONF_DESTINATION,
    CONF_DESTINATION_ID,
    CONF_MAX_TRAINS,
    CONF_ORIGIN,
    CONF_ORIGIN_ID,
    CONF_TOMORROW_DURATION_HOURS,
    CONF_TOMORROW_START_HOUR,
    DEFAULT_MAX_TRAINS,
    DEFAULT_TOMORROW_DURATION_HOURS,
    DEFAULT_TOMORROW_START_HOUR,
    DOMAIN,
    PRIM_NAVITIA_BASE,
)


def _norm(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(value.upper().split())


async def _resolve_stop_area(session, api_key: str, query: str):
    headers = {"Accept": "application/json", "apikey": api_key}
    async with session.get(
        f"{PRIM_NAVITIA_BASE}/places",
        params={"q": query, "type[]": "stop_area", "count": 10},
        headers=headers,
        timeout=20,
    ) as response:
        response.raise_for_status()
        payload = await response.json()

    candidates = []
    for place in payload.get("places", []) or []:
        stop = place.get("stop_area") or {}
        stop_id = stop.get("id")
        name = stop.get("name") or place.get("name")
        if stop_id and name:
            candidates.append((stop_id, name))

    if not candidates:
        return None

    wanted = _norm(query)
    for candidate in candidates:
        if _norm(candidate[1]) == wanted:
            return candidate
    for candidate in candidates:
        if wanted in _norm(candidate[1]):
            return candidate
    return candidates[0]


class MyTransilienConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        shared_api_key = next(
            (
                entry.data.get(CONF_API_KEY)
                for entry in existing_entries
                if entry.data.get(CONF_API_KEY)
            ),
            None,
        )

        if user_input is not None:
            api_key = (shared_api_key or user_input.get(CONF_API_KEY) or "").strip()
            origin_query = user_input[CONF_ORIGIN].strip()
            destination_query = user_input[CONF_DESTINATION].strip()

            try:
                session = async_get_clientsession(self.hass)
                origin = await _resolve_stop_area(session, api_key, origin_query)
                destination = await _resolve_stop_area(
                    session, api_key, destination_query
                )
            except ClientResponseError as err:
                if err.status == 401:
                    errors["base"] = "invalid_auth"
                elif err.status == 403:
                    errors["base"] = "api_forbidden"
                elif err.status == 429:
                    errors["base"] = "quota_exceeded"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                if origin is None:
                    errors[CONF_ORIGIN] = "station_not_found"
                if destination is None:
                    errors[CONF_DESTINATION] = "station_not_found"
                if origin and destination and origin[0] == destination[0]:
                    errors["base"] = "same_station"

                if not errors:
                    origin_id, origin_name = origin
                    destination_id, destination_name = destination
                    await self.async_set_unique_id(f"{origin_id}>{destination_id}")
                    self._abort_if_unique_id_configured()

                    data = dict(user_input)
                    data[CONF_API_KEY] = api_key
                    data[CONF_ORIGIN] = origin_name
                    data[CONF_ORIGIN_ID] = origin_id
                    data[CONF_DESTINATION] = destination_name
                    data[CONF_DESTINATION_ID] = destination_id

                    return self.async_create_entry(
                        title=f"{origin_name} → {destination_name}",
                        data=data,
                    )

        schema = {}
        if not shared_api_key:
            schema[vol.Required(CONF_API_KEY)] = str
        schema[vol.Required(CONF_ORIGIN)] = str
        schema[vol.Required(CONF_DESTINATION)] = str
        schema[vol.Optional(CONF_MAX_TRAINS, default=DEFAULT_MAX_TRAINS)] = vol.All(
            vol.Coerce(int), vol.Range(min=1, max=10)
        )
        schema[
            vol.Optional(
                CONF_TOMORROW_START_HOUR,
                default=DEFAULT_TOMORROW_START_HOUR,
            )
        ] = vol.All(vol.Coerce(int), vol.Range(min=0, max=12))
        schema[
            vol.Optional(
                CONF_TOMORROW_DURATION_HOURS,
                default=DEFAULT_TOMORROW_DURATION_HOURS,
            )
        ] = vol.All(vol.Coerce(int), vol.Range(min=1, max=12))

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema),
            errors=errors,
        )
