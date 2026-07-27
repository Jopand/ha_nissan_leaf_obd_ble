"""Validation and calculated metrics for Nissan Leaf data."""

from __future__ import annotations

from numbers import Real
from typing import Optional

MAX_ODOMETER_KM = 0xFFFFFF
ZE1_ODOMETER_COMMAND = b"03220e01"
ZE1_ODOMETER_EXPECTED_BYTES = 0
ZE1_ODOMETER_RESPONSE_PREFIX = b"\x62\x0e\x01"

LEGACY_NOMINAL_AH = {
    60.6: 66.0,
    105.6: 115.0,
    167.6: 176.0,
}


def decode_ze1_odometer(data: bytes) -> Optional[int]:
    """Decode a validated ReadDataByIdentifier response for PID 0x0E01."""
    if len(data) != 6 or data[:3] != ZE1_ODOMETER_RESPONSE_PREFIX:
        return None

    value = int.from_bytes(data[3:6], byteorder="big", signed=False)
    return value if is_valid_odometer(value) else None


def is_valid_odometer(value: object) -> bool:
    """Return whether a value can be a 24-bit Leaf odometer reading."""
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and 0 < value <= MAX_ODOMETER_KM
    )


def calculate_soh(capacity_ah: object, nominal_ah: object) -> Optional[float]:
    """Calculate battery state of health from present and new-pack capacity."""
    if (
        not isinstance(capacity_ah, Real)
        or isinstance(capacity_ah, bool)
        or not isinstance(nominal_ah, Real)
        or isinstance(nominal_ah, bool)
        or capacity_ah <= 0
        or nominal_ah <= 0
    ):
        return None
    return float(capacity_ah) / float(nominal_ah) * 100


def migrate_nominal_ah(value: object) -> object:
    """Map legacy usable-capacity values to new-pack capacity references."""
    if not isinstance(value, Real) or isinstance(value, bool):
        return value
    return LEGACY_NOMINAL_AH.get(float(value), value)


def normalize_metrics(data: dict, nominal_ah: object) -> bool:
    """Normalize persisted or freshly decoded calculated metrics in place."""
    changed = False

    if "odometer" in data and not is_valid_odometer(data["odometer"]):
        data.pop("odometer")
        changed = True

    capacity_ah = data.get("hv_battery_Ah")
    if "hv_battery_Ah" in data and (
        not isinstance(capacity_ah, Real)
        or isinstance(capacity_ah, bool)
        or capacity_ah <= 0
    ):
        data.pop("hv_battery_Ah")
        capacity_ah = None
        changed = True

    soh = calculate_soh(capacity_ah, nominal_ah)
    if soh is None:
        if "state_of_health" in data:
            data.pop("state_of_health")
            changed = True
    elif data.get("state_of_health") != soh:
        data["state_of_health"] = soh
        changed = True

    return changed
