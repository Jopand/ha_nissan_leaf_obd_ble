"""Sensor platform for Nissan Leaf OBD BLE (ha_nissan_leaf_obd_ble)."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_GENERATION, DOMAIN, GENERATION_AUTO, NAME
from .entity import NissanLeafObdBleEntity
from .generations import get_sensors_for_generation


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensor entities for the configured generation."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    generation = entry.data.get(CONF_GENERATION, GENERATION_AUTO)

    descriptions = get_sensors_for_generation(generation)
    async_add_entities(
        NissanLeafSensor(coordinator, entry, desc) for desc in descriptions
    )


class NissanLeafSensor(NissanLeafObdBleEntity, SensorEntity):
    """A single OBD sensor entity for the Nissan Leaf."""

    def __init__(
        self,
        coordinator,
        config_entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, config_entry)
        self.entity_description = description
        self._attr_name = f"{NAME} {description.name}"
        self._attr_unique_id = (
            f"{config_entry.data[CONF_ADDRESS]}-{description.key}"
        )

    @property
    def native_value(self):
        """Return the current sensor value from coordinator data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def unique_id(self) -> str:
        """Preserve the existing SOC registry identity after its display rename."""
        if self.entity_description.key == "state_of_charge":
            address = self.config_entry.data[CONF_ADDRESS]
            return f"{address}-{NAME} State of charge"
        return super().unique_id

    @property
    def icon(self) -> str | None:
        """Return the icon defined in the entity description."""
        return self.entity_description.icon
