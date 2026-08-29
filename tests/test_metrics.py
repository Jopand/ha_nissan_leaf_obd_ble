"""Regression tests for ZE1 metrics and battery calculations."""

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

    def test_reported_ze1_odometer_capture(self):
        self.assertEqual(
            metrics.decode_ze1_odometer(bytes.fromhex("620e01018087")),
            98439,
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

    def test_reported_display_soc_capture(self):
        self.assertEqual(
            metrics.decode_ze1_display_soc(bytes.fromhex("621204000012f8")),
            48.56,
        )

    def test_display_soc_boundaries(self):
        self.assertEqual(
            metrics.decode_ze1_display_soc(bytes.fromhex("62120400000000")),
            0,
        )
        self.assertEqual(
            metrics.decode_ze1_display_soc(bytes.fromhex("62120400002710")),
            100,
        )

    def test_invalid_display_soc_responses_are_rejected(self):
        self.assertIsNone(metrics.decode_ze1_display_soc(b""))
        self.assertIsNone(
            metrics.decode_ze1_display_soc(bytes.fromhex("621204000012"))
        )
        self.assertIsNone(
            metrics.decode_ze1_display_soc(bytes.fromhex("621205000012f8"))
        )
        self.assertIsNone(
            metrics.decode_ze1_display_soc(bytes.fromhex("62120400002711"))
        )

    def test_reported_range_capture_is_only_validated(self):
        self.assertTrue(
            metrics.is_valid_ze1_range_response(
                bytes.fromhex("620e2400284208800208000000")
            )
        )
        self.assertFalse(metrics.is_valid_ze1_range_response(b""))
        self.assertFalse(
            metrics.is_valid_ze1_range_response(
                bytes.fromhex("620e2500284208800208000000")
            )
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
            "range_remaining": 4.0,
        }

        self.assertTrue(metrics.normalize_metrics(data, 115.0))
        self.assertNotIn("odometer", data)
        self.assertAlmostEqual(data["state_of_health"], 87.7, places=1)
        self.assertIsNone(data["range_remaining"])

    def test_invalid_fresh_capacity_is_ignored(self):
        data = {"hv_battery_Ah": 0, "state_of_health": 95.5}

        self.assertTrue(metrics.normalize_metrics(data, 115.0))
        self.assertNotIn("hv_battery_Ah", data)
        self.assertNotIn("state_of_health", data)

    def test_merge_cached_values_keeps_last_known_state(self):
        cache = {"state_of_charge": 61.0, "odometer": 100, "range_remaining": None}
        fresh = {"state_of_charge": 63.0, "range_remaining": None}

        merged = metrics.merge_cached_values(cache, fresh)

        self.assertEqual(merged["state_of_charge"], 63.0)
        self.assertEqual(merged["odometer"], 100)
        self.assertIsNone(merged["range_remaining"])

    def test_merge_cached_values_ignores_none_fields(self):
        cache = {"state_of_charge": 61.0, "eco_mode": None}

        merged = metrics.merge_cached_values(
            cache, {"state_of_charge": None, "eco_mode": True}
        )

        self.assertEqual(merged["state_of_charge"], 61.0)
        self.assertEqual(merged["eco_mode"], True)

    def test_merge_cached_values_does_not_mutate_inputs(self):
        cache = {"state_of_charge": 61.0}
        fresh = {"state_of_charge": 55.0}

        merged = metrics.merge_cached_values(cache, fresh)

        self.assertEqual(merged["state_of_charge"], 55.0)
        self.assertEqual(cache["state_of_charge"], 61.0)
        self.assertEqual(fresh, {"state_of_charge": 55.0})

    def test_merge_cached_values_returns_a_copy(self):
        cache = {"state_of_charge": 61.0}

        merged = metrics.merge_cached_values(cache, {})

        self.assertEqual(merged, cache)
        self.assertIsNot(merged, cache)


if __name__ == "__main__":
    unittest.main()
