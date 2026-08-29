"""Regression tests for BLE polling reliability and cached values."""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
            "homeassistant.components.bluetooth"
        ),
        "homeassistant.components.bluetooth.api": _module(
            "homeassistant.components.bluetooth.api",
            async_address_present=lambda *args, **kwargs: True,
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


class FakeApi:
    """Return or raise a configured poll result."""

    def __init__(self, result) -> None:
        self.result = result
        self.calls = 0

    async def async_get_data(self, **kwargs):
        self.calls += 1
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
    coordinator._normalize_metrics = lambda data: False
    coordinator._async_save_cache = AsyncMock()
    coordinator.update_interval = None
    coordinator_module.async_address_present = (
        lambda *args, **kwargs: available
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

        data = await coordinator._async_update_data()

        self.assertEqual(
            data, {"state_of_charge": 61.0, "odometer": 98439}
        )
        self.assertEqual(coordinator.update_interval, timedelta(seconds=10))
        coordinator._async_save_cache.assert_awaited_once_with()

    async def test_no_valid_fields_keeps_cache_without_saving(self):
        coordinator = make_coordinator(
            {"state_of_charge": None}, {"state_of_charge": 61.0}
        )

        data = await coordinator._async_update_data()

        self.assertEqual(data, {"state_of_charge": 61.0})
        self.assertEqual(coordinator.update_interval, timedelta(seconds=300))
        coordinator._async_save_cache.assert_not_awaited()

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
            _contains_constant(method_node(module, "create"), b"ATZ"),
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


class BleSerialLifecycleTest(unittest.IsolatedAsyncioTestCase):
    """Exercise disconnect callback ordering across reconnects."""

    async def test_delayed_old_callback_does_not_clear_new_client(self):
        class Device:
            name = "IOS-VLINK"

        class Client:
            callback = None

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


if __name__ == "__main__":
    unittest.main()
