from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)
PARIS_TZ = ZoneInfo("Europe/Paris")


def _parse_datetime(value):
    if not value:
        return None
    try:
        text = str(value).strip()
        if len(text) == 15 and "T" in text:
            return datetime.strptime(text, "%Y%m%dT%H%M%S").replace(
                tzinfo=PARIS_TZ
            ).astimezone(timezone.utc)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=PARIS_TZ)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _departure_delay(section):
    actual = _parse_datetime(section.get("departure_date_time"))
    scheduled = _parse_datetime(section.get("base_departure_date_time"))

    if not actual or not scheduled:
        stop_times = section.get("stop_date_times", []) or []
        if stop_times:
            first_stop = stop_times[0] or {}
            actual = actual or _parse_datetime(
                first_stop.get("departure_date_time")
                or first_stop.get("arrival_date_time")
            )
            scheduled = scheduled or _parse_datetime(
                first_stop.get("base_departure_date_time")
                or first_stop.get("base_arrival_date_time")
            )

    if not actual or not scheduled:
        return None, scheduled

    delay = round((actual - scheduled).total_seconds() / 60)
    return max(0, delay), scheduled


class MyTransilienCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.entry = entry
        self.session = async_get_clientsession(hass)
        self.api_key = entry.data.get(CONF_API_KEY)
        self.max_trains = entry.data.get(CONF_MAX_TRAINS, DEFAULT_MAX_TRAINS)
        self.tomorrow_start_hour = entry.data.get(
            CONF_TOMORROW_START_HOUR,
            DEFAULT_TOMORROW_START_HOUR,
        )
        self.tomorrow_duration_hours = entry.data.get(
            CONF_TOMORROW_DURATION_HOURS,
            DEFAULT_TOMORROW_DURATION_HOURS,
        )
        self.origin = entry.data.get(CONF_ORIGIN)
        self.origin_id = entry.data.get(CONF_ORIGIN_ID)
        self.destination = entry.data.get(CONF_DESTINATION)
        self.destination_id = entry.data.get(CONF_DESTINATION_ID)

    @property
    def headers(self):
        return {
            "Accept": "application/json",
            "apikey": self.api_key,
            "User-Agent": "MyTransilien-HomeAssistant/1.2.0",
        }

    async def _get_json(self, url, *, params=None):
        async with self.session.get(
            url,
            params=params,
            headers=self.headers,
            timeout=25,
        ) as response:
            response.raise_for_status()
            return await response.json()

    async def _async_update_data(self):
        if not all(
            (
                self.api_key,
                self.origin,
                self.origin_id,
                self.destination,
                self.destination_id,
            )
        ):
            raise UpdateFailed(
                "Configuration de trajet incomplète. "
                "Supprimez puis recréez cette entrée MyTransilien."
            )

        try:
            now = datetime.now(PARIS_TZ)
            journeys = await self._fetch_route_journeys(now, "realtime")
            if journeys:
                return self._result(journeys, "realtime", "Prochains trajets")

            tomorrow = (now + timedelta(days=1)).replace(
                hour=self.tomorrow_start_hour,
                minute=0,
                second=0,
                microsecond=0,
            )
            scheduled = await self._fetch_route_journeys(
                tomorrow,
                "base_schedule",
                end=tomorrow + timedelta(hours=self.tomorrow_duration_hours),
            )
            return self._result(scheduled, "schedule", "Horaires prévus")
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Erreur PRIM: {err}") from err

    def _result(self, journeys, mode, label):
        return {
            "trains": journeys,
            "mode": mode,
            "source": "PRIM Navitia",
            "label": label,
            "origin": self.origin,
            "destination": self.destination,
        }

    async def _fetch_route_journeys(
        self,
        start: datetime,
        freshness: str,
        end: datetime | None = None,
    ):
        payload = await self._get_json(
            f"{PRIM_NAVITIA_BASE}/journeys",
            params={
                "from": self.origin_id,
                "to": self.destination_id,
                "datetime": start.strftime("%Y%m%dT%H%M%S"),
                "datetime_represents": "departure",
                "data_freshness": freshness,
                "count": max(self.max_trains * 2, 10),
            },
        )

        now_utc = datetime.now(timezone.utc)
        end_utc = end.astimezone(timezone.utc) if end else None
        results = []
        seen = set()

        for journey in payload.get("journeys", []) or []:
            sections = [
                section
                for section in (journey.get("sections", []) or [])
                if section.get("type") == "public_transport"
            ]
            if not sections:
                continue

            departure = _parse_datetime(journey.get("departure_date_time"))
            arrival = _parse_datetime(journey.get("arrival_date_time"))
            if not departure or not arrival:
                continue
            if freshness == "realtime" and departure < now_utc:
                continue
            if end_utc and departure > end_utc:
                continue

            key = (departure.isoformat(), arrival.isoformat())
            if key in seen:
                continue
            seen.add(key)

            lines = []
            directions = []
            modes = []
            for section in sections:
                display = section.get("display_informations", {}) or {}
                code = str(display.get("code") or "").strip()
                name = str(display.get("name") or "").strip()
                commercial_mode = str(
                    display.get("commercial_mode") or ""
                ).strip()
                direction = str(display.get("direction") or "").strip()

                line = code or name
                if commercial_mode and line:
                    line = f"{commercial_mode} {line}"
                if line and line not in lines:
                    lines.append(line)
                if direction and direction not in directions:
                    directions.append(direction)
                if commercial_mode and commercial_mode not in modes:
                    modes.append(commercial_mode)

            delay_minutes, scheduled_departure = _departure_delay(sections[0])
            scheduled_local = (
                scheduled_departure.astimezone(PARIS_TZ)
                if scheduled_departure
                else None
            )
            local_departure = departure.astimezone(PARIS_TZ)
            local_arrival = arrival.astimezone(PARIS_TZ)

            duration_seconds = journey.get("duration")
            if duration_seconds is None:
                duration_seconds = int((arrival - departure).total_seconds())

            results.append(
                {
                    "expected": departure.isoformat(),
                    "arrival": arrival.isoformat(),
                    "time": local_departure.strftime("%H:%M"),
                    "arrival_time": local_arrival.strftime("%H:%M"),
                    "origin": self.origin,
                    "destination": self.destination,
                    "lines": lines,
                    "directions": directions,
                    "transport_modes": modes,
                    "duration_minutes": max(0, round(duration_seconds / 60)),
                    "transfers": int(journey.get("nb_transfers") or 0),
                    "status": (
                        "scheduled"
                        if freshness == "base_schedule"
                        else (
                            "delayed"
                            if (delay_minutes or 0) > 0
                            else "onTime"
                        )
                    ),
                    "delay_minutes": (
                        None
                        if freshness == "base_schedule"
                        else delay_minutes
                    ),
                    "scheduled": (
                        scheduled_departure.isoformat()
                        if scheduled_departure
                        else None
                    ),
                    "scheduled_time": (
                        scheduled_local.strftime("%H:%M")
                        if scheduled_local
                        else None
                    ),
                    "minutes": (
                        max(
                            0,
                            int(
                                (departure - now_utc).total_seconds()
                                // 60
                            ),
                        )
                        if freshness == "realtime"
                        else None
                    ),
                    "platform": None,
                    "mode": (
                        "schedule"
                        if freshness == "base_schedule"
                        else "realtime"
                    ),
                }
            )

        results.sort(key=lambda item: item["expected"])
        return results[: self.max_trains]
