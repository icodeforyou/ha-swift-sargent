"""Telemetry sensors from the Sargent PSU."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SargentConfigEntry, SargentEntity
from .coordinator import SargentCoordinator
from .protocol import CAN_LEVELS, CAN_POWER, CanState, decode_temperature


@dataclass(frozen=True, kw_only=True)
class SargentSensorDescription(SensorEntityDescription):
    """A sensor derived from one or more CAN data bytes."""

    can_id: int
    value_fn: Callable[[CanState], float | int | None]


def _tenths(can_id: int, index: int) -> Callable[[CanState], float | None]:
    def _value(state: CanState) -> float | None:
        raw = state.byte(can_id, index)
        return round(raw / 10, 1) if raw else None

    return _value


def _plain(can_id: int, index: int) -> Callable[[CanState], int]:
    return lambda state: state.byte(can_id, index)


SENSORS: tuple[SargentSensorDescription, ...] = (
    SargentSensorDescription(
        key="leisure_battery_voltage",
        name="Leisure battery voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        can_id=CAN_POWER,
        value_fn=_tenths(CAN_POWER, 1),
    ),
    SargentSensorDescription(
        key="vehicle_battery_voltage",
        name="Vehicle battery voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        can_id=CAN_POWER,
        value_fn=_tenths(CAN_POWER, 0),
    ),
    SargentSensorDescription(
        key="battery_current",
        name="Battery current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        can_id=CAN_POWER,
        value_fn=_tenths(CAN_POWER, 2),
    ),
    SargentSensorDescription(
        key="solar_current",
        name="Solar current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        can_id=CAN_POWER,
        value_fn=_tenths(CAN_POWER, 4),
    ),
    SargentSensorDescription(
        key="mains_current",
        name="Mains current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        can_id=CAN_POWER,
        value_fn=_tenths(CAN_POWER, 5),
    ),
    SargentSensorDescription(
        key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        can_id=CAN_POWER,
        value_fn=_plain(CAN_POWER, 6),
    ),
    SargentSensorDescription(
        key="inside_temperature",
        name="Inside temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        can_id=CAN_LEVELS,
        value_fn=lambda s: decode_temperature(
            s.byte(CAN_LEVELS, 4), s.byte(CAN_LEVELS, 5)
        ),
    ),
    SargentSensorDescription(
        key="outside_temperature",
        name="Outside temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        can_id=CAN_LEVELS,
        value_fn=lambda s: decode_temperature(
            s.byte(CAN_LEVELS, 2), s.byte(CAN_LEVELS, 3)
        ),
    ),
    SargentSensorDescription(
        key="fresh_water_level",
        name="Fresh water level",
        icon="mdi:water",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        can_id=CAN_LEVELS,
        value_fn=_plain(CAN_LEVELS, 0),
    ),
    SargentSensorDescription(
        key="waste_water_level",
        name="Waste water level",
        icon="mdi:water-off",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        can_id=CAN_LEVELS,
        value_fn=_plain(CAN_LEVELS, 1),
    ),
    SargentSensorDescription(
        key="ac_limit",
        name="AC limit setting",
        icon="mdi:transmission-tower",
        state_class=SensorStateClass.MEASUREMENT,
        can_id=CAN_LEVELS,
        value_fn=_plain(CAN_LEVELS, 7),
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SargentConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SargentSensor(coordinator, desc) for desc in SENSORS)


class SargentSensor(SargentEntity, SensorEntity):
    """One telemetry value."""

    entity_description: SargentSensorDescription

    def __init__(
        self, coordinator: SargentCoordinator, description: SargentSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.state.has(
            self.entity_description.can_id
        )

    @property
    def native_value(self) -> float | int | None:
        return self.entity_description.value_fn(self.coordinator.state)
