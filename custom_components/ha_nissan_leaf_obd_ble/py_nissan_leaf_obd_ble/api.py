"""API for nissan leaf obd ble."""

from __future__ import annotations

import logging
import time

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .elm327 import OBDStatus
from .obd import OBD
from .profiles import get_generation_commands, VALID_GENERATIONS, DEFAULT_GENERATION

_LOGGER: logging.Logger = logging.getLogger(__package__)

_PRIORITY_COMMANDS = {
    generation: ("lbc", "plug_state", "charge_mode")
    for generation in VALID_GENERATIONS
}

_CRITICAL_VALUES = frozenset({"state_of_charge", "plug_state", "charge_mode"})
_OPTIONAL_COMMAND_BUDGET = 20.0


class NissanLeafObdBleApiClient:
    """API for connecting to the Nissan Leaf OBD BLE dongle."""

    async def async_get_data(
        self,
        ble_device: BLEDevice,
        options=None,
        generation: str = DEFAULT_GENERATION,
        extra_commands: dict | None = None,
        disabled_commands: set[str] | None = None,
    ) -> dict | None:
        """Get data from the API.
        
        Args:
            ble_device: Fresh connectable route selected by Home Assistant.
            options: BLE connection options (service_uuid, characteristic_uuid_read, characteristic_uuid_write)
            generation: Nissan Leaf generation profile. Options:
                - 'auto' (default): Automatic mode, includes both active and passive odometer sources.
                  Recommended for maximum compatibility. ZE0/AZE0 users get working passive odometer,
                  ZE1 users get fast active odometer (passive is redundant but harmless).
                - 'ze0': Optimized for 2010-2017 Leaf (passive odometer only)
                - 'aze0': Optimized for 2017-2018 Leaf (passive odometer only)  
                - 'ze1': Optimized for 2018+ Leaf (active odometer only)
            extra_commands: dict of command overrides to merge with generation defaults
            disabled_commands: set of command names to skip
            
        Returns:
            dict of sensor readings, or None if connection fails
            
        Raises:
            ValueError: if generation is not recognized
        """

        self.last_poll_succeeded = False
        self.last_failed_command: str | None = None

        # Validate and retrieve generation-specific command table
        if generation not in VALID_GENERATIONS:
            raise ValueError(
                f"Unknown generation '{generation}'. "
                f"Valid options: {', '.join(sorted(VALID_GENERATIONS))}"
            )

        opts = options or {}
        service_uuid = opts.get("service_uuid")
        characteristic_uuid_read = opts.get("characteristic_uuid_read")
        characteristic_uuid_write = opts.get("characteristic_uuid_write")

        api = await OBD.create(
            ble_device,
            protocol="6",
            service_uuid=service_uuid,
            characteristic_uuid_read=characteristic_uuid_read,
            characteristic_uuid_write=characteristic_uuid_write,
        )

        if api is None:
            return None

        try:
            # Get generation-specific command table with user overrides applied
            commands = get_generation_commands(
                generation,
                extra_commands=extra_commands,
                disabled_commands=disabled_commands,
            )

            priority_names = _PRIORITY_COMMANDS[generation]
            priority_commands = [
                commands[name] for name in priority_names if name in commands
            ]
            ordered_commands = list(priority_commands)
            ordered_commands.extend(
                command
                for name, command in commands.items()
                if name not in priority_names
            )

            data = {}
            started = time.monotonic()
            attempted = 0
            _LOGGER.debug(
                "Starting OBD poll for generation %s with %d commands",
                generation,
                len(ordered_commands),
            )
            for command_index, command in enumerate(ordered_commands):
                if (
                    command_index >= len(priority_commands)
                    and time.monotonic() - started >= _OPTIONAL_COMMAND_BUDGET
                ):
                    _LOGGER.debug(
                        "Stopping optional OBD queries after %.2fs with %d fresh values",
                        time.monotonic() - started,
                        len(data),
                    )
                    break

                if api.status() == OBDStatus.NOT_CONNECTED:
                    self.last_failed_command = command.name
                    _LOGGER.debug(
                        "OBD connection lost before %s after %d commands; "
                        "returning %d collected values",
                        command.name,
                        attempted,
                        len(data),
                    )
                    return data or None

                query_attempts = 2 if command.name == "lbc" else 1
                for query_attempt in range(query_attempts):
                    attempted += 1
                    command_started = time.monotonic()
                    try:
                        response = await api.query(command, force=True)
                    except (BleakError, TimeoutError) as err:
                        self.last_failed_command = command.name
                        self.last_poll_succeeded = _CRITICAL_VALUES <= data.keys()
                        _LOGGER.debug(
                            "OBD command %s failed after %.2fs: %s; returning %d "
                            "collected values",
                            command.name,
                            time.monotonic() - command_started,
                            err,
                            len(data),
                        )
                        return data or None

                    if response.value is not None:
                        fresh_values = {
                            key: value
                            for key, value in response.value.items()
                            if value is not None
                        }
                        data.update(fresh_values)
                        _LOGGER.debug(
                            "OBD command %s produced %d fresh values: %s",
                            command.name,
                            len(fresh_values),
                            sorted(fresh_values),
                        )

                    if command.name != "lbc" or "state_of_charge" in data:
                        break
                    if query_attempt == 0:
                        _LOGGER.debug(
                            "LBC query returned no state of charge; retrying once"
                        )

                if command.name == "unknown" and not response.messages:
                    _LOGGER.debug(
                        "No response to probe command; continuing with known OBD queries"
                    )
                    continue

                if api.status() == OBDStatus.NOT_CONNECTED:
                    self.last_failed_command = command.name
                    self.last_poll_succeeded = _CRITICAL_VALUES <= data.keys()
                    _LOGGER.debug(
                        "OBD connection lost while querying %s; returning %d "
                        "collected values",
                        command.name,
                        len(data),
                    )
                    return data or None

            self.last_poll_succeeded = _CRITICAL_VALUES <= data.keys()
            _LOGGER.debug(
                "OBD poll completed in %.2fs after %d commands with %d fresh "
                "values: %s",
                time.monotonic() - started,
                attempted,
                len(data),
                sorted(data),
            )
            return data
        finally:
            await api.close()

