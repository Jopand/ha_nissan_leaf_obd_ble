"""Static wiring tests that do not require Home Assistant dependencies."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "ha_nissan_leaf_obd_ble"


def assignment_value(path: Path, name: str) -> ast.AST:
    """Return the value node for a named module-level assignment."""
    module = ast.parse(path.read_text())
    for node in module.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return node.value
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return node.value
    raise AssertionError(f"Assignment {name!r} not found in {path}")


class FeatureWiringTest(unittest.TestCase):
    """Ensure commands, vehicle profiles, and entities remain consistent."""

    def test_display_soc_command_and_range_safety(self):
        commands_path = COMPONENT / "py_nissan_leaf_obd_ble" / "commands.py"
        command_table = assignment_value(commands_path, "leaf_commands")
        commands = {
            ast.literal_eval(key): value
            for key, value in zip(command_table.keys, command_table.values)
        }

        display_args = commands["display_state_of_charge"].args
        self.assertEqual(ast.literal_eval(display_args[2]), b"03221204")
        self.assertEqual(ast.literal_eval(display_args[3]), 0)
        self.assertEqual(
            ast.literal_eval(commands["display_state_of_charge"].keywords[0].value),
            b"797",
        )

        range_args = commands["range_remaining"].args
        self.assertEqual(ast.literal_eval(range_args[3]), 0)

    def test_old_generations_do_not_query_or_expose_display_soc(self):
        profiles_path = COMPONENT / "py_nissan_leaf_obd_ble" / "profiles.py"
        for profile_name in ("PROFILE_ZE0", "PROFILE_AZE0"):
            profile = ast.literal_eval(assignment_value(profiles_path, profile_name))
            self.assertIn("display_state_of_charge", profile["disabled_commands"])

        generations_path = COMPONENT / "generations.py"
        exclusions = ast.literal_eval(
            assignment_value(generations_path, "_ZE0_EXCLUDED")
        )
        self.assertIn("display_state_of_charge", exclusions)

    def test_soc_entity_names_are_distinct(self):
        sensors = assignment_value(COMPONENT / "generations.py", "_ALL_SENSORS")
        descriptions = {
            ast.literal_eval(key): value
            for key, value in zip(sensors.keys, sensors.values)
        }

        names = {}
        for key in ("state_of_charge", "display_state_of_charge"):
            names[key] = next(
                ast.literal_eval(keyword.value)
                for keyword in descriptions[key].keywords
                if keyword.arg == "name"
            )
        self.assertEqual(names["state_of_charge"], "BMS state of charge")
        self.assertEqual(
            names["display_state_of_charge"], "Display state of charge"
        )

    def test_failed_connection_does_not_reach_query_loop(self):
        obd_module = ast.parse(
            (COMPONENT / "py_nissan_leaf_obd_ble" / "obd.py").read_text()
        )
        create_method = next(
            node
            for node in ast.walk(obd_module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "create"
        )
        self.assertTrue(
            any(
                isinstance(node, ast.Return)
                and isinstance(node.value, ast.Constant)
                and node.value.value is None
                for node in ast.walk(create_method)
            )
        )

    def test_refresh_button_and_diagnostics_are_wired(self):
        platforms = assignment_value(COMPONENT / "__init__.py", "PLATFORMS")
        platform_names = {
            element.attr
            for element in platforms.elts
            if isinstance(element, ast.Attribute)
        }
        self.assertEqual(platform_names, {"BUTTON", "SENSOR"})

        button_module = ast.parse((COMPONENT / "button.py").read_text())
        press_method = next(
            node
            for node in ast.walk(button_module)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_press"
        )
        self.assertTrue(
            any(
                isinstance(node, ast.Attribute)
                and node.attr == "async_request_refresh"
                for node in ast.walk(press_method)
            )
        )

        diagnostic_descriptions = assignment_value(
            COMPONENT / "sensor.py", "DIAGNOSTIC_SENSORS"
        )
        diagnostic_keys = {
            ast.literal_eval(
                next(
                    keyword.value
                    for keyword in call.keywords
                    if keyword.arg == "key"
                )
            )
            for call in diagnostic_descriptions.elts
        }
        self.assertEqual(
            diagnostic_keys,
            {
                "last_poll_attempt",
                "last_successful_update",
                "last_fresh_value_count",
                "last_ble_route",
            },
        )


if __name__ == "__main__":
    unittest.main()
