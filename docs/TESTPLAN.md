# Vehicle test plan

The read path is verified against a real 2018 Swift Toscana. Everything below
tests the parts that are only reconstructed from the app's code: the write
path, and the CAN ids that should cover heating and the fridge.

Two ways to run the tests:

- **Standalone**, from a laptop with Bluetooth near the vehicle — no Home
  Assistant needed:

  ```
  pip install bleak
  python tools/probe.py
  ```

  The probe hexdumps every frame in both directions and never writes unless
  you ask it to.

- **Through Home Assistant**, with the integration installed. Enable debug
  logging first so every frame change is recorded:

  ```yaml
  logger:
    logs:
      custom_components.swift_sargent: debug
  ```

  Raw frames are sent with the `swift_sargent.send_raw` service, and
  *Download diagnostics* on the device page dumps every CAN frame seen.

## 1. Confirm the read path

Probe: `poll`. HA: just wait for a poll cycle and check the sensor entities.

Expected: reports for CAN 50, 51, 52, 53, 131, 132 and plausible values
(battery around 12–13 V, sane temperatures). This should work; it is the
verified half of the protocol.

## 2. Interior lights, newer PSU framing (CAN 8)

This is the first real write. Have the lights reachable so you can see them,
and note their current state first.

Probe: `lights-on`, then `lights-off`.
HA: toggle the *Interior lights* switch, or send raw:

| Action | Frame |
|---|---|
| lights on | `0300080005010000000000000000000000000000` |
| lights off | `0300080005000000000000000000000000000000` |

Watch for three things:

1. an ACK frame (byte 2 = `0x43`, byte 4 = `0x45`) — the module accepted the
   write;
2. the lights actually changing;
3. CAN 50 byte 2 flipping on the next poll (probe: `poll`).

ACK but no light suggests the framing is right but the command table is off.
No ACK at all suggests the module wants pairing first: press PAIR on the
control panel or call `swift_sargent.start_pairing`, then retry.

## 3. Interior lights, older PSU framing (CAN 11)

Only if step 2 did nothing. Probe: `lights-toggle` (it polls first — the
CAN 11 frame echoes freshly read status bytes and stale ones may be why a
write gets rejected). In HA: switch the integration options to *Older PSU*
and toggle the switch.

Each send toggles the lights rather than setting a state. If this is the
framing your PSU wants, leave the option on *Older* permanently.

## 4. Record the outcome

Whichever variant worked, note: PSU generation option, ACK seen or not, and
the CAN 50 state change. Update the README status section — the write path is
no longer unverified after this.

## 5. Map heating and fridge (CAN 173–182, read side first)

The app can write CAN ids 144, 173–178, 180–182, 185, 186 for heating, fridge
and panel settings, but their layout is unknown. Map the read side before
ever writing:

1. Probe: `sweep` — reads every known-readable id and snapshots it.
   (In HA, send the read frames below with `send_raw` and pull diagnostics
   before and after instead.)
2. Change **one** thing from the control panel: heating setpoint, heating
   on/off, fridge mode, ...
3. Probe: `diff` — shows exactly which id and byte changed.
4. Repeat for each setting. One change at a time, note everything.

Read frames for the ids not yet modelled:

| CAN id | READ frame |
|---|---|
| 90 (0x5A) | `02005a0000000000000000000000000000000000` |
| 91 (0x5B) | `02005b0000000000000000000000000000000000` |
| 133 (0x85) | `0200850000000000000000000000000000000000` |
| 134 (0x86) | `0200860000000000000000000000000000000000` |
| 135 (0x87) | `0200870000000000000000000000000000000000` |
| 136 (0x88) | `0200880000000000000000000000000000000000` |
| 137 (0x89) | `0200890000000000000000000000000000000000` |
| 138 (0x8A) | `02008a0000000000000000000000000000000000` |
| 140 (0x8C) | `02008c0000000000000000000000000000000000` |
| 141 (0x8D) | `02008d0000000000000000000000000000000000` |
| 142 (0x8E) | `02008e0000000000000000000000000000000000` |
| 143 (0x8F) | `02008f0000000000000000000000000000000000` |
| 145 (0x91) | `0200910000000000000000000000000000000000` |
| 146 (0x92) | `0200920000000000000000000000000000000000` |
| 184 (0xB8) | `0200b80000000000000000000000000000000000` |
| 216 (0xD8) | `0200d80000000000000000000000000000000000` |

Reading has no side effects; sweep as often as you like.

## 6. Write to heating/fridge ids — only after mapping

Once a setting's read-side id and byte are known, the safe experiment is to
write back **exactly what you just read**, changing a single byte to a value
the panel itself produces (e.g. setpoint one step higher). Frame layout:

```
03 00 <id lo> <id hi> <the eight data bytes> 00 x8
```

Do this with the heating cold and mains disconnected the first time. Avoid
writing values outside the range the panel generates, and stay away from ids
185/186 (panel settings) until everything else is understood.

## Notes for the log

- Vehicle: Swift Toscana 694, 2018 — PSU generation option that worked: ___
- ACK on first write: ___
- CAN id / byte map discovered for heating: ___
- CAN id / byte map discovered for fridge: ___
