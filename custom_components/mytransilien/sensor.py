from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MyTransilienCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    coordinator: MyTransilienCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            MyTransilienSummarySensor(coordinator, entry),
            MyTransilienNextTrainSensor(coordinator, entry),
        ]
    )


class MyTransilienBaseSensor(CoordinatorEntity[MyTransilienCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="PRIM / Île-de-France Mobilités",
            model="Trajet transports Île-de-France",
        )


class MyTransilienSummarySensor(MyTransilienBaseSensor):
    _attr_name = "Prochains trajets"
    _attr_icon = "mdi:train-car"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_trains"

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("trains", []))

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {
            "origin": data.get("origin", self.coordinator.origin),
            "destination": data.get("destination", self.coordinator.destination),
            "mode": data.get("mode"),
            "source": data.get("source"),
            "label": data.get("label"),
            "trains": data.get("trains", []),
        }


class MyTransilienNextTrainSensor(MyTransilienBaseSensor):
    _attr_name = "Prochain départ"
    _attr_icon = "mdi:train-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_next_train"

    @property
    def native_value(self):
        trains = (self.coordinator.data or {}).get("trains", [])
        if not trains:
            return None
        try:
            return datetime.fromisoformat(trains[0]["expected"])
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self):
        trains = (self.coordinator.data or {}).get("trains", [])
        if not trains:
            return {}
        journey = trains[0]
        return {
            "origin": journey.get("origin", self.coordinator.origin),
            "destination": journey.get("destination", self.coordinator.destination),
            "arrival": journey.get("arrival"),
            "arrival_time": journey.get("arrival_time"),
            "lines": journey.get("lines", []),
            "directions": journey.get("directions", []),
            "transport_modes": journey.get("transport_modes", []),
            "duration_minutes": journey.get("duration_minutes"),
            "transfers": journey.get("transfers"),
            "status": journey.get("status"),
            "delay_minutes": journey.get("delay_minutes"),
            "minutes": journey.get("minutes"),
            "platform": journey.get("platform"),
            "mode": journey.get("mode"),
        }
