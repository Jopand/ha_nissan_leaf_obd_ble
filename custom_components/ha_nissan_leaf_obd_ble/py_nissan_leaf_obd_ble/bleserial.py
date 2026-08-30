"""Module to implement a serial-like interface over BLE GATT."""

import asyncio
from contextlib import suppress
import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakAbortedError,
    BleakClientWithServiceCache,
    BleakConnectionError,
    BleakNotFoundError,
    BleakOutOfConnectionSlotsError,
    establish_connection,
)

logger = logging.getLogger(__name__)


class bleserial:
    """Encapsulates the ble connection and make it appear something like a UART port."""

    __buffer = bytearray()

    def __init__(
        self,
        ble_device: BLEDevice,
        service_uuid,
        characteristic_uuid_read,
        characteristic_uuid_write,
    ) -> None:
        """Initialise."""
        self._ble_device: BLEDevice = ble_device
        self._service_uuid = service_uuid
        self._characteristic_uuid_read = characteristic_uuid_read
        self._characteristic_uuid_write = characteristic_uuid_write
        self._client: BleakClient | None = None
        self._rx_buffer = bytearray()
        self._timeout = None
        self._closing = False
        self._close_lock = asyncio.Lock()
        self._write_timeout = None

    async def _wait_for_data(self, size):
        while len(self._rx_buffer) < size:
            await asyncio.sleep(0.01)

    async def _wait_for_line(self):
        while b"\n" not in self._rx_buffer:
            await asyncio.sleep(0.01)

    def reset_input_buffer(self):
        """Reset the input buffer."""
        logger.debug("Resetting input buffer")
        self._rx_buffer.clear()

    def reset_output_buffer(self):
        """Reset the output buffer."""
        logger.debug("Resetting output buffer")
        # Since there's no explicit output buffer, this is a no-op.

    def flush(self):
        """Reset the input and the output buffer."""
        self.reset_input_buffer()
        self.reset_output_buffer()

    @property
    def in_waiting(self):
        """Return the number of bytes in the receive buffer."""
        return len(self._rx_buffer)

    @property
    def timeout(self):
        """Timeout duration."""
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        """Set the timeout duration."""
        self._timeout = value

    @property
    def write_timeout(self):
        """Write timeout duration."""
        return self._write_timeout

    @write_timeout.setter
    def write_timeout(self, value):
        """Set the write timeout duration."""
        self._write_timeout = value

    def _notification_handler(self, sender, data):
        """Handle when a GATT notification arrives."""
        logger.debug("Notification received: %s", data)
        self._rx_buffer.extend(data)

    async def open(self):
        """Open the port."""

        logger.debug("open port, ble_device: %s", self._ble_device)

        self._closing = False

        def on_disconnect(client):
            """Handle disconnection (expected or unexpected)."""
            if client is not self._client:
                logger.debug("Ignoring disconnect callback from superseded client")
                return
            if self._closing:
                logger.debug("BleakClient disconnected (expected)")
            else:
                logger.error("BleakClient disconnected unexpectedly")
            self._client = None

        try:
            logger.debug("Connecting to ble_device: %s %s", self._ble_device, self._ble_device.name)
            for attempt in range(2):
                self._client = await establish_connection(
                    BleakClientWithServiceCache,
                    self._ble_device,
                    self._ble_device.name or "Unknown Device",
                    disconnected_callback=on_disconnect,
                    max_attempts=3,
                    use_services_cache=attempt == 0,
                )

                missing_characteristics = [
                    uuid
                    for uuid in {
                        self._characteristic_uuid_read,
                        self._characteristic_uuid_write,
                    }
                    if self._client.services.get_characteristic(uuid) is None
                ]
                if not missing_characteristics:
                    break

                logger.warning(
                    "Expected GATT characteristic(s) missing: %s",
                    ", ".join(sorted(missing_characteristics)),
                )
                if attempt:
                    raise BleakError(
                        "Expected GATT characteristic(s) not found: "
                        + ", ".join(sorted(missing_characteristics))
                    )

                client = self._client
                self._closing = True
                await client.clear_cache()
                await client.disconnect()
                self._client = None
                self._closing = False

            logger.debug("Connected to ble_device: %s", self._ble_device)
            logger.debug(
                "Starting notifications on characteristic UUID: %s",
                self._characteristic_uuid_read,
            )
            await self._client.start_notify(
                self._characteristic_uuid_read, self._notification_handler
            )
            logger.debug("Notifications started")

        except BleakNotFoundError as e:
            await self._cleanup_failed_open()
            logger.debug("Device not found - it may have moved out of range: %s", e)
            self._closing = False
            raise

        except BleakOutOfConnectionSlotsError:
            await self._cleanup_failed_open()
            logger.debug(
                "No connection slots available - try disconnecting other devices"
            )
            self._closing = False
            raise

        except BleakAbortedError as e:
            await self._cleanup_failed_open()
            logger.debug(
                "Connection aborted; check interference, range, and Bluetooth proxy availability: %s",
                e,
            )
            self._closing = False
            raise

        except BleakConnectionError as e:
            await self._cleanup_failed_open()
            logger.debug("Connection failed: %s", e)
            self._closing = False
            raise

        except BleakError as e:
            await self._cleanup_failed_open()
            logger.debug("Failed to connect or start notifications: %s", e)
            self._closing = False
            raise

    async def _cleanup_failed_open(self):
        """Disconnect a client left behind by failed GATT setup."""
        if not self._client:
            return
        self._closing = True
        client = self._client
        try:
            with suppress(BleakError):
                await client.disconnect()
        finally:
            self._client = None

    async def close(self):
        """Close the port (expected disconnect)."""
        async with self._close_lock:
            if not self._client:
                return

            self._closing = True
            client = self._client

            try:
                logger.debug(
                    "Stopping notifications on characteristic UUID: %s",
                    self._characteristic_uuid_read,
                )
                with suppress(BleakError):
                    await client.stop_notify(self._characteristic_uuid_read)
                logger.debug("Disconnecting from device")
                await client.disconnect()
                logger.debug("Disconnected from device")
            finally:
                self._client = None

    async def write(self, data):
        """Write bytes."""
        if isinstance(data, str):
            data = data.encode()
        try:
            logger.debug(
                "Writing data to characteristic UUID: %s Data: %s",
                self._characteristic_uuid_write,
                data,
            )
            if self._client is not None:
                await self._client.write_gatt_char(
                    self._characteristic_uuid_write, data
                )
            logger.debug("Data written")
        except BleakError as e:
            logger.error("Failed to write data: %s", e)
            raise

    async def read(self, size=1):
        """Read from the buffer."""
        try:
            logger.debug("Reading %s bytes of data", size)
            while len(self._rx_buffer) < size:
                await asyncio.sleep(0.01)
            data = self._rx_buffer[:size]
            self._rx_buffer = self._rx_buffer[size:]
            logger.debug("Read data: %s", data)
            return bytes(data)
        except Exception as e:
            logger.error("Failed to read data: %s", e)
            raise

    async def readline(self):
        """Read a whole line from the buffer."""
        try:
            logger.debug("Reading line")
            await asyncio.wait_for(self._wait_for_line(), timeout=self._timeout)
            index = self._rx_buffer.index(b"\n") + 1
            data = self._rx_buffer[:index]
            self._rx_buffer = self._rx_buffer[index:]
            logger.debug("Read line: %s", data)
            return bytes(data)
        except TimeoutError as e:
            logger.error("Readline operation timed out")
            raise BleakError("Readline operation timed out") from e
        except Exception as e:
            logger.error("Failed to read line: %s", e)
            raise

