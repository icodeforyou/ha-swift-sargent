#!/usr/bin/env python3
"""Interactive probe for the Sargent BLE bridge.

Connects straight from this machine (no Home Assistant needed), subscribes to
notifications and hexdumps every frame with a decode. Nothing is written to
the vehicle unless you type a write command.

    pip install bleak
    python tools/probe.py                 # scan for SWIFT_BLE and connect
    python tools/probe.py AA:BB:CC:DD:EE:FF

Commands at the prompt:

    poll            read the six CAN ids the integration polls
    sweep           read every known readable CAN id and snapshot the result
    diff            sweep again and show only what changed since last snapshot
    read <id>       read one CAN id (decimal)
    lights-on       WRITE interior lights on, newer PSU framing (CAN 8)
    lights-off      WRITE interior lights off, newer PSU framing (CAN 8)
    lights-toggle   WRITE interior lights toggle, older PSU framing (CAN 11);
                    polls first so the echoed shadow bytes are fresh
    cmd <c> <v>     WRITE arbitrary command/value, newer PSU framing (CAN 8)
    raw <hex>       send an arbitrary 20 byte frame
    quit
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "custom_components/swift_sargent")
)
import protocol  # noqa: E402

LOCAL_NAME = "SWIFT_BLE"
POLL_IDS = (
    protocol.CAN_STATUS,
    protocol.CAN_LIGHTING,
    protocol.CAN_AUX,
    protocol.CAN_DUMP,
    protocol.CAN_LEVELS,
    protocol.CAN_POWER,
)
INTER_FRAME_DELAY = 0.15

KIND_NAMES = {2: "READ", 3: "WRITE", 4: "REPORT"}


class Probe:
    def __init__(self) -> None:
        self.state = protocol.CanState()
        self.snapshot: dict[int, bytes] = {}
        self.client: BleakClient | None = None

    # ------------------------------------------------------------------
    # incoming
    # ------------------------------------------------------------------

    def on_notify(self, _handle, payload: bytearray) -> None:
        frame = bytes(payload)
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"\r{stamp}  <-  {frame.hex(' ')}")
        if protocol.is_ack(frame):
            print(f"{'':14}ACK (write acknowledged)")
        elif frame == b"ABCDEFGHIJKLMNOPQRST":
            print(f"{'':14}idle buffer flush, ignore")
        else:
            parsed = protocol.parse_report(frame)
            if parsed:
                can_id, data = parsed
                old = self.state.frame(can_id)
                self.state.update(can_id, data)
                changed = ""
                if old is not None and old != data:
                    marks = "".join(
                        "^^ " if o != n else "   " for o, n in zip(old, data)
                    )
                    changed = f"\n{'':14}changed:      {marks}"
                kind = KIND_NAMES.get(frame[0], str(frame[0]))
                print(f"{'':14}{kind} CAN {can_id}: {data.hex(' ')}{changed}")
        print("> ", end="", flush=True)

    # ------------------------------------------------------------------
    # outgoing
    # ------------------------------------------------------------------

    async def send(self, frame: bytes, label: str) -> None:
        assert self.client is not None
        print(f"{'':14}->  {frame.hex(' ')}   ({label})")
        await self.client.write_gatt_char(protocol.WRITE_UUID, frame, response=True)
        await asyncio.sleep(INTER_FRAME_DELAY)

    async def read_ids(self, ids: tuple[int, ...] | list[int]) -> None:
        for can_id in ids:
            await self.send(protocol.build_read(can_id), f"read CAN {can_id}")
        await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------

    async def handle(self, line: str) -> bool:
        parts = line.split()
        if not parts:
            return True
        verb, args = parts[0].lower(), parts[1:]

        if verb in ("quit", "exit", "q"):
            return False

        if verb == "poll":
            await self.read_ids(POLL_IDS)
        elif verb == "sweep":
            await self.read_ids(protocol.READABLE_IDS)
            self.snapshot = {i: self.state.frame(i) for i in self.state.seen_ids}
            print(f"snapshot of {len(self.snapshot)} ids taken; "
                  "change something on the panel, then run: diff")
        elif verb == "diff":
            before = dict(self.snapshot)
            await self.read_ids(protocol.READABLE_IDS)
            self.snapshot = {i: self.state.frame(i) for i in self.state.seen_ids}
            changes = 0
            for can_id in sorted(self.snapshot):
                old, new = before.get(can_id), self.snapshot[can_id]
                if old != new:
                    changes += 1
                    print(f"CAN {can_id}: {old.hex(' ') if old else '(new)':>23}"
                          f"  ->  {new.hex(' ')}")
            if not changes:
                print("no changes")
        elif verb == "read" and args:
            await self.read_ids([int(args[0])])
        elif verb == "lights-on":
            await self.send(
                protocol.build_write_new(protocol.CMD_LIGHTS, 1), "lights on, CAN 8"
            )
        elif verb == "lights-off":
            await self.send(
                protocol.build_write_new(protocol.CMD_LIGHTS, 0), "lights off, CAN 8"
            )
        elif verb == "lights-toggle":
            # The CAN 11 frame echoes polled bytes, so refresh them first.
            await self.read_ids(POLL_IDS)
            await self.send(
                protocol.build_write_old(protocol.CMD_LIGHTS, self.state),
                "lights toggle, CAN 11",
            )
        elif verb == "cmd" and len(args) == 2:
            await self.send(
                protocol.build_write_new(int(args[0]), int(args[1])),
                f"command {args[0]} value {args[1]}, CAN 8",
            )
        elif verb == "raw" and args:
            frame = bytes.fromhex("".join(args))
            if len(frame) != protocol.FRAME_LEN:
                print(f"frame must be {protocol.FRAME_LEN} bytes, got {len(frame)}")
            else:
                await self.send(frame, "raw")
        else:
            print((__doc__ or "").partition("Commands at the prompt:")[2])
        return True


async def main() -> None:
    address = sys.argv[1] if len(sys.argv) > 1 else None
    if address is None:
        print(f"scanning for {LOCAL_NAME} ...")
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: (d.name or "").upper().startswith(LOCAL_NAME), timeout=15
        )
        if device is None:
            sys.exit(f"no {LOCAL_NAME} found; is the control panel on and in range?")
        address = device.address
        print(f"found {device.name} at {address}")

    probe = Probe()
    async with BleakClient(address) as client:
        probe.client = client
        await client.start_notify(protocol.NOTIFY_UUID, probe.on_notify)
        print("connected; type 'poll' to read status, 'quit' to leave")

        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, input, "> ")
            try:
                if not await probe.handle(line):
                    break
            except Exception as err:  # noqa: BLE001 - keep the prompt alive
                print(f"error: {err}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
