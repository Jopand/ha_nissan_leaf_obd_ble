"""Button platform for Nissan Leaf OBD BLE."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NAME
from .entity import NissanLeafObdBleEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the manual OBD refresh button."""
    async_add_entities(
        [NissanLeafRefreshButton(hass.data[DOMAIN][entry.entry_id], entry)]
    )


class NissanLeafRefreshButton(NissanLeafObdBleEntity, ButtonEntity):
    """Request a complete OBD refresh through the coordinator."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialise the refresh button."""
        super().__init__(coordinator, config_entry)
        self._attr_name = f"{NAME} Refresh OBD"
        self._attr_unique_id = f"{config_entry.data[CONF_ADDRESS]}-refresh_obd"

    @property
    def unique_id(self) -> str:
        """Return a stable registry ID independent of the button name."""
        return self._attr_unique_id

    async def async_press(self) -> None:
        """Request the same complete refresh used by polling and discovery."""
        await self.coordinator.async_request_refresh()
