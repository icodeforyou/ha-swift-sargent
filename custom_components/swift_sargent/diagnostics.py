"""Diagnostics for the Swift Command / Sargent BLE integration.

Settings -> Devices & services -> Swift Command -> Download diagnostics
gives a JSON dump of every CAN frame seen, which is the raw material for
mapping the ids this integration does not model yet.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import SargentConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SargentConfigEntry
) -> dict[str, Any]:
    """Return the coordinator state for one vehicle."""
    coordinator = entry.runtime_data
    return {
        "psu_generation": coordinator.psu_generation,
        "vehicle_type": coordinator.vehicle_type,
        "last_update_success": coordinator.last_update_success,
        "can_frames": {
            str(can_id): coordinator.state.frame(can_id).hex(" ")
            for can_id in sorted(coordinator.state.seen_ids)
        },
    }
