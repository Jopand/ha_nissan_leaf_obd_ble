"""Config flow for Nissan Leaf OBD BLE (ha_nissan_leaf_obd_ble).

Setup wizard steps
------------------
1. bluetooth  — triggered automatically when HA discovers a compatible adapter.
2. user        — manual "Add Integration" entry point; shows a dropdown of all
                 discovered supported adapters.  If none are found the user is
                 asked to bring the adapter into BLE range first.
3. generation  — choose the Leaf platform (ZE0 / AZE0 / ZE1 / Auto).
4. configure   — (optional) override the BLE service / characteristic UUIDs
                 if the adapter uses non-standard GATT UUIDs.

Options flow (post-setup "Configure" button)
--------------------------------------------
Allows adjusting polling intervals, BLE UUIDs, and the generation after setup.
Changing generation reloads the integration so the correct sensor set is
created.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

try:
    from bluetooth_data_tools import human_readable_name
except ImportError:  # pragma: no cover
    def human_readable_name(_manufacturer, name, address):
        return name or address

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    BATTERY_NOMINAL_AH,
    CONF_CHARACTERISTIC_UUID_READ,
    CONF_CHARACTERISTIC_UUID_WRITE,
    CONF_GENERATION,
    CONF_NOMINAL_AH,
    CONF_SERVICE_UUID,
    DEFAULT_FAST_POLL,
    DEFAULT_NOMINAL_AH,
    DEFAULT_SLOW_POLL,
    DEFAULT_XS_POLL,
    DOMAIN,
    GENERATION_AUTO,
    GENERATION_OPTIONS,
    get_adapter_profile,
    is_supported_adapter,
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Multi-step config flow for ha_nissan_leaf_obd_ble."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        """Initialise."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._selected_device: BluetoothServiceInfoBleak | None = None
        self._selected_generation: str = GENERATION_AUTO
        self._selected_nominal_ah: float = DEFAULT_NOMINAL_AH

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return NissanLeafOptionsFlowHandler()

    # ------------------------------------------------------------------
    # Step 1a: auto-discovery via Bluetooth
    # ------------------------------------------------------------------

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle automatic Bluetooth discovery of a compatible adapter."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": human_readable_name(None, discovery_info.name, discovery_info.address)
        }
        return await self.async_step_user()

    # ------------------------------------------------------------------
    # Step 1b: manual "Add Integration" entry point
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Display a dropdown of all discovered supported adapters."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery_info = self._discovered_devices.get(address)
            if discovery_info is None:
                errors[CONF_ADDRESS] = "device_not_found"
            else:
                await self.async_set_unique_id(
                    discovery_info.address, raise_on_progress=False
                )
                self._abort_if_unique_id_configured()
                self._selected_device = discovery_info
                return await self.async_step_generation()

        # Populate the discovered-devices dict from HA's Bluetooth registry
        if self._discovery_info:
            self._discovered_devices[self._discovery_info.address] = (
                self._discovery_info
            )

        already_configured = self._async_current_ids()
        for info in async_discovered_service_info(self.hass):
            if (
                info.address in already_configured
                or info.address in self._discovered_devices
            ):
                continue
            if is_supported_adapter(info.name, info.service_uuids):
                self._discovered_devices[info.address] = info

        if not self._discovered_devices:
            return self.async_abort(reason="no_unconfigured_devices")

        device_choices = {
            addr: f"{info.name} ({addr})"
            for addr, info in self._discovered_devices.items()
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(device_choices)}
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2: generation selection
    # ------------------------------------------------------------------

    async def async_step_generation(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user choose their Leaf platform generation."""
        if user_input is not None:
            self._selected_generation = user_input[CONF_GENERATION]
            return await self.async_step_battery_size()

        return self.async_show_form(
            step_id="generation",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GENERATION, default=GENERATION_AUTO): vol.In(
                        GENERATION_OPTIONS
                    )
                }
            ),
            description_placeholders={
                "adapter_name": (
                    f"{self._selected_device.name} "
                    f"({self._selected_device.address})"
                    if self._selected_device
                    else ""
                )
            },
        )

    # ------------------------------------------------------------------
    # Step 3: battery size selection (for SOH calculation)
    # ------------------------------------------------------------------

    async def async_step_battery_size(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user select their battery size for SOH calculation."""
        if user_input is not None:
            self._selected_nominal_ah = float(user_input[CONF_NOMINAL_AH])
            return await self.async_step_configure()

        battery_choices = {
            str(ah): f"{size} kWh ({ah} Ah)"
            for size, ah in sorted(BATTERY_NOMINAL_AH.items())
        }

        return self.async_show_form(
            step_id="battery_size",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NOMINAL_AH, default=str(DEFAULT_NOMINAL_AH)): vol.In(
                        battery_choices
                    )
                }
            ),
        )

    # ------------------------------------------------------------------
    # Step 4: Create entry (UUIDs can be configured later via options)
    # ------------------------------------------------------------------

    async def async_step_configure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create the config entry with defaults; UUIDs can be changed later."""
        address = self._selected_device.address
        generation = self._selected_generation
        nominal_ah = self._selected_nominal_ah
        gen_label = GENERATION_OPTIONS.get(generation, generation)
        adapter_profile = get_adapter_profile(
            self._selected_device.name,
            self._selected_device.service_uuids,
        )

        return self.async_create_entry(
            title=f"Nissan Leaf {gen_label.split('—')[0].strip()} ({address})",
            data={
                CONF_ADDRESS: address,
                CONF_GENERATION: generation,
            },
            options={
                **adapter_profile,
                CONF_NOMINAL_AH: nominal_ah,
                "fast_poll": DEFAULT_FAST_POLL,
                "slow_poll": DEFAULT_SLOW_POLL,
                "xs_poll": DEFAULT_XS_POLL,
            },
        )


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


class NissanLeafOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow — allows adjusting settings after initial setup."""

    def __init__(self) -> None:
        """Initialise."""
        self._options: dict = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the options form."""
        if not self._options:
            self._options = dict(self.config_entry.options)

        if user_input is not None:
            # Convert string battery size back to float
            if CONF_NOMINAL_AH in user_input:
                user_input[CONF_NOMINAL_AH] = float(user_input[CONF_NOMINAL_AH])
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)

        battery_choices = {
            str(ah): f"{size} kWh ({ah} Ah)"
            for size, ah in sorted(BATTERY_NOMINAL_AH.items())
        }
        adapter_profile = get_adapter_profile(None)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NOMINAL_AH,
                        default=str(self._options.get(CONF_NOMINAL_AH, DEFAULT_NOMINAL_AH)),
                    ): vol.In(battery_choices),
                    vol.Required(
                        "fast_poll",
                        default=self._options.get("fast_poll", DEFAULT_FAST_POLL),
                    ): int,
                    vol.Required(
                        "slow_poll",
                        default=self._options.get("slow_poll", DEFAULT_SLOW_POLL),
                    ): int,
                    vol.Required(
                        "xs_poll",
                        default=self._options.get("xs_poll", DEFAULT_XS_POLL),
                    ): int,
                    vol.Optional(
                        CONF_SERVICE_UUID,
                        default=self._options.get(
                            CONF_SERVICE_UUID, adapter_profile[CONF_SERVICE_UUID]
                        ),
                    ): str,
                    vol.Optional(
                        CONF_CHARACTERISTIC_UUID_READ,
                        default=self._options.get(
                            CONF_CHARACTERISTIC_UUID_READ,
                            adapter_profile[CONF_CHARACTERISTIC_UUID_READ],
                        ),
                    ): str,
                    vol.Optional(
                        CONF_CHARACTERISTIC_UUID_WRITE,
                        default=self._options.get(
                            CONF_CHARACTERISTIC_UUID_WRITE,
                            adapter_profile[CONF_CHARACTERISTIC_UUID_WRITE],
                        ),
                    ): str,
                }
            ),
        )
