"""Part of python-OBD (a derivative of pyOBD)."""

from __future__ import annotations

########################################################################
#                                                                      #
# python-OBD: A python OBD-II serial module derived from pyobd         #
#                                                                      #
# Copyright 2004 Donour Sizemore (donour@uchicago.edu)                 #
# Copyright 2009 Secons Ltd. (www.obdtester.com)                       #
# Copyright 2009 Peter J. Creath                                       #
# Copyright 2016 Brendan Whitfield (brendan-w.com)                     #
#                                                                      #
########################################################################
#                                                                      #
# elm327.py                                                            #
#                                                                      #
# This file is part of python-OBD (a derivative of pyOBD)              #
#                                                                      #
# python-OBD is free software: you can redistribute it and/or modify   #
# it under the terms of the GNU General Public License as published by #
# the Free Software Foundation, either version 2 of the License, or    #
# (at your option) any later version.                                  #
#                                                                      #
# python-OBD is distributed in the hope that it will be useful,        #
# but WITHOUT ANY WARRANTY; without even the implied warranty of       #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the        #
# GNU General Public License for more details.                         #
#                                                                      #
# You should have received a copy of the GNU General Public License    #
# along with python-OBD.  If not, see <http://www.gnu.org/licenses/>.  #
#                                                                      #
########################################################################

import asyncio
import logging
import re
import time

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .bleserial import bleserial
from .protocols.protocol import Message
from .protocols.protocol_can import ISO_15765_4_11bit_500k
from .utils import isHex

logger = logging.getLogger(__name__)


class OBDStatus:
    """Values for the connection status flags."""

    NOT_CONNECTED = "Not Connected"
    ELM_CONNECTED = "ELM Connected"
    OBD_CONNECTED = "OBD Connected"
    CAR_CONNECTED = "Car Connected"


class ELM327:
    """Handles communication with the ELM327 adapter."""

    # chevron (ELM prompt character)
    ELM_PROMPT = b">"
    # an 'OK' which indicates we are entering low power state
    ELM_LP_ACTIVE = b"OK"

    # GATT UUIDs specifically for LeLink OBD BLE dongle
    SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
    CHARACTERISTIC_UUID_READ = "0000ffe1-0000-1000-8000-00805f9b34fb"
    CHARACTERISTIC_UUID_WRITE = "0000ffe1-0000-1000-8000-00805f9b34fb"

    def __init__(
        self,
        ble_device: BLEDevice,
        timeout,
        service_uuid=None,
        characteristic_uuid_read=None,
        characteristic_uuid_write=None,
    ) -> None:
        """Initialise."""
        self.__status = OBDStatus.NOT_CONNECTED
        self.__low_power = False
        self.timeout = timeout
        svc = service_uuid or self.SERVICE_UUID
        read_char = characteristic_uuid_read or self.CHARACTERISTIC_UUID_READ
        write_char = characteristic_uuid_write or self.CHARACTERISTIC_UUID_WRITE
        self.__port: bleserial | None = bleserial(
            ble_device,
            svc,
            read_char,
            write_char,
        )
        self.__port.timeout = timeout
        self.__port.write_timeout = timeout
        self.__protocol = ISO_15765_4_11bit_500k()

    @classmethod
    async def create(
        cls,
        ble_device: BLEDevice,
        protocol,
        timeout,
        check_voltage=True,
        start_low_power=False,
        service_uuid=None,
        characteristic_uuid_read=None,
        characteristic_uuid_write=None,
    ):
        """Initialize ELM327."""
        self = cls(
            ble_device,
            timeout,
            service_uuid=service_uuid,
            characteristic_uuid_read=characteristic_uuid_read,
            characteristic_uuid_write=characteristic_uuid_write,
        )

        try:
            await self._initialize(protocol, check_voltage, start_low_power)
        except (BleakError, asyncio.TimeoutError) as err:
            logger.debug(
                "Unable to initialize ELM327 using protocol %s: %s",
                "auto" if protocol is None else protocol,
                err,
            )
        finally:
            if self.__status != OBDStatus.CAR_CONNECTED:
                await self.close()

        return self

    async def _initialize(self, protocol, check_voltage, start_low_power):
        """Open the BLE transport and initialize the ELM327 session."""

        logger.info(
            "Initializing ELM327: PROTOCOL=%s",
            "auto" if protocol is None else protocol,
        )

        # ------------- open port -------------
        try:
            if not self.__port:
                logger.error("error: attempting to open a null port!")
            else:
                logger.debug("looks like the __port is all good: %s", self.__port)

            logger.debug("attempt to open the port: %s", self.__port)

            if self.__port is not None:
                await self.__port.open()

        except (BleakError, asyncio.TimeoutError) as e:
            logger.debug(
                "Unable to initialize ELM327 using protocol %s: %s",
                "auto" if protocol is None else protocol,
                e,
            )
            return

        # If we start with the IC in the low power state we need to wake it up
        if start_low_power:
            await self.__write(b" ")
            await asyncio.sleep(1)

        # ---------------------------- ATZ (reset) ----------------------------
        try:
            await self.__send(b"ATZ", delay=1)  # wait 1 second for ELM to initialize
            # return data can be junk, so don't bother checking
        except (BleakError, asyncio.TimeoutError) as e:
            await self.__error(e)
            return

        # -------------------------- ATE0 (echo OFF) --------------------------
        r = await self.__send(b"ATE0")
        if not self.__isok(r, expectEcho=True):
            await self.__error("ATE0 did not return 'OK'")
            return

        # ------------------------ ATSP6 (set protocol 6) ---------------------
        r = await self.__send(b"ATSP6")
        if not self.__isok(r):
            await self.__error("ATSP6 did not return 'OK'")
            return

        # ------------------------- ATH1 (headers ON) -------------------------
        r = await self.__send(b"ATH1")
        if not self.__isok(r):
            await self.__error("ATH1 did not return 'OK', or echoing is still ON")
            return

        # ------------------------ ATL0 (linefeeds OFF) -----------------------
        r = await self.__send(b"ATL0")
        if not self.__isok(r):
            await self.__error("ATL0 did not return 'OK'")
            return

        # ------------------------ ATS0 (printing spaces OFF)------------------
        r = await self.__send(b"ATS0")
        if not self.__isok(r):
            await self.__error("ATS0 did not return 'OK'")
            return

        # ----------------- ATCAF0 (CAN automatic formatting OFF)--------------
        r = await self.__send(b"ATCAF0")
        if not self.__isok(r):
            await self.__error("ATCAF0 did not return 'OK'")
            return

        # by now, we've successfuly communicated with the ELM, but not the car
        self.__status = OBDStatus.ELM_CONNECTED

        # -------------------------- AT RV (read volt) ------------------------
        if check_voltage:
            r = await self.__send(b"AT RV")
            if not r or len(r) != 1 or r[0] == "":
                await self.__error("No answer from 'AT RV'")
                return
            try:
                if float(r[0].lower().replace("v", "")) < 6:
                    logger.error("OBD2 socket disconnected")
                    return
            except ValueError:
                await self.__error("Incorrect response from 'AT RV'")
                return
            # by now, we've successfuly connected to the OBD socket
            self.__status = OBDStatus.OBD_CONNECTED

        # try to communicate with the car, and load the correct protocol parser
        self.__status = OBDStatus.CAR_CONNECTED

    def __isok(self, lines, expectEcho=False):
        if not lines:
            return False
        if expectEcho:
            # don't test for the echo itself
            # allow the adapter to already have echo disabled
            return self.__has_message(lines, "OK")
        return len(lines) == 1 and lines[0] == "OK"

    def __has_message(self, lines, text):
        return any(text in line for line in lines)

    async def __error(self, msg):
        """Handle fatal failures, print logger.info info and closes serial."""
        await self.close()
        logger.error(str(msg))

    def status(self):
        """Return the status."""
        if self.__port is None or not self.__port.is_connected:
            return OBDStatus.NOT_CONNECTED
        return self.__status

    def protocol_name(self):
        """Return the protocol name."""
        return self.__protocol.ELM_NAME

    def protocol_id(self):
        """Return the protocol ID."""
        return self.__protocol.ELM_ID

    async def low_power(self):
        """Enter Low Power mode.

        This command causes the ELM327 to shut off all but essential
        services.

        The ELM327 can be woken up by a message to the RS232 bus as
        well as a few other ways. See the Power Control section in
        the ELM327 datasheet for details on other ways to wake up
        the chip.

        Returns the status from the ELM327, 'OK' means low power mode
        is going to become active.
        """

        if self.__status == OBDStatus.NOT_CONNECTED:
            logger.info("cannot enter low power when unconnected")
            return None

        lines = await self.__send(b"ATLP", delay=1, end_marker=self.ELM_LP_ACTIVE)

        if "OK" in lines:
            logger.debug("Successfully entered low power mode")
            self.__low_power = True
        else:
            logger.debug("Failed to enter low power mode")

        return lines

    async def normal_power(self):
        """Exit Low Power mode.

        Send a space to trigger the RS232 to wakeup.

        This will send a space even if we aren't in low power mode as
        we want to ensure that we will be able to leave low power mode.

        See the Power Control section in the ELM327 datasheet for details
        on other ways to wake up the chip.

        Returns the status from the ELM327.
        """
        if self.__status == OBDStatus.NOT_CONNECTED:
            logger.info("cannot exit low power when unconnected")
            return None

        lines = await self.__send(b" ")

        # Assume we woke up
        logger.debug("Successfully exited low power mode")
        self.__low_power = False

        return lines

    async def close(self):
        """Close the serial port, and sets all attributes to unconnected states.

        ATZ is intentionally NOT sent here: resetting the adapter right before
        the BLE teardown makes some dongles (e.g. iCar Pro 2S) drop the link,
        which surfaced as a false 'disconnected unexpectedly' warning.  The
        adapter is still reset+initialized at the START of every fresh
        connection in create().
        """

        self.__status = OBDStatus.NOT_CONNECTED

        port = self.__port
        self.__port = None
        if port is not None:
            logger.debug("closing port")
            await port.close()

    async def send_and_parse(self, cmd) -> list[Message] | None:
        """Send OBDCommands.

        Sends the given command string, and parses the
        response lines with the protocol object.

        An empty command string will re-trigger the previous command

        Returns a list of Message objects
        """

        if self.__status == OBDStatus.NOT_CONNECTED:
            logger.info("cannot send_and_parse() when unconnected")
            return None

        # Check if we are in low power
        if self.__low_power:
            await self.normal_power()

        lines = await self.__send(cmd)
        return self.__protocol(lines)

    async def send_raw(self, cmd, delay=None, end_marker=ELM_PROMPT):
        """Send a command and return the raw adapter lines without parsing them."""
        return await self.__send(cmd, delay=delay, end_marker=end_marker)

    def parse_lines(self, lines) -> list[Message]:
        """Parse already-collected adapter lines with the active protocol parser."""
        return self.__protocol(lines)

    async def read_can_broadcast(self, can_id: str, timeout: float = 2.0) -> list[str]:
        """Passively read one CAN broadcast frame matching can_id."""
        if self.__status == OBDStatus.NOT_CONNECTED:
            logger.info("cannot read_can_broadcast() when unconnected")
            return []

        if self.__low_power:
            await self.normal_power()

        # Set receive address filter to only see this CAN ID.
        await self.__send(b"AT CRA " + can_id.upper().encode())

        # Start monitor mode and wait until at least one frame is seen or timeout elapses.
        await self.__write(b"AT MA")
        lines = await self.__read_with_timeout(timeout, stop_on_first_hex_line=True)

        # Any character returns the adapter to command mode; empty command sends only CR.
        await self.__send(b"")
        return lines

    async def read_can_monitor(self, timeout: float = 2.0) -> list[str]:
        """Passively read all monitor-mode CAN frames visible on the bus."""
        if self.__status == OBDStatus.NOT_CONNECTED:
            logger.info("cannot read_can_monitor() when unconnected")
            return []

        if self.__low_power:
            await self.normal_power()

        await self.__write(b"AT MA")
        lines = await self.__read_with_timeout(timeout, stop_on_first_hex_line=False)
        await self.__send(b"")
        return lines

    async def __send(self, cmd, delay=None, end_marker=ELM_PROMPT):
        """Unprotected send() function.

        will __write() the given string, no questions asked.
        returns result of __read() (a list of line strings)
        after an optional delay, until the end marker (by
        default, the prompt) is seen
        """
        await self.__write(cmd)

        delayed = 0.0
        if delay is not None:
            logger.debug("wait: %d seconds", delay)
            await asyncio.sleep(delay)
            delayed += delay

        r = await self.__read(end_marker=end_marker)
        while delayed < 1.0 and len(r) <= 0:
            d = 0.1
            logger.debug("no response; wait: %f seconds", d)
            await asyncio.sleep(d)
            delayed += d
            r = await self.__read(end_marker=end_marker)
        return r

    async def __write(self, cmd):
        """Low-level function to write a string to the port."""

        if self.__port:
            cmd += b"\r"  # terminate with carriage return in accordance with ELM327 and STN11XX specifications
            logger.debug("write: " + repr(cmd))
            try:
                self.__port.reset_input_buffer()  # dump everything in the input buffer
                await self.__port.write(cmd)  # turn the string into bytes and write
            except Exception:
                self.__status = OBDStatus.NOT_CONNECTED
                port = self.__port
                self.__port = None
                await port.close()
                raise
        else:
            raise BleakError("BLE device is not connected")

    async def __read(self, end_marker=ELM_PROMPT):
        """Low-level read function.

        accumulates characters until the end marker (by
        default, the prompt character) is seen
        returns a list of [/r/n] delimited strings
        """
        if not self.__port:
            raise BleakError("BLE device is not connected")

        buffer = bytearray()
        deadline = time.monotonic() + self.timeout

        while True:
            # retrieve as much data as possible
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for ELM327 response")
                data = await asyncio.wait_for(
                    self.__port.read(self.__port.in_waiting or 1),
                    timeout=remaining,
                )
            except Exception:
                self.__status = OBDStatus.NOT_CONNECTED
                port = self.__port
                self.__port = None
                await port.close()
                raise

            # if nothing was received
            if not data:
                logger.warning("Failed to read port")
                break

            buffer.extend(data)

            # end on specified end-marker sequence
            if end_marker in buffer:
                break

        # log, and remove the "bytearray(   ...   )" part
        logger.debug("read: " + repr(buffer)[10:-1])

        # clean out any null characters
        buffer = re.sub(b"\x00", b"", buffer)

        # remove the prompt character
        if buffer.endswith(self.ELM_PROMPT):
            buffer = buffer[:-1]

        # convert bytes into a standard string
        string = buffer.decode("utf-8", "ignore")

        # splits into lines while removing empty lines and trailing spaces
        lines = [s.strip() for s in re.split("[\r\n]", string) if bool(s)]

        return lines

    async def __read_with_timeout(
        self,
        timeout: float,
        stop_on_first_hex_line: bool = True,
    ) -> list[str]:
        """Read until timeout or, optionally, the first hexadecimal data line arrives."""
        if not self.__port:
            logger.info("cannot perform __read_with_timeout() when unconnected")
            return []

        buffer = bytearray()
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            try:
                data = await asyncio.wait_for(
                    self.__port.read(self.__port.in_waiting or 1),
                    timeout=remaining,
                )
            except TimeoutError:
                break
            except Exception:
                self.__status = OBDStatus.NOT_CONNECTED
                port = self.__port
                self.__port = None
                await port.close()
                raise

            if not data:
                break

            buffer.extend(data)

            # For monitor mode (stop_on_first_hex_line=False), don't exit on prompt;
            # keep reading until timeout to collect all available frames.
            if stop_on_first_hex_line and self.ELM_PROMPT in buffer:
                break

            string = re.sub(b"\x00", b"", buffer).decode("utf-8", "ignore")
            # Only evaluate complete line(s). A trailing fragment like "5" may be the
            # beginning of a CAN frame and should not end monitor capture early.
            parts = re.split("[\r\n]", string)
            complete_parts = (
                parts if string.endswith("\r") or string.endswith("\n") else parts[:-1]
            )
            lines = [s.strip() for s in complete_parts if bool(s.strip())]
            if stop_on_first_hex_line and any(isHex(line.replace(" ", "")) for line in lines):
                break

        logger.debug("read_with_timeout: " + repr(buffer)[10:-1])

        buffer = re.sub(b"\x00", b"", buffer)
        if buffer.endswith(self.ELM_PROMPT):
            buffer = buffer[:-1]

        string = buffer.decode("utf-8", "ignore")
        return [s.strip() for s in re.split("[\r\n]", string) if bool(s.strip())]

