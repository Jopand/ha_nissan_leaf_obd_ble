"""Regression tests for BLE adapter defaults and discovery metadata."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "ha_nissan_leaf_obd_ble"
SPEC = importlib.util.spec_from_file_location("nissan_leaf_const", COMPONENT / "const.py")
const = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(const)


class AdapterProfileTest(unittest.TestCase):
    """Cover automatic LeLink and Vgate GATT defaults."""

    def test_ios_vlink_names_select_vgate_profile(self):
        for name in ("IOS-VLINK", "ios-vlink", "Ios-Vlink-1234"):
            with self.subTest(name=name):
                profile = const.get_adapter_profile(name)
                self.assertEqual(
                    profile[const.CONF_SERVICE_UUID],
                    const.VGATE_ICAR_SERVICE_UUID,
                )
                self.assertEqual(
                    profile[const.CONF_CHARACTERISTIC_UUID_READ],
                    const.VGATE_ICAR_CHARACTERISTIC_UUID,
                )
                self.assertEqual(
                    profile[const.CONF_CHARACTERISTIC_UUID_WRITE],
                    const.VGATE_ICAR_CHARACTERISTIC_UUID,
                )

    def test_vgate_service_uuid_takes_precedence_over_name(self):
        profile = const.get_adapter_profile(
            "OBDBLE",
            [const.VGATE_ICAR_SERVICE_UUID.upper()],
        )
        self.assertEqual(
            profile[const.CONF_SERVICE_UUID], const.VGATE_ICAR_SERVICE_UUID
        )

    def test_known_service_uuid_is_supported_without_known_name(self):
        self.assertTrue(
            const.is_supported_adapter(
                "Unexpected name", [const.VGATE_ICAR_SERVICE_UUID.upper()]
            )
        )
        self.assertTrue(
            const.is_supported_adapter("Unexpected name", [const.DEFAULT_SERVICE_UUID])
        )
        self.assertFalse(const.is_supported_adapter("Unexpected name", []))

    def test_obdble_and_unknown_names_keep_default_profile(self):
        for name in ("OBDBLE-1234", "Unknown adapter", None):
            with self.subTest(name=name):
                self.assertEqual(
                    const.get_adapter_profile(name),
                    const.DEFAULT_ADAPTER_PROFILE,
                )

    def test_manifest_discovers_both_adapter_services(self):
        manifest = json.loads((COMPONENT / "manifest.json").read_text())
        services = {matcher["service_uuid"] for matcher in manifest["bluetooth"]}
        self.assertEqual(
            services,
            {const.DEFAULT_SERVICE_UUID, const.VGATE_ICAR_SERVICE_UUID},
        )
        self.assertEqual(manifest["version"], const.VERSION)


if __name__ == "__main__":
    unittest.main()
