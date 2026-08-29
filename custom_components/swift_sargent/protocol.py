"""Sargent / Swift Command CAN-over-BLE protocol.

Derived by reverse engineering the official 'Swift Command 2019' Android app
(package com.SwiftCommand2019Xamarin, assembly SwiftCommand2019.dll), classes
SwiftCommand2019.Bluetooth.BluetoothFunctions, Models.PsuCommands and
Models.CanBusIdsRead/CanBusIdsWrite.

Transport is a Nordic UART Service look-alike:
    service 6e400001-b5a3-f393-e0a9-e50e24dcca9e
    write   6e400002-...  (Write Request)
    notify  6e400003-...

Every message is exactly 20 bytes:

    [0]      message kind: 2 = READ, 3 = WRITE, 4 = report from the vehicle
    [1]      always 0
    [2]      CAN id, low byte
    [3]      CAN id, high byte
    [4..11]  the eight CAN data bytes
    [12..19] padding (the app sends zeros; the PSU leaves stale buffer
             contents here, which is why real vehicles emit the trailing
             ASCII "MNOPQRST")
"""

from __future__ import annotations

from typing import Final

SERVICE_UUID: Final = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
WRITE_UUID: Final = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NOTIFY_UUID: Final = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

FRAME_LEN: Final = 20
DATA_OFFSET: Final = 4

KIND_READ: Final = 2
KIND_WRITE: Final = 3
KIND_REPORT: Final = 4

# A write is acknowledged with a frame carrying 0x43 ('C') at byte 2 and
# 0x45 ('E') at byte 4.
ACK_BYTE2: Final = 0x43
ACK_BYTE4: Final = 0x45

# CAN ids the PSU will answer a READ for.
CAN_STATUS: Final = 50  # 0x32 switch states
CAN_LIGHTING: Final = 51  # 0x33 dimmers + solar
CAN_AUX: Final = 52  # 0x34 aux / tank heaters
CAN_DUMP: Final = 53  # 0x35 fresh / waste dump
CAN_LEVELS: Final = 131  # 0x83 water levels + temperatures
CAN_POWER: Final = 132  # 0x84 battery, current, humidity, entry light

READABLE_IDS: Final = (
    50, 51, 52, 53, 90, 91,
    131, 132, 133, 134, 135, 136, 137, 138,
    140, 141, 142, 143, 145, 146, 184, 216,
)

# CAN ids the PSU accepts a WRITE for.
WRITABLE_IDS: Final = (8, 11, 144, 173, 174, 175, 176, 177, 178, 180, 181, 182, 185, 186)

CAN_WRITE_NEW: Final = 8  # newer PSU firmware, carries an explicit value
CAN_WRITE_OLD: Final = 11  # older PSU firmware, toggle semantics

# PsuCommands enum values used as data byte 0 of a write.
CMD_BATTERY_SELECT: Final = 2
CMD_PUMP: Final = 3
CMD_POWER: Final = 4
CMD_LIGHTS: Final = 5
CMD_AWNING_LIGHT: Final = 6
CMD_TANK_FILL_HEATERS: Final = 7
CMD_ENTRY_LIGHT: Final = 8
CMD_DIMMER1_POWER: Final = 9
CMD_DIMMER2_POWER: Final = 10
CMD_DIMMER_BOTH_POWER: Final = 11
CMD_MH_TANK_FILL: Final = 12
CMD_MH_FRESH_DUMP: Final = 13
CMD_MH_WASTE_DUMP: Final = 14
CMD_TANK_HEATERS2: Final = 15
CMD_DIMMER1_LEVEL: Final = 50
CMD_DIMMER2_LEVEL: Final = 51
CMD_BT_PAIRING: Final = 100
CMD_SAVE_SETTINGS: Final = 101
CMD_SEND_BULK_DATA: Final = 107

# Commands that always carry value 1 regardless of the requested state.
_FORCE_VALUE_ONE: Final = frozenset({108, 109, 110})


def build_read(can_id: int) -> bytes:
    """Build a READ request for one CAN id. Has no side effects on the vehicle."""
    frame = bytearray(FRAME_LEN)
    frame[0] = KIND_READ
    frame[2] = can_id & 0xFF
    frame[3] = (can_id >> 8) & 0xFF
    return bytes(frame)


def build_write_new(command: int, value: int) -> bytes:
    """Build a WRITE to CAN id 8 (newer PSU firmware).

    Mirrors BluetoothFunctions.WriteCanId8: byte 4 is the command, byte 5 the
    value. Bytes 6-8 are cleared and bytes 9-11 come from the app's shadow copy
    of CAN id 8, which is never populated from vehicle data and stays zero.
    """
    frame = bytearray(FRAME_LEN)
    frame[0] = KIND_WRITE
    frame[2] = CAN_WRITE_NEW
    frame[4] = command & 0xFF
    frame[5] = 1 if command in _FORCE_VALUE_ONE else (value & 0xFF)
    return bytes(frame)


def build_write_old(command: int, shadow: "CanState") -> bytes:
    """Build a WRITE to CAN id 11 (older PSU firmware).

    Mirrors BluetoothFunctions.WriteCanId11 combined with
    LightingPage.UpdateCanId11. The command in byte 4 acts as a toggle; the
    remaining bytes carry the current dimmer levels and a few echoed status
    bytes, so the caller must pass a freshly polled state.
    """
    frame = bytearray(FRAME_LEN)
    frame[0] = KIND_WRITE
    frame[2] = CAN_WRITE_OLD
    frame[4] = command & 0xFF
    frame[5] = shadow.byte(CAN_LEVELS, 6)
    frame[6] = shadow.byte(CAN_LIGHTING, 2)  # dimmer 1 level
    frame[7] = shadow.byte(CAN_LIGHTING, 3)  # dimmer 2 level
    frame[8] = shadow.byte(CAN_LEVELS, 7)  # AC limit
    frame[9] = shadow.byte(CAN_AUX, 0)
    frame[10] = shadow.byte(CAN_AUX, 1)
    frame[11] = 1
    return bytes(frame)


def is_ack(frame: bytes) -> bool:
    """True if the frame is a write acknowledgement."""
    return len(frame) >= 5 and frame[2] == ACK_BYTE2 and frame[4] == ACK_BYTE4


def parse_report(frame: bytes) -> tuple[int, bytes] | None:
    """Return (can_id, eight data bytes) for a vehicle report, else None."""
    if len(frame) < FRAME_LEN or frame[0] != KIND_REPORT:
        return None
    can_id = frame[2] | (frame[3] << 8)
    return can_id, bytes(frame[DATA_OFFSET : DATA_OFFSET + 8])


def decode_temperature(low: int, high: int) -> float | None:
    """Decode a Sargent temperature pair: uint16 little endian in 0.1 K."""
    raw = low | (high << 8)
    if raw == 0:
        return None
    return round((raw - 2730) / 10, 1)


class CanState:
    """The most recent data bytes seen for each CAN id."""

    def __init__(self) -> None:
        self._frames: dict[int, bytes] = {}

    def update(self, can_id: int, data: bytes) -> None:
        self._frames[can_id] = data

    def frame(self, can_id: int) -> bytes | None:
        return self._frames.get(can_id)

    def byte(self, can_id: int, index: int) -> int:
        data = self._frames.get(can_id)
        if data is None or index >= len(data):
            return 0
        return data[index]

    def has(self, can_id: int) -> bool:
        return can_id in self._frames

    @property
    def seen_ids(self) -> set[int]:
        return set(self._frames)
