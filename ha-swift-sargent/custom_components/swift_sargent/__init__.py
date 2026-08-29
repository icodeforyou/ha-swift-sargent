"""Swift Command / Sargent BLE integration for Home Assistant."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    SERVICE_SEND_COMMAND,
    SERVICE_SEND_RAW,
    SERVICE_START_PAIRING,
)
from .coordinator import SargentCoordinator
from .protocol import FRAME_LEN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type SargentConfigEntry = ConfigEntry[SargentCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SargentConfigEntry) -> bool:
    """Set up one vehicle."""
    coordinator = SargentCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SargentConfigEntry) -> bool:
    """Tear down one vehicle."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: SargentConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _coordinator_for(hass: HomeAssistant, entry_id: str | None) -> SargentCoordinator:
    entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
    for candidate in entries:
        if hasattr(candidate, "runtime_data") and candidate.runtime_data:
            return candidate.runtime_data
    raise HomeAssistantError("No configured Swift Command vehicle found")


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SEND_RAW):
        return

    async def _send_raw(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data.get("entry_id"))
        try:
            frame = bytes.fromhex(call.data["frame"].replace(" ", ""))
        except ValueError as err:
            raise HomeAssistantError(f"Not valid hex: {err}") from err
        if len(frame) != FRAME_LEN:
            raise HomeAssistantError(f"Frame must be exactly {FRAME_LEN} bytes")
        if not await coordinator.async_send_raw(frame):
            _LOGGER.warning("Raw frame sent but not acknowledged")

    async def _send_command(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data.get("entry_id"))
        await coordinator.async_send_command(
            int(call.data["command"]), int(call.data.get("value", 0))
        )

    async def _start_pairing(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data.get("entry_id"))
        await coordinator.async_start_pairing()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_RAW,
        _send_raw,
        schema=vol.Schema(
            {vol.Required("frame"): cv.string, vol.Optional("entry_id"): cv.string}
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        _send_command,
        schema=vol.Schema(
            {
                vol.Required("command"): vol.All(int, vol.Range(min=0, max=255)),
                vol.Optional("value", default=0): vol.All(int, vol.Range(min=0, max=255)),
                vol.Optional("entry_id"): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_PAIRING,
        _start_pairing,
        schema=vol.Schema({vol.Optional("entry_id"): cv.string}),
    )


class SargentEntity(CoordinatorEntity[SargentCoordinator]):
    """Base entity bound to one vehicle."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SargentCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={("bluetooth", coordinator.address)},
            manufacturer="Sargent Electrical Services",
            model="Swift Command (EC600 / EC800)",
            name="Swift Command",
        )
