"""Config flow for the Swift Command / Sargent BLE integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_ADDRESS,
    CONF_PSU_GENERATION,
    CONF_SCAN_INTERVAL,
    CONF_VEHICLE_TYPE,
    DEFAULT_PSU_GENERATION,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VEHICLE_TYPE,
    DOMAIN,
    LOCAL_NAME,
    PSU_NEW,
    PSU_OLD,
    VEHICLE_CARAVAN,
    VEHICLE_MOTORHOME,
)

_SETTINGS = {
    vol.Optional(CONF_PSU_GENERATION, default=DEFAULT_PSU_GENERATION): vol.In(
        {
            PSU_NEW: "Newer PSU - explicit on/off (CAN id 8)",
            PSU_OLD: "Older PSU - toggle (CAN id 11)",
        }
    ),
    vol.Optional(CONF_VEHICLE_TYPE, default=DEFAULT_VEHICLE_TYPE): vol.In(
        {VEHICLE_MOTORHOME: "Motorhome", VEHICLE_CARAVAN: "Caravan"}
    ),
    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
        int, vol.Range(min=10, max=600)
    ),
}


class SargentConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle adding a vehicle."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._name: str = LOCAL_NAME

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name or LOCAL_NAME
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_settings()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_settings()

        configured = self._async_current_ids()
        choices: dict[str, str] = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address in configured:
                continue
            if (info.name or "").upper().startswith(LOCAL_NAME):
                choices[info.address] = f"{info.name} ({info.address})"

        if not choices:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}),
                description_placeholders={"name": LOCAL_NAME},
                errors={"base": "no_devices_found"},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(choices)}),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._name,
                data={CONF_ADDRESS: self._address, **user_input},
            )
        return self.async_show_form(
            step_id="settings", data_schema=vol.Schema(_SETTINGS)
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return SargentOptionsFlow()


class SargentOptionsFlow(OptionsFlow):
    """Allow changing the PSU generation, vehicle type and poll interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_PSU_GENERATION,
                    default=current.get(CONF_PSU_GENERATION, DEFAULT_PSU_GENERATION),
                ): vol.In(
                    {
                        PSU_NEW: "Newer PSU - explicit on/off (CAN id 8)",
                        PSU_OLD: "Older PSU - toggle (CAN id 11)",
                    }
                ),
                vol.Optional(
                    CONF_VEHICLE_TYPE,
                    default=current.get(CONF_VEHICLE_TYPE, DEFAULT_VEHICLE_TYPE),
                ): vol.In({VEHICLE_MOTORHOME: "Motorhome", VEHICLE_CARAVAN: "Caravan"}),
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(int, vol.Range(min=10, max=600)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
