"""Nissan Leaf OBD BLE — Home Assistant custom integration (ha_nissan_leaf_obd_ble).

Sets up one coordinator per config entry (one per OBD adapter / Leaf),
registers a Bluetooth callback so new polls are triggered immediately when
the adapter comes back into range, and forwards entries to entity platforms.
"""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.typing import ConfigType

from .py_nissan_leaf_obd_ble import NissanLeafObdBleApiClient

from .const import CONF_NOMINAL_AH, DOMAIN, STARTUP_MESSAGE, VERSION
from .coordinator import NissanLeafCoordinator
from .metrics import migrate_nominal_ah

__version__ = VERSION

PLATFORMS = [Platform.BUTTON, Platform.SENSOR]

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """YAML-based setup is not supported; only UI config flow is used."""
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy battery capacity references in existing entries."""
    if entry.version > 2:
        return False

    if entry.version < 2:
        options = dict(entry.options)
        old_nominal_ah = options.get(CONF_NOMINAL_AH)
        new_nominal_ah = migrate_nominal_ah(old_nominal_ah)
        if new_nominal_ah != old_nominal_ah:
            options[CONF_NOMINAL_AH] = new_nominal_ah
            _LOGGER.info(
                "Migrating battery capacity reference from %.2f Ah to %.2f Ah",
                old_nominal_ah,
                new_nominal_ah,
            )
        try:
            hass.config_entries.async_update_entry(
                entry, options=options, version=2
            )
        except TypeError:
            # Home Assistant 2023.6 does not yet accept the version keyword.
            entry.version = 2
            hass.config_entries.async_update_entry(entry, options=options)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an ha_nissan_leaf_obd_ble config entry."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    address: str = entry.data[CONF_ADDRESS]

    api = NissanLeafObdBleApiClient()

    coordinator = NissanLeafCoordinator(hass, entry, api)

    # Load persisted sensor data BEFORE the first refresh so sensors
    # immediately show their last known values (even if the car is away).
    await coordinator.async_load_persistent_data()
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Re-trigger a data refresh whenever the adapter reappears in BLE range
    @callback
    def _on_adapter_detected(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        _LOGGER.debug(
            "OBD adapter %s detected (%s) — scheduling refresh", address, change
        )
        hass.async_create_task(coordinator.async_request_refresh())

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _on_adapter_detected,
            {"address": address},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    # Apply updated options immediately when the user clicks "Configure"
    async def _on_options_updated(
        hass: HomeAssistant | None, entry: ConfigEntry
    ) -> None:
        coordinator.options = entry.options
        await coordinator.async_request_refresh()

    entry.async_on_unload(entry.add_update_listener(_on_options_updated))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry (called after options change that requires restart)."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
