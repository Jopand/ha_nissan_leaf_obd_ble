"""Data update coordinator with persistence for Nissan Leaf OBD BLE."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_GENERATION,
    CONF_NOMINAL_AH,
    DEFAULT_FAST_POLL,
    DEFAULT_FETCH_TIMEOUT,
    DEFAULT_NOMINAL_AH,
    DEFAULT_SLOW_POLL,
    DEFAULT_XS_POLL,
    DOMAIN,
    GENERATION_AUTO,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .generations import get_extra_commands_for_generation
from .metrics import merge_cached_values, normalize_metrics

_LOGGER = logging.getLogger(__name__)


class NissanLeafCoordinator(DataUpdateCoordinator):
    """Coordinator that fetches OBD data and persists it across HA restarts."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_FAST_POLL),
            always_update=False,
        )

        self._address: str = entry.data[CONF_ADDRESS]
        self._generation: str = entry.data.get(CONF_GENERATION, GENERATION_AUTO)
        self.api = api

        # Persistent cache — populated from storage before the first poll so
        # sensors immediately reflect the last known values after a restart.
        self._cache_data: dict[str, Any] = {}

        # Per-entry storage file so multiple Leaf devices stay independent.
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}"
        )

        # Get nominal battery capacity for SOH calculation
        options = entry.options or {}
        self._nominal_ah: float = options.get(CONF_NOMINAL_AH, DEFAULT_NOMINAL_AH)

        # Generation-specific extra_commands (e.g. ZE0 LBC decoder override, SOH)
        self._generation_extra_commands: dict = get_extra_commands_for_generation(
            self._generation, nominal_ah=self._nominal_ah
        )

        self._options: dict = {}
        self.options = entry.options or {}  # triggers the setter

    # ------------------------------------------------------------------
    # Options property — reconfigured live when the user adjusts settings
    # ------------------------------------------------------------------

    @property
    def options(self) -> dict:
        """Current configuration options."""
        return self._options

    @options.setter
    def options(self, value: dict) -> None:
        """Apply new options and recalculate poll intervals and decoders.
        
        When nominal_ah (battery capacity) changes, rebuild the LBC decoder
        so SOH calculations use the new value.
        """
        self._options = value
        self._fast_poll = int(value.get("fast_poll", DEFAULT_FAST_POLL))
        self._slow_poll = int(value.get("slow_poll", DEFAULT_SLOW_POLL))
        self._xs_poll = int(value.get("xs_poll", DEFAULT_XS_POLL))
        self._fetch_timeout = float(value.get("fetch_timeout", DEFAULT_FETCH_TIMEOUT))
        
        # Rebuild decoders if nominal_ah changed
        new_nominal_ah = value.get(CONF_NOMINAL_AH, DEFAULT_NOMINAL_AH)
        if new_nominal_ah != self._nominal_ah:
            _LOGGER.info(
                "Battery nominal Ah changed from %.2f to %.2f — rebuilding decoders",
                self._nominal_ah, new_nominal_ah
            )
            self._nominal_ah = new_nominal_ah
            self._generation_extra_commands: dict = get_extra_commands_for_generation(
                self._generation, nominal_ah=self._nominal_ah
            )
            self._normalize_metrics(self._cache_data)

    def _normalize_metrics(self, data: dict[str, Any]) -> bool:
        """Remove invalid odometer values and keep calculated SOH consistent."""
        odometer = data.get("odometer")
        changed = normalize_metrics(data, self._nominal_ah)
        if odometer is not None and "odometer" not in data:
            _LOGGER.warning("Discarding invalid odometer value: %s", odometer)
        return changed

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def async_load_persistent_data(self) -> None:
        """Load last-known sensor values from HA storage.

        Call this once during entry setup, before the first refresh.  The
        loaded data is used as the initial coordinator.data so that sensors
        are not 'unknown' while the car is away from home.
        """
        stored = await self._store.async_load()
        if stored and isinstance(stored, dict):
            self._cache_data = dict(stored)
            normalized = self._normalize_metrics(self._cache_data)
            _LOGGER.debug(
                "Loaded %d persisted sensor values for %s",
                len(stored),
                self._address,
            )
            if normalized:
                await self._async_save_cache()

    async def _async_save_cache(self) -> None:
        """Persist the current cache to storage."""
        try:
            await self._store.async_save(self._cache_data)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to persist sensor cache: %s", err)

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch fresh data from the OBD adapter.

        Returns the merged cache (persisted + live) so sensors always display
        a value.  New data from the car updates and re-saves the cache; if the
        device is unreachable or a poll fails, the previous values are returned
        unchanged so entities never flip to 'unavailable' because the dongle
        was asleep or momentarily busy.
        """
        address = self._address.upper()
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, address, connectable=True
        )

        if ble_device is None:
            reason = bluetooth.async_address_reachability_diagnostics(
                self.hass,
                address,
                bluetooth.BluetoothReachabilityIntent.CONNECTION,
            )
            _LOGGER.debug(
                "No connectable BLE route for %s: %s; using cached data "
                "(interval -> %ds)",
                self._address,
                reason,
                self._xs_poll,
            )
            self.update_interval = timedelta(seconds=self._xs_poll)
            # Return a copy so the coordinator's internal reference can't be
            # mutated externally.
            return dict(self._cache_data)

        try:
            new_data = await asyncio.wait_for(
                self.api.async_get_data(
                    ble_device=ble_device,
                    options=self._options,
                    generation=self._generation,
                    extra_commands=self._generation_extra_commands or None,
                ),
                timeout=self._fetch_timeout,
            )
        except TimeoutError as err:
            if self._cache_data:
                _LOGGER.debug(
                    "BLE fetch timed out after %ss; using cached data",
                    self._fetch_timeout,
                )
                self.update_interval = timedelta(seconds=self._slow_poll)
                return dict(self._cache_data)
            raise UpdateFailed(
                f"BLE fetch timed out after {self._fetch_timeout}s"
            ) from err
        except Exception as err:  # noqa: BLE001
            if self._cache_data:
                _LOGGER.debug("Unable to fetch OBD data: %s; using cached data", err)
                self.update_interval = timedelta(seconds=self._slow_poll)
                return dict(self._cache_data)
            raise UpdateFailed(f"Unable to fetch OBD data: {err}") from err

        if new_data is None:
            if self._cache_data:
                _LOGGER.debug("OBD adapter returned no data; using cached data")
                self.update_interval = timedelta(seconds=self._slow_poll)
                return dict(self._cache_data)
            raise UpdateFailed("OBD adapter returned no data (connection failed)")

        new_data = dict(new_data)
        self._normalize_metrics(new_data)

        has_values = any(value is not None for value in new_data.values())

        if has_values:
            # Only keep fields that carry a real value; a missing/None field
            # must not discard the previously valid cached reading.
            self._cache_data = merge_cached_values(self._cache_data, new_data)
            self.update_interval = timedelta(seconds=self._fast_poll)
            await self._async_save_cache()
            _LOGGER.debug(
                "Fetched %d sensor values from %s", len(new_data), self._address
            )
        else:
            # Car is in range but turned off — keep slow polling
            _LOGGER.debug("No OBD data returned; car may be off (interval → %ds)", self._slow_poll)
            self.update_interval = timedelta(seconds=self._slow_poll)

        return dict(self._cache_data)
