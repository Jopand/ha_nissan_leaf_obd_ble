"""Constants for Nissan Leaf OBD BLE (ha_nissan_leaf_obd_ble)."""

from __future__ import annotations

NAME = "Nissan Leaf OBD BLE"
DOMAIN = "ha_nissan_leaf_obd_ble"
VERSION = "1.1.0"

ISSUE_URL = "https://github.com/Jopand/ha_nissan_leaf_obd_ble/issues"

# Configuration keys — stored in config entry DATA (require re-adding to change)
CONF_GENERATION = "generation"

# Configuration keys — stored in config entry OPTIONS (changeable via Configure)
CONF_SERVICE_UUID = "service_uuid"
CONF_CHARACTERISTIC_UUID_READ = "characteristic_uuid_read"
CONF_CHARACTERISTIC_UUID_WRITE = "characteristic_uuid_write"
CONF_NOMINAL_AH = "nominal_ah"

# Default BLE UUIDs (LeLink2 / OBDBLE dongle)
DEFAULT_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
DEFAULT_CHARACTERISTIC_UUID_READ = "0000ffe1-0000-1000-8000-00805f9b34fb"
DEFAULT_CHARACTERISTIC_UUID_WRITE = "0000ffe1-0000-1000-8000-00805f9b34fb"

# Vgate iCar Pro BLE / IOS-VLINK UUIDs
VGATE_ICAR_SERVICE_UUID = "e7810a71-73ae-499d-8c15-faa9aef0c3f2"
VGATE_ICAR_CHARACTERISTIC_UUID = "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"

DEFAULT_ADAPTER_PROFILE = {
    CONF_SERVICE_UUID: DEFAULT_SERVICE_UUID,
    CONF_CHARACTERISTIC_UUID_READ: DEFAULT_CHARACTERISTIC_UUID_READ,
    CONF_CHARACTERISTIC_UUID_WRITE: DEFAULT_CHARACTERISTIC_UUID_WRITE,
}
VGATE_ICAR_ADAPTER_PROFILE = {
    CONF_SERVICE_UUID: VGATE_ICAR_SERVICE_UUID,
    CONF_CHARACTERISTIC_UUID_READ: VGATE_ICAR_CHARACTERISTIC_UUID,
    CONF_CHARACTERISTIC_UUID_WRITE: VGATE_ICAR_CHARACTERISTIC_UUID,
}

# BLE local-name prefixes to search for when scanning for adapters
BLE_LOCAL_NAMES = {"OBDBLE", "IOS-Vlink"}
SUPPORTED_SERVICE_UUIDS = {DEFAULT_SERVICE_UUID, VGATE_ICAR_SERVICE_UUID}


def is_supported_adapter(
    name: str | None, service_uuids: list[str] | tuple[str, ...] | None = None
) -> bool:
    """Return whether advertised name or service identifies a supported adapter."""
    device_name = (name or "").casefold()
    advertised_services = {
        service_uuid.casefold() for service_uuid in (service_uuids or [])
    }
    return any(
        device_name.startswith(prefix.casefold()) for prefix in BLE_LOCAL_NAMES
    ) or bool(
        advertised_services
        & {service_uuid.casefold() for service_uuid in SUPPORTED_SERVICE_UUIDS}
    )


def get_adapter_profile(
    name: str | None, service_uuids: list[str] | tuple[str, ...] | None = None
) -> dict[str, str]:
    """Return initial GATT defaults for a discovered BLE adapter."""
    advertised_services = {
        service_uuid.casefold() for service_uuid in (service_uuids or [])
    }
    if VGATE_ICAR_SERVICE_UUID.casefold() in advertised_services:
        return dict(VGATE_ICAR_ADAPTER_PROFILE)
    if (name or "").casefold().startswith("ios-vlink"):
        return dict(VGATE_ICAR_ADAPTER_PROFILE)
    return dict(DEFAULT_ADAPTER_PROFILE)

# Generation identifiers
GENERATION_AUTO = "auto"
GENERATION_ZE0 = "ze0"
GENERATION_AZE0 = "aze0"
GENERATION_ZE1 = "ze1"

# Human-readable labels for UI display
GENERATION_OPTIONS: dict[str, str] = {
    GENERATION_ZE0: "ZE0 — 2010–2017 Nissan Leaf (uses passive CAN odometer)",
    GENERATION_AZE0: "AZE0 — 2017–2018 Nissan Leaf (uses passive CAN odometer)",
    GENERATION_ZE1: "ZE1 — 2018+ Nissan Leaf",
    GENERATION_AUTO: "Auto — all generations (recommended if unsure)",
}

# New-pack Ah capacity references by battery size (used to calculate SOH)
BATTERY_NOMINAL_AH: dict[int, float] = {
    24: 66.0,
    30: 79.48,
    40: 115.0,
    62: 176.0,
}

# Default nominal Ah if user doesn't specify (30 kWh is most common)
DEFAULT_NOMINAL_AH = 79.48

# Default polling intervals (seconds)
DEFAULT_FAST_POLL = 10
DEFAULT_SLOW_POLL = 300
DEFAULT_XS_POLL = 3600
DEFAULT_FETCH_TIMEOUT = 90

# Storage — persists last-known sensor values across HA restarts
STORAGE_KEY = f"{DOMAIN}.sensor_cache"
STORAGE_VERSION = 1

STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
Custom integration — report issues at: {ISSUE_URL}
-------------------------------------------------------------------
"""
