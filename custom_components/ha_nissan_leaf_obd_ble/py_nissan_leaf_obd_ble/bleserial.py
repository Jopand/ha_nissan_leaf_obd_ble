"""Module to implement a serial-like interface over BLE GATT."""

import asyncio
import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    DISCONNECT_TIMEOUT,
    establish_connection,
)

logger = logging.getLogger(__name__)


class bleserial:
    """Encapsulates the ble connection and make it appear something like a UART port."""

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
        self._data_event = asyncio.Event()
        self._timeout = None
        self._closing = False
        self._close_lock = asyncio.Lock()
        self._write_timeout = None

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
    def is_connected(self):
        """Return whether a BLE client is currently connected."""
        return self._client is not None

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
        self._data_event.set()

    async def _run_with_timeout(self, awaitable, timeout):
        """Await an operation with an optional timeout."""
        if timeout is None:
            return await awaitable
        return await asyncio.wait_for(awaitable, timeout=timeout)

    async def _bounded_disconnect(self, client):
        """Complete a bounded disconnect before propagating cancellation."""
        disconnect_task = asyncio.create_task(
            asyncio.wait_for(client.disconnect(), timeout=DISCONNECT_TIMEOUT)
        )
        cancelled = False
        while True:
            try:
                await asyncio.shield(disconnect_task)
            except asyncio.CancelledError:
                if disconnect_task.done() and disconnect_task.cancelled():
                    logger.debug("BLE disconnect operation was cancelled")
                    break
                cancelled = True
                continue
            except Exception as err:  # noqa: BLE001
                logger.debug("Unable to disconnect BLE client cleanly: %s", err)
            break
        if cancelled:
            raise asyncio.CancelledError

    async def _disconnect_client(self, client, *, stop_notify=False):
        """Best-effort bounded disconnect that never masks the caller's error."""
        self._closing = True
        self._data_event.set()
        try:
            if stop_notify:
                try:
                    await asyncio.wait_for(
                        client.stop_notify(self._characteristic_uuid_read),
                        timeout=DISCONNECT_TIMEOUT,
                    )
                except Exception as err:  # noqa: BLE001
                    logger.debug("Unable to stop BLE notifications cleanly: %s", err)
        finally:
            await self._bounded_disconnect(client)

    async def open(self):
        """Open the port."""

        logger.debug("open port, ble_device: %s", self._ble_device)

        self._closing = False
        self._rx_buffer.clear()
        self._data_event.clear()

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
            self._data_event.set()

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
                await self._run_with_timeout(
                    client.clear_cache(), DISCONNECT_TIMEOUT
                )
                await self._disconnect_client(client)
                self._client = None
                self._closing = False
                self._data_event.clear()

            logger.debug("Connected to ble_device: %s", self._ble_device)
            logger.debug(
                "Starting notifications on characteristic UUID: %s",
                self._characteristic_uuid_read,
            )
            await self._run_with_timeout(
                self._client.start_notify(
                    self._characteristic_uuid_read, self._notification_handler
                ),
                self._timeout,
            )
            logger.debug("Notifications started")

        except asyncio.CancelledError:
            await self._cleanup_failed_open()
            self._closing = False
            raise
        except Exception as err:  # noqa: BLE001
            await self._cleanup_failed_open()
            logger.debug("Failed to connect or start notifications: %s", err)
            self._closing = False
            raise

    async def _cleanup_failed_open(self):
        """Disconnect a client left behind by failed GATT setup."""
        if not self._client:
            return
        self._closing = True
        client = self._client
        try:
            await self._disconnect_client(client)
        finally:
            if self._client is client:
                self._client = None
            self._data_event.set()

    async def close(self):
        """Close the port (expected disconnect)."""
        async with self._close_lock:
            if not self._client:
                return

            self._closing = True
            client = self._client

            try:
                await self._disconnect_client(client, stop_notify=True)
            finally:
                if self._client is client:
                    self._client = None
                self._data_event.set()

    async def write(self, data):
        """Write bytes."""
        if isinstance(data, str):
            data = data.encode()
        logger.debug(
            "Writing data to characteristic UUID: %s Data: %s",
            self._characteristic_uuid_write,
            data,
        )
        client = self._client
        if client is None:
            raise BleakError("BLE device is not connected")
        await self._run_with_timeout(
            client.write_gatt_char(self._characteristic_uuid_write, data),
            self._write_timeout,
        )
        if client is not self._client:
            raise BleakError("BLE device disconnected while writing")
        logger.debug("Data written")

    async def _wait_for_buffer(self, predicate, operation):
        """Wait until buffered data matches a predicate or BLE disconnects."""
        while not predicate():
            self._data_event.clear()
            if predicate():
                return
            if self._client is None:
                raise BleakError(f"BLE device disconnected while {operation}")
            await self._data_event.wait()

    async def read(self, size=1):
        """Read from the buffer."""
        logger.debug("Reading %s bytes of data", size)
        await self._run_with_timeout(
            self._wait_for_buffer(
                lambda: len(self._rx_buffer) >= size, "reading"
            ),
            self._timeout,
        )
        data = self._rx_buffer[:size]
        self._rx_buffer = self._rx_buffer[size:]
        logger.debug("Read data: %s", data)
        return bytes(data)

    async def readline(self):
        """Read a whole line from the buffer."""
        logger.debug("Reading line")
        await self._run_with_timeout(
            self._wait_for_buffer(
                lambda: b"\n" in self._rx_buffer, "reading"
            ),
            self._timeout,
        )
        index = self._rx_buffer.index(b"\n") + 1
        data = self._rx_buffer[:index]
        self._rx_buffer = self._rx_buffer[index:]
        logger.debug("Read line: %s", data)
        return bytes(data)

