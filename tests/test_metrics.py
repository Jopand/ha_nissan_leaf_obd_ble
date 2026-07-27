"""Regression tests for odometer and battery calculations."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "ha_nissan_leaf_obd_ble"
    / "metrics.py"
)
SPEC = importlib.util.spec_from_file_location("nissan_leaf_metrics", MODULE_PATH)
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


class MetricsTest(unittest.TestCase):
    """Cover reported odometer and SOH regressions."""

    def test_ze1_odometer_command(self):
        self.assertEqual(metrics.ZE1_ODOMETER_COMMAND, b"03220e01")
        self.assertEqual(metrics.ZE1_ODOMETER_EXPECTED_BYTES, 0)

    def test_valid_ze1_odometer_response(self):
        self.assertEqual(
            metrics.decode_ze1_odometer(bytes.fromhex("620e0101572c")),
            87852,
        )

    def test_negative_response_is_not_an_odometer(self):
        self.assertIsNone(
            metrics.decode_ze1_odometer(bytes.fromhex("7f1012000000"))
        )

    def test_malformed_and_zero_responses_are_rejected(self):
        self.assertIsNone(metrics.decode_ze1_odometer(b""))
        self.assertIsNone(
            metrics.decode_ze1_odometer(bytes.fromhex("620e0101"))
        )
        self.assertIsNone(
            metrics.decode_ze1_odometer(bytes.fromhex("620e01000000"))
        )

    def test_legacy_40_kwh_capacity_is_migrated(self):
        self.assertEqual(metrics.migrate_nominal_ah(105.6), 115.0)

    def test_40_kwh_soh_matches_reported_value(self):
        self.assertAlmostEqual(metrics.calculate_soh(100.8, 115.0), 87.7, places=1)

    def test_cached_metrics_are_normalized(self):
        data = {
            "odometer": 2131759616,
            "hv_battery_Ah": 100.8,
            "state_of_health": 95.5,
        }

        self.assertTrue(metrics.normalize_metrics(data, 115.0))
        self.assertNotIn("odometer", data)
        self.assertAlmostEqual(data["state_of_health"], 87.7, places=1)

    def test_invalid_fresh_capacity_is_ignored(self):
        data = {"hv_battery_Ah": 0, "state_of_health": 95.5}

        self.assertTrue(metrics.normalize_metrics(data, 115.0))
        self.assertNotIn("hv_battery_Ah", data)
        self.assertNotIn("state_of_health", data)


if __name__ == "__main__":
    unittest.main()
