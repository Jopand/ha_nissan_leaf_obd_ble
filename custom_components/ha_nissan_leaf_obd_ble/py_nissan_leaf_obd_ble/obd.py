"""The main API for talking to the OBD BLE module."""

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
# obd.py                                                               #
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

from bleak.backends.device import BLEDevice

from .elm327 import ELM327, OBDStatus
from .OBDResponse import OBDResponse

logger = logging.getLogger(__name__)


class OBD:
    """Class representing an OBD-II connection with it's assorted commands/sensors."""

    def __init__(
        self,
        device: BLEDevice,
        fast=True,
        timeout=5.0,
    ) -> None:
        """Initialise."""
        self.interface = None
        self.fast = fast  # global switch for disabling optimizations
        self.timeout = timeout
        self.__device = device
        self.__last_header = ()  # for comparing with the previously used header
        self.__frame_counts = {}  # keeps track of the number of return frames for each command

    @classmethod
    async def create(
        cls,
        device: BLEDevice,
        protocol=None,
        fast=True,
        timeout=5.0,
        check_voltage=True,
        start_low_power=False,
        service_uuid=None,
        characteristic_uuid_read=None,
        characteristic_uuid_write=None,
    ):
        """Manufacture instance."""
        self = cls(device, fast, timeout)

        logger.debug("Connecting to BLEDevice")
        await self.__connect(
            protocol,
            check_voltage,
            start_low_power,
            service_uuid=service_uuid,
            characteristic_uuid_read=characteristic_uuid_read,
            characteristic_uuid_write=characteristic_uuid_write,
        )
        if not self.is_connected():
            await self.close()
            return None
        return self

    async def __connect(
        self,
        protocol,
        check_voltage,
        start_low_power,
        service_uuid=None,
        characteristic_uuid_read=None,
        characteristic_uuid_write=None,
    ):
        """Attempt to instantiate an ELM327 connection object."""

        self.interface = await ELM327.create(
            self.__device,
            protocol,
            self.timeout,
            check_voltage,
            start_low_power,
            service_uuid=service_uuid,
            characteristic_uuid_read=characteristic_uuid_read,
            characteristic_uuid_write=characteristic_uuid_write,
        )

        # if the connection failed, close it
        if not self.is_connected():
            # the ELM327 class will report its own errors
            await self.close()

    async def __set_header(self, header) -> bool:
        if header == self.__last_header:
            return True

        setup_commands = (
            (b"AT SH " + header + b" ", "AT SH"),
            (b"AT FC SH " + header + b" ", "AT FC SH"),
            (b"AT FC SD 30 00 00", "AT FC SD"),
            (b"AT FC SM 1", "AT FC SM"),
        )
        header_selected = False
        for attempt in range(2):
            flow_control_ok = True
            for setup_command, name in setup_commands:
                response = await self.interface.send_and_parse(setup_command)
                is_ok = bool(response) and "\n".join(
                    message.raw() for message in response
                ) == "OK"
                if is_ok:
                    if name == "AT SH":
                        header_selected = True
                    continue

                logger.debug(
                    "Header %s setup step %s did not return OK (attempt %d)",
                    header,
                    name,
                    attempt + 1,
                )
                if name != "AT SH":
                    flow_control_ok = False
                break

            if header_selected and flow_control_ok:
                self.__last_header = header
                return True

        # Some ELM-compatible adapters reject flow-control configuration but
        # still accept diagnostic requests after AT SH selected the ECU.
        return header_selected

    async def close(self):
        """Close the connection, and clears supported_commands."""

        interface = self.interface
        self.interface = None
        if interface is not None:
            logger.debug("Closing connection")
            await interface.close()

    def status(self):
        """Return the OBD connection status."""
        if self.interface is None:
            return OBDStatus.NOT_CONNECTED
        return self.interface.status()

    async def low_power(self):
        """Enter low power mode."""
        if self.interface is None:
            return OBDStatus.NOT_CONNECTED
        return await self.interface.low_power()

    async def normal_power(self):
        """Exit low power mode."""
        if self.interface is None:
            return OBDStatus.NOT_CONNECTED
        return await self.interface.normal_power()

    def protocol_name(self):
        """Return the name of the protocol being used by the ELM327."""
        if self.interface is None:
            return ""
        return self.interface.protocol_name()

    def protocol_id(self):
        """Return the ID of the protocol being used by the ELM327."""
        if self.interface is None:
            return ""
        return self.interface.protocol_id()

    def is_connected(self):
        """Return. a boolean for whether a connection with the car was made.

        Note: this function returns False when:
        obd.status = OBDStatus.ELM_CONNECTED
        """
        return self.status() == OBDStatus.CAR_CONNECTED

    def test_cmd(self, cmd):
        """Return whether the command is supported. Always True when no PID cache is used."""
        return True

    async def query(self, cmd, force=False):
        """Primary API function. Send commands to the car, and protect against sending unsupported commands."""

        return await self.capture_command(cmd, force=force)

    async def capture_command(self, cmd, force=False):
        """Send a command and retain the raw adapter lines alongside the decoded response."""

        if self.status() == OBDStatus.NOT_CONNECTED:
            logger.warning("Query failed, no connection available")
            return OBDResponse()

        if cmd.kwp2000:
            return await self._query_kwp2000(cmd)

        if cmd.can_monitor:
            return await self._query_can_broadcast(cmd)

        if cmd.name == "lbc":
            return await self._query_lbc(cmd)

        # if the user forces, skip all checks
        if not force and not self.test_cmd(cmd):
            return OBDResponse()

        if not await self.__set_header(cmd.header):
            return OBDResponse(cmd)

        return await self.__capture_command(cmd)

    async def __capture_command(self, cmd, command_string=None):
        """Send and decode a command after its ECU header has been configured."""

        logger.debug("Sending command: %s", cmd)
        cmd_string = command_string or self.__build_command_string(cmd)
        raw_lines = await self.interface.send_raw(cmd_string)
        messages = self.interface.parse_lines(raw_lines)

        response = OBDResponse(cmd, messages)
        response.raw_lines = raw_lines or []

        if not messages:
            logger.debug("No valid OBD Messages returned")
            return response

        for f in messages[0].frames:
            logger.debug("Received frame: %s", f.raw)

        # if we don't already know how many frames this command returns,
        # log it, so we can specify it next time
        if cmd not in self.__frame_counts:
            self.__frame_counts[cmd] = sum([len(m.frames) for m in messages])

        for m in messages:
            if len(m.data) == 0 and (m.raw() == "NO DATA" or m.raw() == "CAN ERROR"):
                logger.debug("Vehicle not responding")
                return response

        decoded_response = cmd(messages)  # applies command-specific message sizing before decode
        decoded_response.raw_lines = response.raw_lines
        return decoded_response

    async def _query_lbc(self, cmd):
        """Read the multi-frame battery response using ZE1-compatible timing."""

        if not await self.__set_header(cmd.header):
            return OBDResponse(cmd)

        # The LBC can take longer to start its eight-frame ISO-TP response.
        # Filtering 7BB also prevents unrelated EV-CAN traffic from delaying
        # ELM-compatible adapters while they assemble the response.
        setup_commands = (
            b"AT ST 96",
            b"AT CRA 7BB",
            b"AT FC SD 30 00 0A",
        )
        for setup_command in setup_commands:
            response = await self.interface.send_and_parse(setup_command)
            if not response or "\n".join(message.raw() for message in response) != "OK":
                logger.debug("LBC setup command %r did not return OK", setup_command)

        try:
            result = await self.__capture_command(cmd)
            if result.value is not None:
                return result

            # Some VLink/ELM-compatible adapters only handle this ISO-TP
            # transaction reliably with automatic CAN formatting. The final
            # digit asks the ELM to wait for all eight LBC response frames.
            response = await self.interface.send_and_parse(b"AT CAF1")
            if not response or "\n".join(
                message.raw() for message in response
            ) != "OK":
                logger.debug("Unable to enable CAN auto formatting for LBC retry")

            try:
                fallback = await self.__capture_command(cmd, b"21018")
            finally:
                if self.status() != OBDStatus.NOT_CONNECTED:
                    response = await self.interface.send_and_parse(b"AT CAF0")
                    if not response or "\n".join(
                        message.raw() for message in response
                    ) != "OK":
                        logger.debug("Unable to restore raw CAN formatting")

            if fallback.value is not None:
                return fallback
            result.raw_lines.extend(["CAF1 fallback:", *fallback.raw_lines])
            return result
        finally:
            if self.status() != OBDStatus.NOT_CONNECTED:
                # A bare AT CRA clears the receive filter for later ECUs.
                response = await self.interface.send_and_parse(b"AT CRA")
                if not response or "\n".join(
                    message.raw() for message in response
                ) != "OK":
                    logger.debug("Unable to clear LBC receive filter")

    async def _query_kwp2000(self, cmd):
        """Execute a KWP2000 multi-step diagnostic sequence.
        
        For odometer: sends session start (0x0210C0) then data read (0x022101).
        Requires explicit sequencing with responses between steps.
        """
        
        # Set header to target ECU (0x743 for CAR-CAN odometer)
        if not await self.__set_header(cmd.header):
            return OBDResponse(cmd)
        
        raw_lines_all = []
        
        # Step 1: Send session start (0x0210C0)
        logger.info("KWP2000: Sending diagnostic session start (0x0210C0)")
        raw_lines_session = await self.interface.send_raw(b"0210C0")
        raw_lines_all.extend(raw_lines_session or [])
        messages_session = self.interface.parse_lines(raw_lines_session)
        
        if not messages_session or not messages_session[0].data:
            logger.warning("KWP2000: No response to session start - continuing anyway")
        else:
            logger.info(f"KWP2000: Session response ({len(messages_session)} msgs, {len(messages_session[0].data)} bytes): {messages_session[0].data.hex()}")
        
        # Small delay to ensure session is established
        await asyncio.sleep(0.05)
        
        # Step 2: Send data read request (0x022101) 
        logger.info("KWP2000: Sending data read request (0x022101)")
        raw_lines_data = await self.interface.send_raw(cmd.command)
        raw_lines_all.extend(raw_lines_data or [])
        messages_data = self.interface.parse_lines(raw_lines_data)
        
        response = OBDResponse(cmd, messages_data)
        response.raw_lines = raw_lines_all
        
        if not messages_data:
            logger.info("KWP2000: No response to data read request")
            return response
        
        logger.info(f"KWP2000: Data response ({len(messages_data)} msgs):")
        for i, msg in enumerate(messages_data):
            logger.info(f"  Message {i}: {len(msg.data)} bytes: {msg.data.hex()}")
        
        for f in messages_data[0].frames:
            logger.debug("KWP2000: Received frame: %s", f.raw)
        
        # Decode the response
        decoded_response = cmd(messages_data)
        decoded_response.raw_lines = response.raw_lines
        return decoded_response

    async def _query_can_broadcast(self, cmd):
        """Read a passive CAN broadcast frame and decode it using the command decoder."""
        if self.status() != OBDStatus.CAR_CONNECTED:
            return OBDResponse()

        if self.interface is None:
            return OBDResponse()

        lines = await self.interface.read_can_broadcast(cmd.command.decode())
        if not lines:
            response = OBDResponse(cmd)
            response.raw_lines = []
            return response

        messages = self.interface.parse_lines(lines)
        if not messages:
            response = OBDResponse(cmd)
            response.raw_lines = lines
            return response

        parsed_messages = [m for m in messages if len(m.data) > 0]
        if not parsed_messages:
            response = OBDResponse(cmd, messages)
            response.raw_lines = lines
            return response

        response = cmd(parsed_messages)
        response.raw_lines = lines
        return response

    def __build_command_string(self, cmd):
        """Assemble the appropriate command string."""
        cmd_string = cmd.command

        # if we know the number of frames that this command returns,
        # only wait for exactly that number. This avoids some harsh
        # timeouts from the ELM, thus speeding up queries.
        if self.fast and cmd.fast and (cmd in self.__frame_counts):
            cmd_string += str(self.__frame_counts[cmd]).encode()

        return cmd_string

