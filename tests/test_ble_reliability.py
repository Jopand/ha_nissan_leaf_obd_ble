"""Static regression tests for BLE polling reliability and cached values.

These tests never import Home Assistant; they parse the component source and
assert the wiring that keeps cached sensor values alive across failed polls
and the clean-disconnect behavior of the ELM327 port close.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "ha_nissan_leaf_obd_ble"


def method_node(module: ast.Module, name: str) -> ast.AsyncFunctionDef:
    """Return the first async method named `name` found in the module."""
    for node in ast.walk(module):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Async method {name!r} not found")


def _is_self_cache_attr(node) -> bool:
    """Return True for an expression like `self._cache_data`."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "_cache_data"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _is_update_failed_raise(stmt) -> bool:
    """Return True for a `raise UpdateFailed(...)` statement."""
    if not isinstance(stmt, ast.Raise) or stmt.exc is None:
        return False
    exc = stmt.exc
    if isinstance(exc, ast.Name):
        return exc.id == "UpdateFailed"
    if isinstance(exc, ast.Call):
        return isinstance(exc.func, ast.Name) and exc.func.id == "UpdateFailed"
    return False


def _returns_cached_dict(stmts) -> bool:
    """Return True if any statement is `return dict(self._cache_data)`."""
    for stmt in stmts:
        if not isinstance(stmt, ast.Return) or stmt.value is None:
            continue
        value = stmt.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "dict"
            and value.args
            and _is_self_cache_attr(value.args[0])
        ):
            return True
    return False


def _cache_guard(stmts):
    """Return the leading `if self._cache_data: return dict(...)` or None.

    Expected structure of every failure path:
        if self._cache_data:
            ...logging / interval adjust...
            return dict(self._cache_data)
        raise UpdateFailed(...)
    """
    if stmts and isinstance(stmts[0], ast.If) and _is_self_cache_attr(stmts[0].test):
        if _returns_cached_dict(stmts[0].body):
            return stmts[0]
    return None


def _contains_constant(node, value) -> bool:
    """Return True if a literal constant equal to `value` appears in `node`."""
    for child in ast.walk(node):
        if isinstance(child, ast.Constant):
            try:
                if child.value == value:
                    return True
            except Exception:  # noqa: BLE001 - unhashable literals are irrelevant
                pass
    return False


class BleReliabilityWiringTest(unittest.TestCase):
    """Ensure failed polls keep cached values and shutdown does not reset."""

    def test_update_failed_is_always_guarded_by_cached_data(self):
        module = ast.parse((COMPONENT / "coordinator.py").read_text())
        method = method_node(module, "_async_update_data")

        containers = [
            node
            for node in ast.walk(method)
            if (
                (isinstance(node, ast.ExceptHandler) or isinstance(node, ast.If))
                and any(_is_update_failed_raise(stmt) for stmt in node.body)
            )
        ]

        self.assertEqual(
            len(containers), 3,
            "expected cache-guards in the timeout, generic, and no-data paths",
        )
        for container in containers:
            with self.subTest(kind=type(container).__name__):
                self.assertIsNotNone(
                    _cache_guard(container.body),
                    "every UpdateFailed path must first return cached data when present",
                )

    def test_coordinator_merges_fresh_values_none_safe(self):
        src = (COMPONENT / "coordinator.py").read_text()
        self.assertIn("merge_cached_values(self._cache_data, new_data)", src)

    def test_close_does_not_reset_adapter_but_create_initializes(self):
        module = ast.parse((COMPONENT / "py_nissan_leaf_obd_ble" / "elm327.py").read_text())

        self.assertFalse(
            _contains_constant(method_node(module, "close"), b"ATZ"),
            "close() must not send ATZ (it makes iCar Pro 2S drop the BLE link)",
        )
        self.assertTrue(
            _contains_constant(method_node(module, "create"), b"ATZ"),
            "create() must still send ATZ as part of fresh connection init",
        )

    def test_intentional_close_marks_client_as_closing(self):
        module = ast.parse((COMPONENT / "py_nissan_leaf_obd_ble" / "bleserial.py").read_text())
        close = method_node(module, "close")

        closing_assigns = [
            node
            for node in ast.walk(close)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and target.attr == "_closing"
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                for target in node.targets
            )
        ]
        self.assertTrue(
            any(node.value.value is True for node in closing_assigns),
            "close() must set _closing=True so disconnect is logged as expected",
        )


if __name__ == "__main__":
    unittest.main()