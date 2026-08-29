"""Switches for the Sargent PSU."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SargentConfigEntry, SargentEntity
from .const import PSU_OLD
from .coordinator import SargentCoordinator
from .protocol import (
    CAN_POWER,
    CAN_STATUS,
    CMD_AWNING_LIGHT,
    CMD_ENTRY_LIGHT,
    CMD_LIGHTS,
    CMD_POWER,
    CMD_PUMP,
    CanState,
)


@dataclass(frozen=True, kw_only=True)
class SargentSwitchDescription(SwitchEntityDescription):
    """Maps a switch onto a status byte and a PSU command."""

    can_id: int
    byte_index: int
    command: int | Callable[[SargentCoordinator], int]


SWITCHES: tuple[SargentSwitchDescription, ...] = (
    SargentSwitchDescription(
        key="interior_lights",
        name="Interior lights",
        icon="mdi:lightbulb-group",
        can_id=CAN_STATUS,
        byte_index=2,
        command=CMD_LIGHTS,
    ),
    SargentSwitchDescription(
        key="awning_light",
        name="Awning light",
        icon="mdi:awning-outline",
        can_id=CAN_STATUS,
        byte_index=3,
        command=CMD_AWNING_LIGHT,
    ),
    SargentSwitchDescription(
        key="entry_light",
        name="Entry light",
        icon="mdi:door-open",
        can_id=CAN_POWER,
        byte_index=7,
        command=CMD_ENTRY_LIGHT,
    ),
    SargentSwitchDescription(
        key="water_pump",
        name="Water pump",
        icon="mdi:water-pump",
        can_id=CAN_STATUS,
        byte_index=0,
        command=CMD_PUMP,
    ),
    SargentSwitchDescription(
        key="system_power",
        name="System power",
        icon="mdi:power",
        can_id=CAN_STATUS,
        byte_index=7,
        command=CMD_POWER,
    ),
    SargentSwitchDescription(
        key="tank_fill",
        name="Tank fill",
        icon="mdi:water-plus",
        can_id=CAN_STATUS,
        byte_index=4,
        command=lambda coordinator: coordinator.tank_fill_command(),
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SargentConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SargentSwitch(coordinator, desc) for desc in SWITCHES)


class SargentSwitch(SargentEntity, SwitchEntity):
    """One switched circuit on the PSU."""

    entity_description: SargentSwitchDescription

    def __init__(
        self, coordinator: SargentCoordinator, description: SargentSwitchDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        state: CanState = self.coordinator.state
        return super().available and state.has(self.entity_description.can_id)

    @property
    def is_on(self) -> bool:
        state: CanState = self.coordinator.state
        return bool(
            state.byte(self.entity_description.can_id, self.entity_description.byte_index)
        )

    def _command(self) -> int:
        command = self.entity_description.command
        if callable(command):
            return command(self.coordinator)
        return command

    async def async_turn_on(self, **kwargs: Any) -> None:
        # CAN 11 writes toggle; sending "on" while on would switch it off.
        if self.coordinator.psu_generation == PSU_OLD and self.is_on:
            return
        await self.coordinator.async_send_command(self._command(), 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.coordinator.psu_generation == PSU_OLD and not self.is_on:
            return
        await self.coordinator.async_send_command(self._command(), 0)
