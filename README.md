# Nissan Leaf OBD BLE — Home Assistant Custom Integration

A Home Assistant custom integration for monitoring Nissan Leaf battery and
vehicle data through Bluetooth Low Energy ELM327 OBD-II adapters, including
LeLink2 and Vgate iCar Pro devices.

This repository is a fork of
[hucknz/ha_nissan_leaf_obd_ble](https://github.com/hucknz/ha_nissan_leaf_obd_ble),
which builds on the original
[pbutterworth/nissan-leaf-obd-ble](https://github.com/pbutterworth/nissan-leaf-obd-ble)
integration. It includes the following functionality:

| Feature | Behavior |
|---|---|
| OBD adapter selection | Dropdown of discovered adapters |
| Adapter name matching | Case-insensitive `OBDBLE` and `IOS-Vlink` prefix matching |
| Generation support | Built-in ZE0, AZE0, ZE1, and automatic profiles |
| ZE0/AZE0 odometer | Passive CAN broadcast (`0x5C5`) |
| ZE0/AZE0 battery decoder | Generation-specific byte offsets |
| Sensor list | Trimmed to the selected generation's supported sensors |
| Data persistence | Last-known values persisted to Home Assistant storage |

---

## Supported hardware

| Item | Notes |
|---|---|
| LeLink2 ELM327 BLE OBD-II adapter | Discovered by the `OBDBLE` advertised-name prefix |
| Vgate iCar Pro BLE OBD-II adapter | Discovered by the `IOS-Vlink` advertised-name prefix |
| Other compatible ELM327 BLE adapters | May be discovered by the default BLE service UUID; GATT UUIDs are configurable |
| ESPHome Bluetooth Proxy (e.g. GL-iNet GL-S10) | Recommended for garage setups |

Advertised-name prefixes are matched case-insensitively, so variants such as
`obdble`, `ObdBle-1234`, `ios-vlink`, and `IOS-VLINK-1234` are supported.

## Supported vehicles

| Generation | Years | Notes |
|---|---|---|
| ZE0 | 2010–2017 | Odometer via passive CAN broadcast; ZE0 battery decoder |
| AZE0 | 2017–2018 | Same as ZE0 profile |
| ZE1 | 2018+ | Active KWP2000 odometer; includes e-Pedal sensor |
| Auto | All | All sensors enabled; uses ZE1 decoders (ZE0/AZE0 owners should pick their generation for accurate battery data) |

---

## Requirements

- Home Assistant with a local Bluetooth adapter or ESPHome Bluetooth proxy.
- A compatible BLE ELM327 OBD-II adapter visible to Home Assistant.

The required Nissan Leaf OBD BLE library is bundled with this integration; no
separate Python package installation is required.

---

## Installation

### Option 1 — HACS (Custom Repository)

1. Open HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/Jopand/ha_nissan_leaf_obd_ble` with category **Integration**.
3. Find *Nissan Leaf OBD BLE* and click **Download**.
4. Restart Home Assistant.

### Option 2 — Manual

1. Copy the `custom_components/ha_nissan_leaf_obd_ble/` folder into your HA
   `config/custom_components/` directory.
2. Restart Home Assistant.

---

## Setup

1. Plug the OBD adapter into the Nissan Leaf's OBD-II port and turn on the
   ignition (or accessory mode).
2. In Home Assistant: **Settings → Devices & Services → Add Integration →
   Nissan Leaf OBD BLE**.
3. **Step 1 — OBD adapter**: Select your adapter from the dropdown.  If it
   doesn't appear, check that it advertises an `OBDBLE` or `IOS-Vlink` name,
   is powered, and is within BLE range.
4. **Step 2 — Leaf generation**: Select your Leaf platform.

   | Label | Choose if… |
   |---|---|
   | ZE0 — 2010–2017 | Your Leaf is a pre-facelift (original) model |
   | AZE0 — 2017–2018 | Your Leaf is the 2017 or 2018 refresh |
   | ZE1 — 2018+ | Your Leaf is the second-generation (40 kWh / 62 kWh) |
   | Auto | You're unsure — all sensors enabled, ZE1 decoders used |

5. **Step 3 — Battery size**: Select your Leaf's battery capacity for accurate
   State of Health calculations.
6. Click **Submit**.  HA will create the device and all generation-appropriate
   sensor entities.

If your adapter uses non-standard GATT UUIDs, configure them afterward using
the integration's **Configure** button.

---

## Sensors

### All generations

| Entity | Unit | Description |
|---|---|---|
| `sensor.nissan_leaf_state_of_charge` | % | Battery charge level |
| `sensor.nissan_leaf_hv_battery_health` | % | Battery state of health |
| `sensor.nissan_leaf_hv_battery_capacity` | Ah | Battery capacity |
| `sensor.nissan_leaf_hv_battery_voltage` | V | HV battery pack voltage |
| `sensor.nissan_leaf_hv_battery_current_1` | A | Pack current (channel 1) |
| `sensor.nissan_leaf_hv_battery_current_2` | A | Pack current (channel 2) |
| `sensor.nissan_leaf_odometer` | km | Total distance travelled |
| `sensor.nissan_leaf_range_remaining` | km | Estimated remaining range |
| `sensor.nissan_leaf_speed` | km/h | Vehicle speed |
| `sensor.nissan_leaf_motor_power` | W | Traction motor power |
| `sensor.nissan_leaf_gear_position` | — | Park / Reverse / Neutral / Drive / Eco |
| `sensor.nissan_leaf_charge_mode` | — | Not charging / L1 / L2 / L3 |
| `sensor.nissan_leaf_plug_state` | — | Not plugged / Partial / Plugged |
| `sensor.nissan_leaf_rpm` | RPM | Motor speed |
| `sensor.nissan_leaf_ambient_temp` | °C | Outside air temperature |
| `sensor.nissan_leaf_bat_12v_voltage` | V | 12V auxiliary battery voltage |
| `sensor.nissan_leaf_bat_12v_current` | A | 12V auxiliary battery current |
| `sensor.nissan_leaf_quick_charges` | — | Number of quick (CHAdeMO) charges |
| `sensor.nissan_leaf_l1_l2_charges` | — | Number of L1/L2 charges |
| `sensor.nissan_leaf_ac_power` | W | Climate system power |
| `sensor.nissan_leaf_ac_on` | — | Climate on/off |
| `sensor.nissan_leaf_estimated_ac_power` | W | Estimated climate draw |
| `sensor.nissan_leaf_estimated_ptc_power` | W | Estimated PTC heater draw |
| `sensor.nissan_leaf_aux_power` | W | Auxiliary equipment power |
| `sensor.nissan_leaf_obc_out_power` | W | On-board charger output |
| `sensor.nissan_leaf_eco_mode` | — | ECO mode active |
| `sensor.nissan_leaf_rear_heater` | — | Rear window heater active |
| `sensor.nissan_leaf_power_switch` | — | Power switch status |
| `sensor.nissan_leaf_tp_fr` | kPa | Tyre pressure — front right |
| `sensor.nissan_leaf_tp_fl` | kPa | Tyre pressure — front left |
| `sensor.nissan_leaf_tp_rr` | kPa | Tyre pressure — rear right |
| `sensor.nissan_leaf_tp_rl` | kPa | Tyre pressure — rear left |

### ZE1 only

| Entity | Description |
|---|---|
| `sensor.nissan_leaf_e_pedal_mode` | e-Pedal mode active |

---

## Notes on ZE0/AZE0 battery data accuracy

The battery decoder byte offsets for ZE0/AZE0 (`state_of_charge`,
`hv_battery_health`, `hv_battery_Ah`) are based on community research and
testing on a 2016 Nissan Leaf.  They have not been exhaustively verified across
all ZE0 and AZE0 vehicles.  If you notice incorrect battery figures, please
[open an issue](https://github.com/Jopand/ha_nissan_leaf_obd_ble/issues) with
your raw LBC data.

---

## Configuration options

After setup, click **Configure** on the integration card to adjust:

| Option | Default | Description |
|---|---|---|
| Battery size | 30 kWh / 79.48 Ah | Nominal capacity used to calculate State of Health |
| Fast poll interval | 10 s | Polling rate when the car is on and in range |
| Slow poll interval | 300 s | Polling rate when in range but car is off |
| Extra-slow poll interval | 3600 s | Polling rate when out of BLE range |
| BLE service UUID | `0000ffe0-…` | GATT service UUID for the adapter |
| BLE read characteristic UUID | `0000ffe1-…` | Read characteristic UUID |
| BLE write characteristic UUID | `0000ffe1-…` | Write characteristic UUID |

---

## Data persistence

Sensor values are saved to HA's `.storage/` directory after each successful
poll.  After a Home Assistant restart, all sensors immediately display their
last known values — no need to drive the car home first.

---

## Troubleshooting

**No adapters appear in the dropdown**
: Ensure the OBD adapter is plugged in, the ignition is on, and the adapter
is within Bluetooth range of your HA host or a Bluetooth proxy.  Check
*Settings → Devices & Services → Bluetooth* to verify HA can see the adapter.
Manual discovery recognizes the `OBDBLE` and `IOS-Vlink` name prefixes without
regard to letter case.

**Sensors stay at last known value indefinitely**
: This is the persistence feature working as designed.  Values update the
next time the car is in range and the ignition is on.

**Incorrect battery / SoC values on a ZE0 or AZE0**
: Ensure you selected the correct generation during setup.  If you used
*Auto*, re-add the integration and select *ZE0* or *AZE0* explicitly.

**Enable debug logging**
```yaml
# configuration.yaml
logger:
  default: warning
  logs:
    custom_components.ha_nissan_leaf_obd_ble: debug
```

---

## Credits

- [hucknz/ha_nissan_leaf_obd_ble](https://github.com/hucknz/ha_nissan_leaf_obd_ble) — parent integration fork
- [pbutterworth/nissan-leaf-obd-ble](https://github.com/pbutterworth/nissan-leaf-obd-ble) — original integration
- [pbutterworth/py-nissan-leaf-obd-ble](https://github.com/pbutterworth/py-nissan-leaf-obd-ble) — upstream Python library
- [hucknz/py-nissan-leaf-obd-ble](https://github.com/hucknz/py-nissan-leaf-obd-ble) — forked library with ZE0 support and generation profiles
- [HA Community thread](https://community.home-assistant.io/t/custom-component-nissan-leaf-via-lelink-2-elm327-ble/561961)

## License

GPL-2.0-or-later (inherited from python-OBD lineage).
