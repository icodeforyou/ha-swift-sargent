"""Binary sensors from the Sargent PSU."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SargentConfigEntry, SargentEntity
from .coordinator import SargentCoordinator
from .protocol import CAN_LIGHTING, CAN_POWER, CAN_STATUS


@dataclass(frozen=True, kw_only=True)
class SargentBinaryDescription(BinarySensorEntityDescription):
    """A binary sensor derived from one CAN data byte."""

    can_id: int
    byte_index: int


BINARY_SENSORS: tuple[SargentBinaryDescription, ...] = (
    SargentBinaryDescription(
        key="mains_connected",
        name="Mains connected",
        device_class=BinarySensorDeviceClass.PLUG,
        can_id=CAN_STATUS,
        byte_index=6,
    ),
    SargentBinaryDescription(
        key="engine_running",
        name="Engine running",
        icon="mdi:engine",
        can_id=CAN_STATUS,
        byte_index=5,
    ),
    SargentBinaryDescription(
        key="battery_charging",
        name="Battery charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        can_id=CAN_POWER,
        byte_index=3,
    ),
    SargentBinaryDescription(
        key="solar_active",
        name="Solar active",
        icon="mdi:solar-power",
        can_id=CAN_LIGHTING,
        byte_index=7,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SargentConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SargentBinarySensor(coordinator, desc) for desc in BINARY_SENSORS)


class SargentBinarySensor(SargentEntity, BinarySensorEntity):
    """One boolean status byte."""

    entity_description: SargentBinaryDescription

    def __init__(
        self, coordinator: SargentCoordinator, description: SargentBinaryDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.state.has(
            self.entity_description.can_id
        )

    @property
    def is_on(self) -> bool:
        return bool(
            self.coordinator.state.byte(
                self.entity_description.can_id, self.entity_description.byte_index
            )
        )
