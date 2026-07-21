# Phase 3 — Global Gamepad Input — Design

**Date:** 2026-07-21
**Target device:** ClockworkPi uConsole (Raspberry Pi CM4) with j1n6 QMK firmware
**Fork:** `git@github.com:btquan/BrickEmuPy-uConsole.git`
**Depends on:** Phase 2 (handheld GameScreen) — merged to `main`.
**Status:** Approved design, ready for implementation planning
**Priority:** Brick games first.

## 1. Overview

Let the uConsole's physical gamepad drive any game. In the firmware's **Game
Mode (Fn+G)**, the buttons and D-pad emit **Linux joystick events** on
`/dev/input/js0` (not keyboard keys). A background reader translates those
events into canonical **roles**, maps each role to a game button via an editable
global profile (`uconsole.json`) with optional per-`.brick` overrides, and feeds
them to the emulator through the existing button-press path. Keyboard input keeps
working unchanged alongside it.

## 2. Captured hardware mapping (measured on device, Game Mode on)

`/dev/input/js0`, Linux joystick API (`struct js_event { u32 time; s16 value;
u8 type; u8 number; }`, 8 bytes):

| Physical button | js0 event |
|---|---|
| A / B / X / Y | button 0 / 1 / 2 / 3 |
| Select / Start | button 4 / 5 |
| D-pad Left / Right | axis 0 = −32767 / +32767 (0 = released) |
| D-pad Up / Down | axis 1 = −32767 / +32767 (0 = released) |

D-pad is digital (full-scale ±32767). Buttons: value 1 = press, 0 = release.

## 3. Goals / Non-Goals

**Goals**
- Read `js0` and drive the active game with the D-pad + A/B/X/Y/Select/Start.
- Editable global profile (`uconsole.json`): js0 layout + role→button mapping.
- Per-`.brick` override of role→button.
- ControlsPanel shows the gamepad control for each game button.
- Keyboard `hot_keys` still work (no change to that path).
- Default profile encodes: **Start→btnStart, Select→btnMute, A→btnRotate**,
  D-pad L/R/Down → move, **Up separate (not rotate)**, B→btnRotate.

**Non-Goals (later / out of scope)**
- Analog sticks, multiple gamepads, L/R shoulder buttons (unmapped for now).
- In-app remap UI (edit `uconsole.json` instead).
- Making the emulator itself gamepad-aware (all mapping lives in the shell).

## 4. Roles

Canonical role strings, independent of any game's button names:
`DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT, BTN_A, BTN_B, BTN_X, BTN_Y,
BTN_SELECT, BTN_START`.

## 5. `uconsole.json` (shipped default, user-editable)

```json
{
  "buttons": {
    "0": "BTN_A", "1": "BTN_B", "2": "BTN_X", "3": "BTN_Y",
    "4": "BTN_SELECT", "5": "BTN_START"
  },
  "axes": {
    "0": {"negative": "DPAD_LEFT", "positive": "DPAD_RIGHT"},
    "1": {"negative": "DPAD_UP",   "positive": "DPAD_DOWN"}
  },
  "axis_threshold": 16000,
  "roles": {
    "DPAD_LEFT":  ["btnLeft"],
    "DPAD_RIGHT": ["btnRight"],
    "DPAD_DOWN":  ["btnDown"],
    "DPAD_UP":    ["btnUp"],
    "BTN_A":      ["btnRotate"],
    "BTN_B":      ["btnRotate"],
    "BTN_X":      [],
    "BTN_Y":      [],
    "BTN_START":  ["btnStart"],
    "BTN_SELECT": ["btnMute", "btnSelect"]
  }
}
```

Each role maps to an ordered list of **candidate** game-button names; resolution
picks the first candidate that exists in the game's `config["buttons"]`. Empty
list or no match → the role does nothing for that game (e.g. `DPAD_UP` on a brick
game that has no `btnUp`).

## 6. Role → game-button resolution (pure)

`resolve_role(role, config, profile) -> str | None`:
1. If the game's `config` has `"input_map"` and it contains `role`, return that
   button name (per-game override) — even if the button doesn't exist, so a
   game can deliberately point a role somewhere specific.
2. Else walk `profile["roles"][role]` candidates; return the first that is a key
   of `config["buttons"]`.
3. Else `None`.

Per-`.brick` override example (optional block in a `.brick`):
`"input_map": {"BTN_A": "btnRotate", "BTN_B": "btnOnOff"}`.

## 7. Components

### `handheld/js_events.py` — pure joystick decoding
- `parse_js_event(data8: bytes) -> (kind, number, value)` where kind is
  `"button"`/`"axis"`/`"init"` (init = the 0x80 startup flag, ignored by callers).
- `AxisTracker`: given `axis_threshold` and the axes config, converts axis
  value changes into role press/release transitions (crossing +threshold →
  positive role pressed; returning toward 0 → released; direction flips release
  the old role and press the new). Pure, deterministic, unit-tested.
- `button_role(number, profile)` / `axis_roles(number, profile)`: look up roles
  from the profile. Pure.

### `handheld/input_map.py` — pure resolution + profile load
- `load_profile(path) -> dict` (reads `uconsole.json`; returns a built-in
  default if the file is missing so the app still runs).
- `resolve_role(role, config, profile) -> str | None` (§6).
- `control_hints(config, profile) -> list[(button_name, [role,...])]` — inverse
  map for the ControlsPanel: for each game button, which roles resolve to it.

### `handheld/gamepad.py` — Qt/IO reader
- `GamepadReader(QThread)` with signals `rolePressed(str)`, `roleReleased(str)`.
- Opens `/dev/input/js0` non-blocking (`os.open` + `select` with a timeout) so
  `stop()` exits promptly. If the device is absent or unreadable (dev Mac, Game
  Mode off), it emits nothing and exits cleanly — keyboard input is unaffected.
- Uses `js_events` to decode; emits role transitions for buttons and axes.

### `uconsole.json`
- Shipped at repo root (or `handheld/uconsole.json`); `load_profile` looks there,
  overridable via an env var or a path constant.

## 8. Changes to existing files (small, additive)

- **`brick_widget.py`**: add `pressButton(name)` / `releaseButton(name)` public
  methods that send `CMD_BTN_PRESS` / `CMD_BTN_RELEASE`; refactor
  `keyPressEvent`/`keyReleaseEvent` to call them. Behaviour identical; now
  reusable by the gamepad path.
- **`handheld/game_screen.py`**: construct a `GamepadReader`, load the profile,
  connect `rolePressed`/`roleReleased` → resolve role → `brick.pressButton/
  releaseButton`; stop the reader in `close()`.
- **`handheld/controls_panel.py`**: render the gamepad legend from
  `control_hints` — for each game button, show its label and the physical
  control(s) via a role→symbol map
  (`DPAD_LEFT→"◄", DPAD_RIGHT→"►", DPAD_UP→"▲", DPAD_DOWN→"▼", BTN_A→"A",
  BTN_B→"B", BTN_X→"X", BTN_Y→"Y", BTN_START→"Start", BTN_SELECT→"Select"`).
  Buttons with no bound control are omitted or shown as unmapped.

## 9. Data flow

```
js0 8-byte event
  → js_events.parse → (kind, number, value)
  → button_role / AxisTracker → role transition (pressed/released)
  → GamepadReader emits rolePressed/roleReleased  [GUI thread via queued signal]
  → GameScreen: resolve_role(role, config, profile) → button name
  → BrickWidget.pressButton(name) → CMD_BTN_PRESS → emulator
```

## 10. Error handling / edge cases

- `js0` absent/unreadable → GamepadReader no-ops; app runs on keyboard only.
- Game Mode off → js0 yields no gamepad events (buttons act as keys); documented.
- Malformed/short read on js0 → skip; thread continues.
- Missing/invalid `uconsole.json` → built-in default profile.
- Role resolving to `None` → ignored (no press sent).
- Multiple roles → same button (e.g. A and B → btnRotate): reference-count
  presses so releasing one held button doesn't cancel another still held.

**Known limitation:** the keyboard path (`BrickWidget.keyPressEvent`) and the
gamepad path (`GameScreen._heldRoles`) are independent — the emulator's per-button
input is a boolean, not a counter. If a key and a gamepad role drove the *same*
game button at once, one path's release could turn the button off while the other
still holds it. This cannot happen on the uConsole because the QMK firmware makes
Game Mode (js0 events) and keyboard mode mutually exclusive, so the two paths are
never live simultaneously. A future refactor must not merge the two paths without
sharing the reference count.

## 11. Testing

- **Pure (run anywhere):** `parse_js_event` (button/axis/init framing);
  `AxisTracker` (threshold crossings, direction flips, center release);
  `resolve_role` (override > candidates > none); `control_hints` inverse map;
  `load_profile` (missing file → default).
- **Qt/IO:** `GamepadReader` fed a fake fd (an `os.pipe` with pre-written
  js_event frames) → asserts it emits the expected role signals and stops
  cleanly; absence path (bad path) emits nothing and exits.
- **On-device:** Game Mode on; play E-23 — D-pad moves, A/B rotate, Start =
  start, Select = mute, Up does nothing (no `btnUp`); ControlsPanel shows the
  gamepad legend; keyboard still works with Game Mode off.

## 12. Milestones (implementation-plan tasks)

1. `js_events.py` (parse + button/axis role lookup) + tests.
2. `AxisTracker` (in `js_events.py`) + tests.
3. `input_map.py` (`load_profile`, `resolve_role`, `control_hints`) + `uconsole.json` + tests.
4. `brick_widget.py`: `pressButton`/`releaseButton` + refactor key events + reference-count presses.
5. `gamepad.py`: `GamepadReader` QThread + fake-fd Qt/IO test.
6. `game_screen.py` wiring + `controls_panel.py` gamepad legend.
7. On-device acceptance (Game Mode gameplay + legend + keyboard fallback).

## 13. Risks

| Risk | Mitigation |
|---|---|
| Reference counting for shared buttons gets out of sync | Track a per-button held-role set in GameScreen; press on first, release on last |
| js0 blocking read stalls shutdown | `select` with timeout; `stop()` flag checked each loop |
| Game Mode must be on for gamepad | Documented; keyboard remains a full fallback |
| Other games use different button names | Candidate lists + per-`.brick` `input_map`; brick games covered by default |
