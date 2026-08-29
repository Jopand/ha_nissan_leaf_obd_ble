"""Validation and calculated metrics for Nissan Leaf data."""

from __future__ import annotations

from numbers import Real
from typing import Optional

MAX_ODOMETER_KM = 0xFFFFFF
ZE1_ODOMETER_COMMAND = b"03220e01"
ZE1_ODOMETER_EXPECTED_BYTES = 0
ZE1_ODOMETER_RESPONSE_PREFIX = b"\x62\x0e\x01"
ZE1_DISPLAY_SOC_RESPONSE_PREFIX = b"\x62\x12\x04"
ZE1_RANGE_RESPONSE_PREFIX = b"\x62\x0e\x24"
ZE1_RANGE_RESPONSE_LENGTH = 13

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


def decode_ze1_display_soc(data: bytes) -> Optional[float]:
    """Decode dashboard SOC from a validated VCM DID 0x1204 response."""
    if len(data) < 7 or data[:3] != ZE1_DISPLAY_SOC_RESPONSE_PREFIX:
        return None

    value = int.from_bytes(data[5:7], byteorder="big", signed=False) / 100
    return value if 0 <= value <= 100 else None


def is_valid_ze1_range_response(data: bytes) -> bool:
    """Validate the known ZE1 range response envelope without decoding it."""
    return (
        len(data) == ZE1_RANGE_RESPONSE_LENGTH
        and data[:3] == ZE1_RANGE_RESPONSE_PREFIX
    )


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


def merge_cached_values(cache: dict, fresh: dict) -> dict:
    """Merge fresh readings into cached values without losing valid state.

    A missing or None field in `fresh` never overwrites an existing cached
    value, so a partial or failed poll keeps every sensor's last known value
    instead of making it unavailable/changed to unknown.
    """
    merged = dict(cache)
    for key, value in dict(fresh).items():
        if value is not None:
            merged[key] = value
    return merged


def normalize_metrics(data: dict, nominal_ah: object) -> bool:
    """Normalize persisted or freshly decoded calculated metrics in place."""
    changed = False

    if "odometer" in data and not is_valid_odometer(data["odometer"]):
        data.pop("odometer")
        changed = True

    # DID 0x0E24 is not decoded yet; discard values produced by the old formula.
    if data.get("range_remaining") is not None:
        data["range_remaining"] = None
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
