"""Dimmable lighting channels on the Sargent PSU."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
    LightEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SargentConfigEntry, SargentEntity
from .const import PSU_OLD
from .coordinator import SargentCoordinator
from .protocol import (
    CAN_LIGHTING,
    CMD_DIMMER1_LEVEL,
    CMD_DIMMER1_POWER,
    CMD_DIMMER2_LEVEL,
    CMD_DIMMER2_POWER,
    CanState,
)


@dataclass(frozen=True, kw_only=True)
class SargentLightDescription(LightEntityDescription):
    """Maps a dimmer onto its status byte, level byte and commands."""

    status_byte: int
    level_byte: int
    power_command: int
    level_command: int


LIGHTS: tuple[SargentLightDescription, ...] = (
    SargentLightDescription(
        key="dimmer_1",
        name="Dimmer 1",
        icon="mdi:lightbulb-on-50",
        status_byte=0,
        level_byte=2,
        power_command=CMD_DIMMER1_POWER,
        level_command=CMD_DIMMER1_LEVEL,
    ),
    SargentLightDescription(
        key="dimmer_2",
        name="Dimmer 2",
        icon="mdi:lightbulb-on-50",
        status_byte=1,
        level_byte=3,
        power_command=CMD_DIMMER2_POWER,
        level_command=CMD_DIMMER2_LEVEL,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SargentConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SargentDimmer(coordinator, desc) for desc in LIGHTS)


class SargentDimmer(SargentEntity, LightEntity):
    """A dimmer channel, 0-100 on the bus, 0-255 in Home Assistant."""

    entity_description: SargentLightDescription
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(
        self, coordinator: SargentCoordinator, description: SargentLightDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        state: CanState = self.coordinator.state
        return super().available and state.has(CAN_LIGHTING)

    @property
    def is_on(self) -> bool:
        state: CanState = self.coordinator.state
        return bool(state.byte(CAN_LIGHTING, self.entity_description.status_byte))

    @property
    def brightness(self) -> int | None:
        state: CanState = self.coordinator.state
        level = state.byte(CAN_LIGHTING, self.entity_description.level_byte)
        return min(255, round(level * 255 / 100))

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness is not None and self.coordinator.psu_generation != PSU_OLD:
            level = max(1, min(100, round(brightness * 100 / 255)))
            await self.coordinator.async_send_command(
                self.entity_description.level_command, level
            )
        if not self.is_on:
            await self.coordinator.async_send_command(
                self.entity_description.power_command, 1
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on or self.coordinator.psu_generation != PSU_OLD:
            await self.coordinator.async_send_command(
                self.entity_description.power_command, 0
            )
