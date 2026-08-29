"""Connection handling and polling for the Sargent BLE bridge."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ACK_TIMEOUT,
    CONF_PSU_GENERATION,
    CONF_SCAN_INTERVAL,
    CONF_VEHICLE_TYPE,
    DEFAULT_PSU_GENERATION,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VEHICLE_TYPE,
    DOMAIN,
    INTER_FRAME_DELAY,
    PAIR_TIMEOUT,
    PSU_OLD,
    READ_TIMEOUT,
    VEHICLE_CARAVAN,
)
from .protocol import (
    CAN_AUX,
    CAN_DUMP,
    CAN_LEVELS,
    CAN_LIGHTING,
    CAN_POWER,
    CAN_STATUS,
    CMD_MH_TANK_FILL,
    CMD_TANK_FILL_HEATERS,
    NOTIFY_UUID,
    WRITE_UUID,
    CanState,
    build_read,
    build_write_new,
    build_write_old,
    is_ack,
    parse_report,
)

_LOGGER = logging.getLogger(__name__)

POLL_IDS = (CAN_STATUS, CAN_LIGHTING, CAN_AUX, CAN_DUMP, CAN_LEVELS, CAN_POWER)


class SargentCoordinator(DataUpdateCoordinator[CanState]):
    """Keeps one BLE connection open and polls the PSU over it."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.address: str = entry.data["address"]
        self.psu_generation: str = entry.options.get(
            CONF_PSU_GENERATION, entry.data.get(CONF_PSU_GENERATION, DEFAULT_PSU_GENERATION)
        )
        self.vehicle_type: str = entry.options.get(
            CONF_VEHICLE_TYPE, entry.data.get(CONF_VEHICLE_TYPE, DEFAULT_VEHICLE_TYPE)
        )
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

        self.state = CanState()
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._ack = asyncio.Event()
        self._pending_reads: set[int] = set()
        self._reads_done = asyncio.Event()
        self._notify_started = False

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.address}",
            update_interval=timedelta(seconds=interval),
        )

    # ------------------------------------------------------------------
    # connection
    # ------------------------------------------------------------------

    def _ble_device(self) -> BLEDevice:
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address.upper(), connectable=True
        )
        if device is None:
            raise UpdateFailed(
                f"{self.address} is not in range of any connectable adapter or proxy"
            )
        return device

    async def _ensure_connected(self) -> BleakClientWithServiceCache:
        if self._client is not None and self._client.is_connected:
            return self._client

        self._notify_started = False
        device = self._ble_device()
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                self.address,
                self._on_disconnect,
                use_services_cache=True,
                ble_device_callback=self._ble_device,
            )
        except (BleakError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Could not connect to {self.address}: {err}") from err

        self._client = client
        try:
            # The module demands an encrypted link before it accepts the CCCD
            # write (GATT status 5, insufficient authentication), so encrypt
            # up front: pair() reuses the stored bond when there is one and
            # runs the SMP exchange when there is not, in which case the
            # Sargent panel must be in pairing mode. Bounded, because an
            # unanswered pairing request otherwise hangs until the link dies.
            try:
                async with asyncio.timeout(PAIR_TIMEOUT):
                    await client.pair()
            except NotImplementedError:
                _LOGGER.debug("Backend cannot pair; subscribing anyway")
            await client.start_notify(NOTIFY_UUID, self._on_notify)
        except (BleakError, asyncio.TimeoutError) as err:
            await self._disconnect()
            raise UpdateFailed(
                "Could not pair and subscribe. Press PAIR on the Sargent "
                f"panel, then reload the integration: {err}"
            ) from err
        self._notify_started = True
        _LOGGER.debug("Connected to %s", self.address)
        return client

    def _on_disconnect(self, _client: BleakClientWithServiceCache) -> None:
        _LOGGER.debug("Disconnected from %s", self.address)
        self._client = None
        self._notify_started = False

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        self._notify_started = False
        if client is None:
            return
        try:
            await client.disconnect()
        except BleakError:
            pass

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self._disconnect()

    # ------------------------------------------------------------------
    # notifications
    # ------------------------------------------------------------------

    def _on_notify(self, _handle, payload: bytearray) -> None:
        frame = bytes(payload)
        if is_ack(frame):
            _LOGGER.debug("Write acknowledged: %s", frame.hex())
            self._ack.set()
            return
        parsed = parse_report(frame)
        if parsed is None:
            # Idle frames are the module's uninitialised transmit buffer
            # ("ABCDEFGHIJKLMNOPQRST"); nothing to do with them.
            _LOGGER.debug("Ignoring non-report frame: %s", frame.hex())
            return
        can_id, data = parsed
        old = self.state.frame(can_id)
        if old != data:
            _LOGGER.debug("CAN %d: %s -> %s", can_id, old.hex() if old else None, data.hex())
        self.state.update(can_id, data)
        self._pending_reads.discard(can_id)
        if not self._pending_reads:
            self._reads_done.set()
        self.hass.loop.call_soon_threadsafe(self._publish)

    def _publish(self) -> None:
        self.async_set_updated_data(self.state)

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> CanState:
        async with self._lock:
            client = await self._ensure_connected()
            self._pending_reads = set(POLL_IDS)
            self._reads_done.clear()
            for can_id in POLL_IDS:
                try:
                    await client.write_gatt_char(
                        WRITE_UUID, build_read(can_id), response=True
                    )
                except BleakError as err:
                    await self._disconnect()
                    raise UpdateFailed(f"Read of CAN {can_id} failed: {err}") from err
                await asyncio.sleep(INTER_FRAME_DELAY)
            try:
                await asyncio.wait_for(self._reads_done.wait(), READ_TIMEOUT)
            except asyncio.TimeoutError:
                if not self.state.seen_ids:
                    raise UpdateFailed(
                        "No reports received; is the Sargent system switched on?"
                    )
                _LOGGER.debug("Poll incomplete, missing %s", sorted(self._pending_reads))
        return self.state

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------

    async def async_send_raw(self, frame: bytes) -> bool:
        """Send an arbitrary 20 byte frame and wait for the acknowledgement."""
        async with self._lock:
            client = await self._ensure_connected()
            self._ack.clear()
            try:
                await client.write_gatt_char(WRITE_UUID, frame, response=True)
            except BleakError as err:
                await self._disconnect()
                raise UpdateFailed(f"Write failed: {err}") from err
            try:
                await asyncio.wait_for(self._ack.wait(), ACK_TIMEOUT)
            except asyncio.TimeoutError:
                _LOGGER.warning("No acknowledgement for %s", frame.hex())
                return False
        return True

    async def async_send_command(self, command: int, value: int) -> bool:
        """Send a PSU command, using whichever framing this vehicle needs."""
        if self.psu_generation == PSU_OLD:
            # CAN 11 frames echo status bytes back at the PSU, and the app
            # always polls right before writing, so do the same.
            await self.async_refresh()
            frame = build_write_old(command, self.state)
        else:
            frame = build_write_new(command, value)
        acked = await self.async_send_raw(frame)
        await asyncio.sleep(INTER_FRAME_DELAY)
        await self.async_request_refresh()
        return acked

    def tank_fill_command(self) -> int:
        """Tank fill uses a different command on caravans than motorhomes."""
        if self.vehicle_type == VEHICLE_CARAVAN:
            return CMD_TANK_FILL_HEATERS
        return CMD_MH_TANK_FILL

    async def async_start_pairing(self) -> bool:
        """Ask the PSU to enter Bluetooth pairing mode."""
        from .protocol import CMD_BT_PAIRING

        return await self.async_send_command(CMD_BT_PAIRING, 1)
