# Swift Command (Sargent BLE) for Home Assistant

Local control of a Swift caravan or motorhome fitted with a Sargent EC600/EC800
power control system, over Bluetooth LE. No cloud, no Swift Command account.

Works through an ESPHome Bluetooth proxy, so Home Assistant can sit at home
while the ESP32 lives in the vehicle.

## Status

The protocol below was recovered from the official Swift Command 2019 Android
app and verified against real notification frames from a 2018 Swift Toscana.
The read path is confirmed byte for byte. **The write path is reconstructed from
the app's code and has not yet been confirmed against a vehicle.** Treat the
first switch press as an experiment, not a certainty.

## Install

1. HACS → three dots → Custom repositories → add this repo as an *Integration*.
2. Install, restart Home Assistant.
3. Settings → Devices & services → Add integration → **Swift Command**.
   The device should be discovered automatically as `SWIFT_BLE`; otherwise
   enter the MAC address by hand.

Requirements: a Bluetooth adapter or an ESPHome device with
`bluetooth_proxy: active: true` within range of the vehicle, and the Sargent
control panel switched on. The BLE module only answers while the system is
awake.

If the module refuses writes, pair it first: press PAIR on the control panel,
or call `swift_sargent.start_pairing`.

## Settings

**PSU generation** decides how commands are framed. The app picks by PSU serial
number: serial 45 and above uses CAN id 8 with an explicit on/off value, older
units use CAN id 11 with toggle semantics. Start with *Newer*; if nothing
happens, switch to *Older* in the integration options.

**Vehicle type** only affects the tank fill command (12 on motorhomes, 7 on
caravans).

## Entities

| Entity | Source |
|---|---|
| Interior lights, awning light, entry light, water pump, system power, tank fill | switches |
| Dimmer 1, Dimmer 2 (with brightness) | lights |
| Leisure/vehicle battery voltage, battery/solar/mains current, humidity, inside/outside temperature, fresh/waste water level | sensors |
| Mains connected, engine running, battery charging, solar active | binary sensors |

## Services

- `swift_sargent.send_command` — send any PsuCommands value with an argument.
- `swift_sargent.send_raw` — send an arbitrary 20 byte frame, for exploring the
  CAN ids this integration does not model yet (90, 91, 133–146, 184, 216 are
  readable; 144, 173–178, 180–182, 185, 186 are writable and cover heating,
  fridge and panel settings).
- `swift_sargent.start_pairing` — put the control panel into pairing mode.

## The protocol

Transport is a Nordic UART Service look-alike:

```
service 6e400001-b5a3-f393-e0a9-e50e24dcca9e
write   6e400002-...   Write Request
notify  6e400003-...
```

Every message is exactly 20 bytes:

```
[0]      2 = READ, 3 = WRITE, 4 = report from the vehicle
[1]      0
[2]      CAN id low
[3]      CAN id high
[4..11]  eight CAN data bytes
[12..19] padding
```

The app zero-fills the padding. The PSU does not, which is why real
notifications end in the ASCII `MNOPQRST` — the tail of an uninitialised
`ABCDEFGHIJKLMNOPQRST` transmit buffer. It carries no meaning. A frame that is
entirely `ABCDEFGHIJKLMNOPQRST` is an idle buffer flush.

A write is acknowledged by a frame with `0x43` at byte 2 and `0x45` at byte 4.

### Read

```
02 00 <id lo> <id hi> 00 x16
```

Reading has no side effects. `0200320000...` polls CAN 50.

### Write, newer PSU

```
03 00 08 00 <command> <value> 00 x14
```

Interior lights on: `0300080005010000000000000000000000000000`

### Write, older PSU

```
03 00 0B 00 <command> <CAN131.6> <dim1> <dim2> <CAN131.7> <CAN52.0> <CAN52.1> 01 00 x8
```

The command toggles rather than setting a state, and the trailing bytes must
carry freshly polled values.

### Commands

| Value | Meaning |
|---|---|
| 2 | battery select |
| 3 | water pump |
| 4 | system power |
| 5 | interior lights |
| 6 | awning light |
| 7 | tank fill / tank heaters (caravan) |
| 8 | entry light |
| 9 / 10 / 11 | dimmer 1 / 2 / both power |
| 12 / 13 / 14 | motorhome tank fill / fresh dump / waste dump |
| 50 / 51 | dimmer 1 / 2 level, 0-100 |
| 100 | Bluetooth pairing |
| 101 | save settings |
| 107 | send bulk data |

### Data bytes

**CAN 50 (0x32)** — 0 pump, 1 battery select, 2 **interior lights**,
3 awning light, 4 tank fill, 5 engine running, 6 mains connected, 7 system power.

**CAN 51 (0x33)** — 0 dimmer 1 on, 1 dimmer 2 on, 2 dimmer 1 level,
3 dimmer 2 level, 6 solar state, 7 solar on.

**CAN 131 (0x83)** — 0 fresh water %, 1 waste water %, 2-3 outside temperature,
4-5 inside temperature, 7 AC limit. Temperatures are uint16 little endian in
0.1 K: `(raw - 2730) / 10` gives °C.

**CAN 132 (0x84)** — 0 vehicle battery (V×10), 1 leisure battery (V×10),
2 battery current, 3 charge direction, 4 solar current, 5 mains current,
6 humidity %, 7 entry light.

## Credits

Reverse engineered from `com.SwiftCommand2019Xamarin`, assembly
`SwiftCommand2019.dll`, classes `BluetoothFunctions`, `PsuCommands`,
`CanBusIdsRead` / `CanBusIdsWrite` and `LightingPage`. Decompilation for
interoperability purposes, EU Directive 2009/24/EC article 6.

Not affiliated with Swift Group or Sargent Electrical Services.
