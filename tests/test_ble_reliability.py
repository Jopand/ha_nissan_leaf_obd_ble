"""Regression tests for BLE polling reliability and cached values."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
import types
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "ha_nissan_leaf_obd_ble"


def _module(name: str, **attributes) -> types.ModuleType:
    """Create a stub module with the requested attributes."""
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    return module


def load_coordinator_module():
    """Load coordinator.py with minimal Home Assistant dependency stubs."""

    class UpdateFailed(Exception):
        """Stub Home Assistant update failure."""

    class DataUpdateCoordinator:
        """Stub base class; tests bypass the real coordinator constructor."""

    class Store:
        """Stub Home Assistant storage class."""

    class BluetoothReachabilityIntent:
        """Stub reachability intent enum."""

        CONNECTION = "connection"

    package_name = "test_nissan_leaf_component"
    package = _module(package_name)
    package.__path__ = []

    const = _module(
        f"{package_name}.const",
        CONF_GENERATION="generation",
        CONF_NOMINAL_AH="nominal_ah",
        DEFAULT_FAST_POLL=10,
        DEFAULT_FETCH_TIMEOUT=90,
        DEFAULT_NOMINAL_AH=79.48,
        DEFAULT_SLOW_POLL=300,
        DEFAULT_XS_POLL=3600,
        DOMAIN="ha_nissan_leaf_obd_ble",
        GENERATION_AUTO="auto",
        STORAGE_KEY="sensor_cache",
        STORAGE_VERSION=1,
    )
    generations = _module(
        f"{package_name}.generations",
        get_extra_commands_for_generation=lambda *args, **kwargs: {},
    )

    def merge_cached_values(cache, fresh):
        merged = dict(cache)
        merged.update({key: value for key, value in fresh.items() if value is not None})
        return merged

    metrics = _module(
        f"{package_name}.metrics",
        merge_cached_values=merge_cached_values,
        normalize_metrics=lambda data, nominal_ah: False,
    )

    stubs = {
        package_name: package,
        f"{package_name}.const": const,
        f"{package_name}.generations": generations,
        f"{package_name}.metrics": metrics,
        "homeassistant": _module("homeassistant"),
        "homeassistant.components": _module("homeassistant.components"),
        "homeassistant.components.bluetooth": _module(
            "homeassistant.components.bluetooth",
            async_ble_device_from_address=lambda *args, **kwargs: object(),
            async_address_reachability_diagnostics=lambda *args, **kwargs: "reachable",
            BluetoothReachabilityIntent=BluetoothReachabilityIntent,
        ),
        "homeassistant.config_entries": _module(
            "homeassistant.config_entries", ConfigEntry=object
        ),
        "homeassistant.const": _module(
            "homeassistant.const", CONF_ADDRESS="address"
        ),
        "homeassistant.core": _module(
            "homeassistant.core", HomeAssistant=object
        ),
        "homeassistant.helpers": _module("homeassistant.helpers"),
        "homeassistant.helpers.storage": _module(
            "homeassistant.helpers.storage", Store=Store
        ),
        "homeassistant.helpers.update_coordinator": _module(
            "homeassistant.helpers.update_coordinator",
            DataUpdateCoordinator=DataUpdateCoordinator,
            UpdateFailed=UpdateFailed,
        ),
    }

    module_name = f"{package_name}.coordinator"
    spec = importlib.util.spec_from_file_location(
        module_name, COMPONENT / "coordinator.py"
    )
    module = importlib.util.module_from_spec(spec)
    stubs[module_name] = module
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


coordinator_module = load_coordinator_module()


def load_bleserial_module():
    """Load bleserial.py with minimal Bleak dependency stubs."""

    class BleakError(Exception):
        """Stub base Bleak error."""

    class BLEDevice:
        """Stub BLE device type."""

    async def establish_connection(*args, **kwargs):
        raise AssertionError("test must replace establish_connection")

    bleak_retry_connector = _module(
        "bleak_retry_connector",
        BleakAbortedError=BleakError,
        BleakClientWithServiceCache=object,
        BleakConnectionError=BleakError,
        BleakNotFoundError=BleakError,
        BleakOutOfConnectionSlotsError=BleakError,
        DISCONNECT_TIMEOUT=0.1,
        establish_connection=establish_connection,
    )
    stubs = {
        "bleak": _module("bleak", BleakClient=object),
        "bleak.backends": _module("bleak.backends"),
        "bleak.backends.device": _module(
            "bleak.backends.device", BLEDevice=BLEDevice
        ),
        "bleak.exc": _module("bleak.exc", BleakError=BleakError),
        "bleak_retry_connector": bleak_retry_connector,
    }

    module_name = "test_nissan_leaf_bleserial"
    spec = importlib.util.spec_from_file_location(
        module_name,
        COMPONENT / "py_nissan_leaf_obd_ble" / "bleserial.py",
    )
    module = importlib.util.module_from_spec(spec)
    stubs[module_name] = module
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


bleserial_module = load_bleserial_module()


def load_elm327_module(serial_class):
    """Load elm327.py with a supplied BLE serial implementation."""

    class BleakError(Exception):
        """Stub base Bleak error."""

    class Protocol:
        ELM_NAME = "CAN"
        ELM_ID = "6"

        def __call__(self, lines):
            return []

    package_name = "test_nissan_leaf_obd_library"
    package = _module(package_name)
    package.__path__ = []
    protocols = _module(f"{package_name}.protocols")
    protocols.__path__ = []
    stubs = {
        package_name: package,
        f"{package_name}.bleserial": _module(
            f"{package_name}.bleserial", bleserial=serial_class
        ),
        f"{package_name}.protocols": protocols,
        f"{package_name}.protocols.protocol": _module(
            f"{package_name}.protocols.protocol", Message=object
        ),
        f"{package_name}.protocols.protocol_can": _module(
            f"{package_name}.protocols.protocol_can",
            ISO_15765_4_11bit_500k=Protocol,
        ),
        f"{package_name}.utils": _module(
            f"{package_name}.utils", isHex=lambda value: True
        ),
        "bleak": _module("bleak"),
        "bleak.backends": _module("bleak.backends"),
        "bleak.backends.device": _module(
            "bleak.backends.device", BLEDevice=object
        ),
        "bleak.exc": _module("bleak.exc", BleakError=BleakError),
    }

    module_name = f"{package_name}.elm327"
    spec = importlib.util.spec_from_file_location(
        module_name,
        COMPONENT / "py_nissan_leaf_obd_ble" / "elm327.py",
    )
    module = importlib.util.module_from_spec(spec)
    stubs[module_name] = module
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


def load_api_module(obd_class, commands):
    """Load api.py with supplied OBD behavior and command table."""

    class BleakError(Exception):
        """Stub base Bleak error."""

    class OBDStatus:
        NOT_CONNECTED = "not connected"
        CAR_CONNECTED = "car connected"

    package_name = "test_nissan_leaf_api_library"
    package = _module(package_name)
    package.__path__ = []
    stubs = {
        package_name: package,
        f"{package_name}.elm327": _module(
            f"{package_name}.elm327", OBDStatus=OBDStatus
        ),
        f"{package_name}.obd": _module(
            f"{package_name}.obd", OBD=obd_class
        ),
        f"{package_name}.profiles": _module(
            f"{package_name}.profiles",
            DEFAULT_GENERATION="auto",
            VALID_GENERATIONS={"auto", "ze0", "aze0", "ze1"},
            get_generation_commands=lambda *args, **kwargs: commands,
        ),
        "bleak": _module("bleak"),
        "bleak.backends": _module("bleak.backends"),
        "bleak.backends.device": _module(
            "bleak.backends.device", BLEDevice=object
        ),
        "bleak.exc": _module("bleak.exc", BleakError=BleakError),
    }

    module_name = f"{package_name}.api"
    spec = importlib.util.spec_from_file_location(
        module_name,
        COMPONENT / "py_nissan_leaf_obd_ble" / "api.py",
    )
    module = importlib.util.module_from_spec(spec)
    stubs[module_name] = module
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module, OBDStatus, BleakError


def load_obd_module():
    """Load obd.py with minimal transport and response stubs."""

    class OBDStatus:
        NOT_CONNECTED = "not connected"
        CAR_CONNECTED = "car connected"

    class OBDResponse:
        def __init__(self, *args, **kwargs):
            self.messages = []
            self.raw_lines = []
            self.value = None

    package_name = "test_nissan_leaf_obd_header_library"
    package = _module(package_name)
    package.__path__ = []
    stubs = {
        package_name: package,
        f"{package_name}.elm327": _module(
            f"{package_name}.elm327", ELM327=object, OBDStatus=OBDStatus
        ),
        f"{package_name}.OBDResponse": _module(
            f"{package_name}.OBDResponse", OBDResponse=OBDResponse
        ),
        "bleak": _module("bleak"),
        "bleak.backends": _module("bleak.backends"),
        "bleak.backends.device": _module(
            "bleak.backends.device", BLEDevice=object
        ),
    }

    module_name = f"{package_name}.obd"
    spec = importlib.util.spec_from_file_location(
        module_name,
        COMPONENT / "py_nissan_leaf_obd_ble" / "obd.py",
    )
    module = importlib.util.module_from_spec(spec)
    stubs[module_name] = module
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class FakeApi:
    """Return or raise a configured poll result."""

    def __init__(self, result) -> None:
        self.result = result
        self.calls = 0
        self.call_kwargs = []

    async def async_get_data(self, **kwargs):
        self.calls += 1
        self.call_kwargs.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def make_coordinator(result, cache=None, available=True):
    """Create a coordinator instance configured for one update call."""
    coordinator = object.__new__(coordinator_module.NissanLeafCoordinator)
    coordinator.hass = object()
    coordinator.api = FakeApi(result)
    coordinator._address = "AA:BB:CC:DD:EE:FF"
    coordinator._generation = "ze1"
    coordinator._generation_extra_commands = {}
    coordinator._options = {}
    coordinator._fetch_timeout = 1
    coordinator._fast_poll = 10
    coordinator._slow_poll = 300
    coordinator._xs_poll = 3600
    coordinator._cache_data = dict(cache or {})
    coordinator.last_poll_attempt = None
    coordinator.last_successful_update = None
    coordinator.last_fresh_value_count = 0
    coordinator.last_poll_succeeded = False
    coordinator.last_updated_by_key = {}
    coordinator._zero_fresh_poll_logged = True
    coordinator._partial_poll_logged = False
    coordinator._last_stale_critical_keys = frozenset()
    coordinator._normalize_metrics = lambda data: False
    coordinator._async_save_cache = AsyncMock()
    coordinator.update_interval = None
    coordinator.ble_device = object() if available else None
    coordinator_module.bluetooth.async_ble_device_from_address = Mock(
        return_value=coordinator.ble_device
    )
    coordinator_module.bluetooth.async_address_reachability_diagnostics = Mock(
        return_value="not connectable"
    )
    return coordinator


def method_node(module: ast.Module, name: str) -> ast.AsyncFunctionDef:
    """Return the first async method named `name` found in the module."""
    for node in ast.walk(module):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Async method {name!r} not found")


def _contains_constant(node, value) -> bool:
    """Return True if a literal constant equal to `value` appears in `node`."""
    return any(
        isinstance(child, ast.Constant) and child.value == value
        for child in ast.walk(node)
    )


def _closing_assignments(node) -> list[bool]:
    """Return boolean values assigned to self._closing in an AST node."""
    assignments = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Assign) or not isinstance(child.value, ast.Constant):
            continue
        if any(
            isinstance(target, ast.Attribute)
            and target.attr == "_closing"
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            for target in child.targets
        ):
            assignments.append(child.value.value)
    return assignments


class CoordinatorReliabilityTest(unittest.IsolatedAsyncioTestCase):
    """Exercise coordinator behavior without requiring Home Assistant."""

    async def test_timeout_returns_cache_and_uses_slow_polling(self):
        coordinator = make_coordinator(
            TimeoutError(), {"state_of_charge": 61.0}
        )

        data = await coordinator._async_update_data()

        self.assertEqual(data, {"state_of_charge": 61.0})
        self.assertIsNot(data, coordinator._cache_data)
        self.assertEqual(coordinator.update_interval, timedelta(seconds=300))

    async def test_generic_error_returns_cache(self):
        coordinator = make_coordinator(
            RuntimeError("BLE disconnected"), {"state_of_charge": 61.0}
        )

        data = await coordinator._async_update_data()

        self.assertEqual(data, {"state_of_charge": 61.0})
        self.assertEqual(coordinator.update_interval, timedelta(seconds=300))

    async def test_none_result_returns_cache(self):
        coordinator = make_coordinator(None, {"state_of_charge": 61.0})

        data = await coordinator._async_update_data()

        self.assertEqual(data, {"state_of_charge": 61.0})
        self.assertEqual(coordinator.update_interval, timedelta(seconds=300))

    async def test_failures_raise_when_no_cache_exists(self):
        for result in (TimeoutError(), RuntimeError("BLE disconnected"), None):
            with self.subTest(result=result):
                coordinator = make_coordinator(result)
                with self.assertRaises(coordinator_module.UpdateFailed):
                    await coordinator._async_update_data()

    async def test_partial_data_preserves_old_values_and_saves_new_values(self):
        coordinator = make_coordinator(
            {"state_of_charge": None, "odometer": 98439},
            {"state_of_charge": 61.0, "odometer": 98000},
        )
        coordinator._last_stale_critical_keys = frozenset({"state_of_charge"})

        data = await coordinator._async_update_data()

        self.assertEqual(
            data, {"state_of_charge": 61.0, "odometer": 98439}
        )
        self.assertEqual(coordinator.update_interval, timedelta(seconds=10))
        self.assertTrue(coordinator.last_poll_succeeded)
        self.assertEqual(coordinator.last_fresh_value_count, 1)
        self.assertIn("odometer", coordinator.last_updated_by_key)
        coordinator._async_save_cache.assert_awaited_once_with()

    async def test_transport_partial_data_uses_fast_polling(self):
        coordinator = make_coordinator(
            {"display_state_of_charge": 48},
            {"state_of_charge": 53, "odometer": 98439},
        )
        coordinator.api.last_poll_succeeded = False
        coordinator.api.last_failed_command = "odometer"

        with self.assertLogs(coordinator_module._LOGGER, level="WARNING"):
            data = await coordinator._async_update_data()

        self.assertEqual(
            data,
            {
                "display_state_of_charge": 48,
                "state_of_charge": 53,
                "odometer": 98439,
            },
        )
        self.assertFalse(coordinator.last_poll_succeeded)
        self.assertIsNone(coordinator.last_successful_update)
        self.assertEqual(coordinator.update_interval, timedelta(seconds=10))
        coordinator._async_save_cache.assert_awaited_once_with()

    async def test_fresh_connectable_route_is_resolved_for_every_poll(self):
        coordinator = make_coordinator({"state_of_charge": 61.0})
        local_adapter = object()
        esphome_proxy = object()
        coordinator_module.bluetooth.async_ble_device_from_address = Mock(
            side_effect=(local_adapter, esphome_proxy)
        )

        await coordinator._async_update_data()
        await coordinator._async_update_data()

        self.assertEqual(
            [call["ble_device"] for call in coordinator.api.call_kwargs],
            [local_adapter, esphome_proxy],
        )
        self.assertEqual(
            coordinator_module.bluetooth.async_ble_device_from_address.call_args_list,
            [
                unittest.mock.call(
                    coordinator.hass, "AA:BB:CC:DD:EE:FF", connectable=True
                ),
                unittest.mock.call(
                    coordinator.hass, "AA:BB:CC:DD:EE:FF", connectable=True
                ),
            ],
        )

    async def test_no_valid_fields_keeps_cache_without_saving(self):
        coordinator = make_coordinator(
            {"state_of_charge": None}, {"state_of_charge": 61.0}
        )

        data = await coordinator._async_update_data()

        self.assertEqual(data, {"state_of_charge": 61.0})
        self.assertEqual(coordinator.update_interval, timedelta(seconds=300))
        coordinator._async_save_cache.assert_not_awaited()
        self.assertFalse(coordinator.last_poll_succeeded)
        self.assertEqual(coordinator.last_fresh_value_count, 0)

    async def test_zero_fresh_poll_logs_warning_once(self):
        coordinator = make_coordinator({}, {"state_of_charge": 61.0})
        coordinator._zero_fresh_poll_logged = False

        with self.assertLogs(coordinator_module._LOGGER, level="WARNING") as logs:
            await coordinator._async_update_data()

        self.assertIn("produced no fresh values", logs.output[0])
        self.assertTrue(coordinator._zero_fresh_poll_logged)

    async def test_absent_adapter_returns_cache_without_polling(self):
        coordinator = make_coordinator(
            {"state_of_charge": 62.0},
            {"state_of_charge": 61.0},
            available=False,
        )

        data = await coordinator._async_update_data()

        self.assertEqual(data, {"state_of_charge": 61.0})
        self.assertEqual(coordinator.api.calls, 0)
        self.assertEqual(coordinator.update_interval, timedelta(seconds=3600))
        coordinator_module.bluetooth.async_address_reachability_diagnostics.assert_called_once_with(
            coordinator.hass,
            "AA:BB:CC:DD:EE:FF",
            coordinator_module.bluetooth.BluetoothReachabilityIntent.CONNECTION,
        )

    async def test_cancellation_is_not_converted_to_cached_success(self):
        started = asyncio.Event()

        class BlockingApi:
            async def async_get_data(self, **kwargs):
                started.set()
                await asyncio.Event().wait()

        coordinator = make_coordinator(None, {"state_of_charge": 61.0})
        coordinator.api = BlockingApi()
        update_task = asyncio.create_task(coordinator._async_update_data())
        await started.wait()

        update_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await update_task


class ApiPollingReliabilityTest(unittest.IsolatedAsyncioTestCase):
    """Exercise command ordering, probe handling, and partial poll results."""

    async def test_critical_ze1_commands_run_first(self):
        commands = {
            name: types.SimpleNamespace(name=name)
            for name in (
                "unknown",
                "power_switch",
                "lbc",
                "plug_state",
                "charge_mode",
                "odometer",
                "display_state_of_charge",
            )
        }

        class Connection:
            def __init__(self, status):
                self._status = status
                self.queries = []
                self.close = AsyncMock()

            def status(self):
                return self._status.CAR_CONNECTED

            async def query(self, command, force):
                self.queries.append(command.name)
                if command.name == "unknown":
                    return types.SimpleNamespace(messages=[], value=None)
                if command.name == "lbc":
                    value = {"state_of_charge": 48}
                else:
                    value = {command.name: len(self.queries)}
                return types.SimpleNamespace(
                    messages=[object()], value=value
                )

        class OBD:
            connection = None

            @classmethod
            async def create(cls, *args, **kwargs):
                return cls.connection

        module, status, _ = load_api_module(OBD, commands)
        OBD.connection = Connection(status)

        client = module.NissanLeafObdBleApiClient()
        data = await client.async_get_data(
            ble_device=object(), generation="ze1"
        )

        self.assertEqual(
            OBD.connection.queries,
            [
                "unknown",
                "power_switch",
                "plug_state",
                "charge_mode",
                "lbc",
                "odometer",
                "display_state_of_charge",
            ],
        )
        self.assertEqual(
            set(data),
            {
                "state_of_charge",
                "plug_state",
                "charge_mode",
                "display_state_of_charge",
                "odometer",
                "power_switch",
            },
        )
        self.assertTrue(client.last_poll_succeeded)
        self.assertEqual(
            module._PRIORITY_COMMANDS["ze1"],
            (
                "unknown",
                "power_switch",
                "gear_position",
                "bat_12v_voltage",
                "bat_12v_current",
                "plug_state",
                "charge_mode",
                "lbc",
            ),
        )
        OBD.connection.close.assert_awaited_once_with()

    async def test_empty_lbc_response_is_retried_once(self):
        commands = {
            name: types.SimpleNamespace(name=name)
            for name in ("lbc", "plug_state", "charge_mode")
        }

        class OBD:
            connection = None

            @classmethod
            async def create(cls, *args, **kwargs):
                return cls.connection

        module, status, _ = load_api_module(OBD, commands)

        class Connection:
            def __init__(self):
                self.queries = []
                self.close = AsyncMock()

            def status(self):
                return status.CAR_CONNECTED

            async def query(self, command, force):
                self.queries.append(command.name)
                if command.name == "lbc" and self.queries.count("lbc") == 1:
                    return types.SimpleNamespace(messages=[], value=None)
                values = {
                    "lbc": {"state_of_charge": 48},
                    "plug_state": {"plug_state": 1},
                    "charge_mode": {"charge_mode": 2},
                }
                return types.SimpleNamespace(
                    messages=[object()], value=values[command.name]
                )

        OBD.connection = Connection()
        client = module.NissanLeafObdBleApiClient()

        data = await client.async_get_data(ble_device=object(), generation="ze1")

        self.assertEqual(
            OBD.connection.queries,
            ["plug_state", "charge_mode", "lbc", "lbc"],
        )
        self.assertEqual(
            data,
            {"state_of_charge": 48, "plug_state": 1, "charge_mode": 2},
        )
        self.assertTrue(client.last_poll_succeeded)

    async def test_missing_plug_and_lbc_are_retried_after_warmup(self):
        commands = {
            name: types.SimpleNamespace(name=name)
            for name in (
                "bat_12v_voltage",
                "plug_state",
                "charge_mode",
                "lbc",
            )
        }

        class OBD:
            connection = None

            @classmethod
            async def create(cls, *args, **kwargs):
                return cls.connection

        module, status, _ = load_api_module(OBD, commands)

        class Connection:
            def __init__(self):
                self.queries = []
                self.close = AsyncMock()

            def status(self):
                return status.CAR_CONNECTED

            async def query(self, command, force):
                self.queries.append(command.name)
                attempt = self.queries.count(command.name)
                values = {
                    "bat_12v_voltage": {"bat_12v_voltage": 13.2},
                    "charge_mode": {"charge_mode": "Not charging"},
                    "plug_state": {"plug_state": "Not plugged"},
                    "lbc": {"state_of_charge": 47},
                }
                value = (
                    None
                    if command.name in {"plug_state", "lbc"} and attempt == 1
                    else values[command.name]
                )
                response = types.SimpleNamespace(
                    messages=[], value=value, raw_lines=[]
                )
                return response

        OBD.connection = Connection()
        client = module.NissanLeafObdBleApiClient()

        data = await client.async_get_data(ble_device=object(), generation="ze1")

        self.assertEqual(
            OBD.connection.queries,
            [
                "bat_12v_voltage",
                "plug_state",
                "charge_mode",
                "lbc",
                "plug_state",
                "lbc",
            ],
        )
        self.assertEqual(data["state_of_charge"], 47)
        self.assertEqual(data["plug_state"], "Not plugged")
        self.assertTrue(client.last_poll_succeeded)

    async def test_optional_queries_stop_after_budget(self):
        commands = {
            name: types.SimpleNamespace(name=name)
            for name in (
                "lbc",
                "plug_state",
                "charge_mode",
                "odometer",
                "tp_fl",
            )
        }

        class OBD:
            connection = None

            @classmethod
            async def create(cls, *args, **kwargs):
                return cls.connection

        module, status, _ = load_api_module(OBD, commands)

        class Connection:
            def __init__(self):
                self.queries = []
                self.close = AsyncMock()

            def status(self):
                return status.CAR_CONNECTED

            async def query(self, command, force):
                self.queries.append(command.name)
                values = {
                    "lbc": {"state_of_charge": 48},
                    "plug_state": {"plug_state": "Plugged"},
                    "charge_mode": {"charge_mode": "L2 charging"},
                }
                return types.SimpleNamespace(
                    messages=[object()], value=values[command.name]
                )

        OBD.connection = Connection()
        client = module.NissanLeafObdBleApiClient()

        with patch.object(
            module.time,
            "monotonic",
            side_effect=(0, 0, 0, 0, 21, 21, 21),
        ):
            data = await client.async_get_data(
                ble_device=object(), generation="ze1"
            )

        self.assertEqual(
            OBD.connection.queries,
            ["plug_state", "charge_mode", "lbc"],
        )
        self.assertEqual(
            data,
            {
                "state_of_charge": 48,
                "plug_state": "Plugged",
                "charge_mode": "L2 charging",
            },
        )
        self.assertTrue(client.last_poll_succeeded)

    async def test_late_transport_failure_returns_collected_values(self):
        commands = {
            name: types.SimpleNamespace(name=name)
            for name in ("lbc", "plug_state", "charge_mode", "odometer")
        }

        class OBD:
            connection = None

            @classmethod
            async def create(cls, *args, **kwargs):
                return cls.connection

        module, status, bleak_error = load_api_module(OBD, commands)

        class Connection:
            def __init__(self):
                self.close = AsyncMock()

            def status(self):
                return status.CAR_CONNECTED

            async def query(self, command, force):
                values = {
                    "lbc": {"state_of_charge": 48},
                    "plug_state": {"plug_state": 1},
                    "charge_mode": {"charge_mode": 2},
                }
                if command.name == "odometer":
                    raise bleak_error("disconnected")
                return types.SimpleNamespace(
                    messages=[object()], value=values[command.name]
                )

        OBD.connection = Connection()

        client = module.NissanLeafObdBleApiClient()
        data = await client.async_get_data(
            ble_device=object(), generation="ze1"
        )

        self.assertEqual(
            data,
            {"state_of_charge": 48, "plug_state": 1, "charge_mode": 2},
        )
        self.assertTrue(client.last_poll_succeeded)
        self.assertEqual(client.last_failed_command, "odometer")
        OBD.connection.close.assert_awaited_once_with()


class ObdHeaderSetupTest(unittest.IsolatedAsyncioTestCase):
    """Exercise ELM-compatible header setup fallbacks."""

    async def test_flow_control_failure_still_allows_diagnostic_query(self):
        module = load_obd_module()

        class Message:
            @staticmethod
            def raw():
                return "OK"

        class Interface:
            def __init__(self):
                self.commands = []

            async def send_and_parse(self, command):
                self.commands.append(command)
                if command.startswith(b"AT SH"):
                    return [Message()]
                return []

        obd = object.__new__(module.OBD)
        obd.interface = Interface()
        obd._OBD__last_header = ()

        result = await obd._OBD__set_header(b"79B")

        self.assertTrue(result)
        self.assertEqual(
            obd.interface.commands,
            [
                b"AT SH 79B ",
                b"AT FC SH 79B ",
                b"AT SH 79B ",
                b"AT FC SH 79B ",
            ],
        )
        self.assertEqual(obd._OBD__last_header, ())

    async def test_header_setup_retries_and_caches_complete_success(self):
        module = load_obd_module()

        class Message:
            @staticmethod
            def raw():
                return "OK"

        class Interface:
            def __init__(self):
                self.commands = []

            async def send_and_parse(self, command):
                self.commands.append(command)
                if len(self.commands) == 1:
                    return []
                return [Message()]

        obd = object.__new__(module.OBD)
        obd.interface = Interface()
        obd._OBD__last_header = ()

        result = await obd._OBD__set_header(b"797")

        self.assertTrue(result)
        self.assertEqual(obd._OBD__last_header, b"797")

    async def test_lbc_uses_filtered_long_timeout_and_clears_filter(self):
        module = load_obd_module()

        class Message:
            @staticmethod
            def raw():
                return "OK"

        class Interface:
            def __init__(self):
                self.events = []

            def status(self):
                return module.OBDStatus.CAR_CONNECTED

            async def send_and_parse(self, command):
                self.events.append(("setup", command))
                return [Message()]

            async def send_raw(self, command):
                self.events.append(("query", command))
                return ["NO DATA"]

            @staticmethod
            def parse_lines(lines):
                return []

        command = types.SimpleNamespace(
            name="lbc",
            header=b"79B",
            command=b"022101",
            fast=False,
        )
        obd = object.__new__(module.OBD)
        obd.interface = Interface()
        obd.fast = True
        obd._OBD__last_header = ()
        obd._OBD__frame_counts = {}

        response = await obd._query_lbc(command)

        self.assertEqual(
            response.raw_lines,
            ["NO DATA", "CAF1 fallback:", "NO DATA"],
        )
        self.assertEqual(
            obd.interface.events,
            [
                ("setup", b"AT SH 79B "),
                ("setup", b"AT FC SH 79B "),
                ("setup", b"AT FC SD 30 00 00"),
                ("setup", b"AT FC SM 1"),
                ("setup", b"AT ST 96"),
                ("setup", b"AT CRA 7BB"),
                ("setup", b"AT FC SD 30 00 0A"),
                ("query", b"022101"),
                ("setup", b"AT CAF1"),
                ("query", b"21018"),
                ("setup", b"AT CAF0"),
                ("setup", b"AT CRA"),
            ],
        )

    async def test_lbc_auto_format_fallback_decodes_soc(self):
        module = load_obd_module()

        class SetupMessage:
            @staticmethod
            def raw():
                return "OK"

        class Frame:
            raw = "7BB10356101"

        class ParsedMessage:
            frames = [Frame()]
            data = b"\x61\x01\x00"

            @staticmethod
            def raw():
                return "7BB10356101"

        class Interface:
            def status(self):
                return module.OBDStatus.CAR_CONNECTED

            async def send_and_parse(self, command):
                return [SetupMessage()]

            async def send_raw(self, command):
                return ["AUTO"] if command == b"21018" else ["NO DATA"]

            @staticmethod
            def parse_lines(lines):
                return [ParsedMessage()] if lines == ["AUTO"] else []

        class Command:
            name = "lbc"
            header = b"79B"
            command = b"022101"
            fast = False

            @staticmethod
            def __call__(messages):
                return types.SimpleNamespace(
                    value={"state_of_charge": 47}, raw_lines=[]
                )

        obd = object.__new__(module.OBD)
        obd.interface = Interface()
        obd.fast = True
        obd._OBD__last_header = ()
        obd._OBD__frame_counts = {}

        response = await obd._query_lbc(Command())

        self.assertEqual(response.value, {"state_of_charge": 47})
        self.assertEqual(response.raw_lines, ["AUTO"])


class BleShutdownWiringTest(unittest.TestCase):
    """Ensure shutdown remains clean while fresh connections still reset."""

    def test_close_does_not_reset_adapter_but_create_initializes(self):
        module = ast.parse(
            (COMPONENT / "py_nissan_leaf_obd_ble" / "elm327.py").read_text()
        )

        self.assertFalse(
            _contains_constant(method_node(module, "close"), b"ATZ"),
            "close() must not send ATZ",
        )
        self.assertTrue(
            _contains_constant(method_node(module, "_initialize"), b"ATZ"),
            "create() must still send ATZ during initialization",
        )

    def test_closing_flag_stays_set_until_next_open(self):
        module = ast.parse(
            (COMPONENT / "py_nissan_leaf_obd_ble" / "bleserial.py").read_text()
        )

        close_assignments = _closing_assignments(method_node(module, "close"))
        open_assignments = _closing_assignments(method_node(module, "open"))

        self.assertIn(True, close_assignments)
        self.assertNotIn(False, close_assignments)
        self.assertIn(False, open_assignments)


class ElmInitializationLifecycleTest(unittest.IsolatedAsyncioTestCase):
    """Ensure an incomplete ELM initialization cannot retain its BLE port."""

    async def test_cancelled_initialization_closes_port(self):
        initialization_started = asyncio.Event()

        class Serial:
            instances = []

            def __init__(self, *args):
                self.timeout = None
                self.write_timeout = None
                self.closed = 0
                self.instances.append(self)

            async def close(self):
                self.closed += 1

        module = load_elm327_module(Serial)

        async def blocked_initialize(self, protocol, check_voltage, start_low_power):
            self._ELM327__status = module.OBDStatus.ELM_CONNECTED
            initialization_started.set()
            await asyncio.Event().wait()

        module.ELM327._initialize = blocked_initialize
        create_task = asyncio.create_task(
            module.ELM327.create(object(), protocol="6", timeout=5)
        )
        await initialization_started.wait()

        create_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await create_task

        self.assertEqual(Serial.instances[0].closed, 1)

    async def test_partial_initialization_closes_port(self):
        class Serial:
            instances = []

            def __init__(self, *args):
                self.timeout = None
                self.write_timeout = None
                self.closed = 0
                self.instances.append(self)

            async def close(self):
                self.closed += 1

        module = load_elm327_module(Serial)

        async def partial_initialize(self, protocol, check_voltage, start_low_power):
            self._ELM327__status = module.OBDStatus.ELM_CONNECTED

        module.ELM327._initialize = partial_initialize

        elm = await module.ELM327.create(object(), protocol="6", timeout=5)

        self.assertEqual(elm.status(), module.OBDStatus.NOT_CONNECTED)
        self.assertEqual(Serial.instances[0].closed, 1)

    async def test_transport_failure_during_initialization_closes_port(self):
        class Serial:
            instances = []

            def __init__(self, *args):
                self.timeout = None
                self.write_timeout = None
                self.closed = 0
                self.instances.append(self)

            async def close(self):
                self.closed += 1

        module = load_elm327_module(Serial)

        async def failed_initialize(self, protocol, check_voltage, start_low_power):
            raise module.BleakError("disconnected")

        module.ELM327._initialize = failed_initialize

        elm = await module.ELM327.create(object(), protocol="6", timeout=5)

        self.assertEqual(elm.status(), module.OBDStatus.NOT_CONNECTED)
        self.assertEqual(Serial.instances[0].closed, 1)


class BleSerialLifecycleTest(unittest.IsolatedAsyncioTestCase):
    """Exercise disconnect callback ordering across reconnects."""

    async def test_delayed_old_callback_does_not_clear_new_client(self):
        class Device:
            name = "IOS-VLINK"

        class Client:
            callback = None

            class Services:
                @staticmethod
                def get_characteristic(characteristic):
                    return object()

            services = Services()

            async def start_notify(self, characteristic, callback):
                return None

            async def stop_notify(self, characteristic):
                return None

            async def disconnect(self):
                return None

        old_client = Client()
        new_client = Client()
        clients = iter((old_client, new_client))

        async def establish_connection(*args, disconnected_callback, **kwargs):
            client = next(clients)
            client.callback = disconnected_callback
            return client

        bleserial_module.establish_connection = establish_connection
        serial = bleserial_module.bleserial(Device(), "service", "read", "write")

        await serial.open()
        await serial.close()
        await serial.open()
        old_client.callback(old_client)

        self.assertIs(serial._client, new_client)

    async def test_missing_characteristic_reconnects_without_service_cache(self):
        class Device:
            name = "IOS-VLINK"

        class Services:
            def __init__(self, found):
                self.found = found

            def get_characteristic(self, characteristic):
                return object() if self.found else None

        class Client:
            def __init__(self, found):
                self.services = Services(found)
                self.clear_cache = AsyncMock(return_value=True)
                self.disconnect = AsyncMock()
                self.start_notify = AsyncMock()

        stale_client = Client(False)
        fresh_client = Client(True)
        clients = iter((stale_client, fresh_client))
        cache_options = []

        async def establish_connection(*args, use_services_cache, **kwargs):
            cache_options.append(use_services_cache)
            return next(clients)

        bleserial_module.establish_connection = establish_connection
        serial = bleserial_module.bleserial(Device(), "service", "read", "write")

        with self.assertLogs(bleserial_module.logger, level="WARNING") as logs:
            await serial.open()

        self.assertEqual(cache_options, [True, False])
        self.assertIn("Expected GATT characteristic(s) missing", logs.output[0])
        stale_client.clear_cache.assert_awaited_once_with()
        stale_client.disconnect.assert_awaited_once_with()
        fresh_client.start_notify.assert_awaited_once()
        self.assertIs(serial._client, fresh_client)

    async def test_cancelled_notification_setup_disconnects_client(self):
        class Device:
            name = "IOS-VLINK"

        class Services:
            @staticmethod
            def get_characteristic(characteristic):
                return object()

        setup_started = asyncio.Event()

        class Client:
            services = Services()

            def __init__(self):
                self.disconnect = AsyncMock()

            async def start_notify(self, characteristic, callback):
                setup_started.set()
                await asyncio.Event().wait()

        client = Client()

        async def establish_connection(*args, **kwargs):
            return client

        bleserial_module.establish_connection = establish_connection
        serial = bleserial_module.bleserial(Device(), "service", "read", "write")
        open_task = asyncio.create_task(serial.open())
        await setup_started.wait()

        open_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await open_task

        client.disconnect.assert_awaited_once_with()
        self.assertIsNone(serial._client)

    async def test_disconnect_wakes_pending_read(self):
        class Device:
            name = "IOS-VLINK"

        class Services:
            @staticmethod
            def get_characteristic(characteristic):
                return object()

        class Client:
            services = Services()
            callback = None

            async def start_notify(self, characteristic, callback):
                return None

        client = Client()

        async def establish_connection(*args, disconnected_callback, **kwargs):
            client.callback = disconnected_callback
            return client

        bleserial_module.establish_connection = establish_connection
        serial = bleserial_module.bleserial(Device(), "service", "read", "write")
        serial.timeout = 1
        await serial.open()
        read_task = asyncio.create_task(serial.read())
        await asyncio.sleep(0)

        with self.assertLogs(bleserial_module.logger, level="ERROR"):
            client.callback(client)
            with self.assertRaises(bleserial_module.BleakError):
                await asyncio.wait_for(read_task, timeout=0.1)

    async def test_write_fails_when_disconnected(self):
        class Device:
            name = "IOS-VLINK"

        serial = bleserial_module.bleserial(Device(), "service", "read", "write")

        with self.assertRaisesRegex(
            bleserial_module.BleakError, "not connected"
        ):
            await serial.write(b"ATZ")

    async def test_write_uses_configured_timeout(self):
        class Device:
            name = "IOS-VLINK"

        class Client:
            async def write_gatt_char(self, characteristic, data):
                await asyncio.Event().wait()

        serial = bleserial_module.bleserial(Device(), "service", "read", "write")
        serial._client = Client()
        serial.write_timeout = 0.01

        with self.assertRaises(asyncio.TimeoutError):
            await serial.write(b"ATZ")

    async def test_read_uses_configured_timeout(self):
        class Device:
            name = "IOS-VLINK"

        serial = bleserial_module.bleserial(Device(), "service", "read", "write")
        serial._client = object()
        serial.timeout = 0.01

        with self.assertRaises(asyncio.TimeoutError):
            await serial.read()

    async def test_stop_notify_timeout_still_disconnects(self):
        class Device:
            name = "IOS-VLINK"

        class Client:
            def __init__(self):
                self.disconnect = AsyncMock()

            async def stop_notify(self, characteristic):
                await asyncio.Event().wait()

        client = Client()
        serial = bleserial_module.bleserial(Device(), "service", "read", "write")
        serial._client = client

        with patch.object(bleserial_module, "DISCONNECT_TIMEOUT", 0.01):
            await serial.close()

        client.disconnect.assert_awaited_once_with()
        self.assertIsNone(serial._client)

    async def test_disconnect_timeout_does_not_block_close(self):
        class Device:
            name = "IOS-VLINK"

        class Client:
            async def stop_notify(self, characteristic):
                return None

            async def disconnect(self):
                await asyncio.Event().wait()

        serial = bleserial_module.bleserial(Device(), "service", "read", "write")
        serial._client = Client()

        with patch.object(bleserial_module, "DISCONNECT_TIMEOUT", 0.01):
            await asyncio.wait_for(serial.close(), timeout=0.1)

        self.assertIsNone(serial._client)

    async def test_cancelled_stop_notify_still_disconnects(self):
        class Device:
            name = "IOS-VLINK"

        stop_started = asyncio.Event()

        class Client:
            def __init__(self):
                self.disconnect = AsyncMock()

            async def stop_notify(self, characteristic):
                stop_started.set()
                await asyncio.Event().wait()

        client = Client()
        serial = bleserial_module.bleserial(Device(), "service", "read", "write")
        serial._client = client
        close_task = asyncio.create_task(serial.close())
        await stop_started.wait()

        close_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await close_task

        client.disconnect.assert_awaited_once_with()
        self.assertIsNone(serial._client)

    async def test_cancelled_disconnect_finishes_before_close_returns(self):
        class Device:
            name = "IOS-VLINK"

        disconnect_started = asyncio.Event()
        allow_disconnect = asyncio.Event()
        disconnect_finished = asyncio.Event()

        class Client:
            async def stop_notify(self, characteristic):
                return None

            async def disconnect(self):
                disconnect_started.set()
                await allow_disconnect.wait()
                disconnect_finished.set()

        serial = bleserial_module.bleserial(Device(), "service", "read", "write")
        serial._client = Client()
        close_task = asyncio.create_task(serial.close())
        await disconnect_started.wait()

        close_task.cancel()
        await asyncio.sleep(0)
        close_task.cancel()
        await asyncio.sleep(0)
        allow_disconnect.set()
        with self.assertRaises(asyncio.CancelledError):
            await close_task

        self.assertTrue(disconnect_finished.is_set())
        self.assertIsNone(serial._client)

    async def test_cancelled_disconnect_coroutine_does_not_loop_forever(self):
        class Device:
            name = "IOS-VLINK"

        class Client:
            async def stop_notify(self, characteristic):
                return None

            async def disconnect(self):
                raise asyncio.CancelledError

        serial = bleserial_module.bleserial(Device(), "service", "read", "write")
        serial._client = Client()

        await asyncio.wait_for(serial.close(), timeout=0.1)

        self.assertIsNone(serial._client)


if __name__ == "__main__":
    unittest.main()
