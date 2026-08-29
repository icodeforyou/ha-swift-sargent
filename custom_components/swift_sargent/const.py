"""Constants for the Swift Command / Sargent BLE integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "swift_sargent"

CONF_ADDRESS: Final = "address"
CONF_PSU_GENERATION: Final = "psu_generation"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_VEHICLE_TYPE: Final = "vehicle_type"

PSU_NEW: Final = "can8"
PSU_OLD: Final = "can11"

VEHICLE_MOTORHOME: Final = "motorhome"
VEHICLE_CARAVAN: Final = "caravan"

DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_PSU_GENERATION: Final = PSU_NEW
DEFAULT_VEHICLE_TYPE: Final = VEHICLE_MOTORHOME

LOCAL_NAME: Final = "SWIFT_BLE"

# How long to wait for the pairing exchange; the panel may need PAIR pressed.
PAIR_TIMEOUT: Final = 15.0
# How long to wait for a write acknowledgement before giving up.
ACK_TIMEOUT: Final = 4.0
# How long to wait for the reports triggered by a poll cycle.
READ_TIMEOUT: Final = 3.0
# Delay between consecutive frames so the PSU keeps up.
INTER_FRAME_DELAY: Final = 0.15

SERVICE_SEND_RAW: Final = "send_raw"
SERVICE_SEND_COMMAND: Final = "send_command"
SERVICE_START_PAIRING: Final = "start_pairing"
