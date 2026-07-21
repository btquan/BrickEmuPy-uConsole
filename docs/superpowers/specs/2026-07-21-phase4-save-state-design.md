# Phase 4 — Save-State (auto-persist) — Design

**Date:** 2026-07-21
**Target device:** ClockworkPi uConsole (Raspberry Pi CM4)
**Fork:** `git@github.com:btquan/BrickEmuPy-uConsole.git`
**Depends on:** Phase 1–3, 5 (merged to `main`).
**Status:** Design drafted while the uConsole was offline — **implementation +
on-device acceptance are pending device access.**
**User choice (from Phase-0 brainstorming):** auto-persist on exit (CPU + RAM +
EEPROM), auto-restore on open.

## 1. Overview

Persist a game's full machine state when the player leaves it (back-to-launcher
or quit) and restore it on next open, so continuously-running virtual pets
(Tamagotchi, Digimon) survive power-off. Arcade games get it too (harmless).

## 2. Investigation findings (grounded in the code)

- **HT24LC08 EEPROM** (`peripherals/HT24LC08.py`): loads from a per-game config
  `"path"` on init and writes `_mem` back in `__del__`. Only
  `Tamagotchi_v3_{us,eu}.brick` (SPLB32 core) use it, with
  `"path": "./assets/Tamagotchi_v3_us.eeprom"`. **`__del__` is unreliable** — it
  won't run on `terminate()`/`kill()` of the emulator subprocess (Phase-1
  teardown ladder), and may not flush on abrupt exit.
- **CPU state**: every core exposes `examine()` and `edit_state()`
  (`HT4BIT`/`HT943`, `E0C6200:424/494`, `SPLB32:417/494`, …). The UI already
  receives `examine()` at 30 Hz via `MSG_EXAMINE`. **Nothing persists it to disk
  on exit** — this is the real gap for E0C6200 pets (Tamagotchi P1/P2, Digimon),
  whose save data lives in CPU RAM.
- **Asymmetry (key risk):** `examine()` returns `RAM` as a **tuple**, but
  `edit_state()` expects `RAM` as an **index→value dict** (`for i, value in
  state["RAM"].items()`). A naive `examine()`→`edit_state()` round-trip will
  **not** restore RAM. Registers/flags do round-trip (scalar keys). So a
  serializer/adapter is required, and it must be validated per core.

## 3. Approach

1. **State capture (save):** add `CMD_SAVE_STATE` to `EmulatorProcess`; it returns
   `MSG_STATE_DUMP` = `{"cpu": cpu.examine(), "peripherals": {...}}`. Reuse the
   existing `examine()` (already lossless enough for the debugger). Peripherals
   that hold state (HT24LC08) expose `get_state()` returning their bytes.
2. **State restore (load):** on launch, after the emulator starts, read the saved
   dict from disk and send `CMD_LOAD_STATE`; `EmulatorProcess` applies it via a
   new adapter that converts the saved `cpu` dict into the `edit_state()` shape
   (notably `RAM` tuple → `{index: value}` dict) and restores peripheral state.
3. **EEPROM reliability:** give `HT24LC08` `get_state()`/`set_state(bytes)` and
   include it in the state dump/restore, so it no longer depends on `__del__`.
   Keep the existing `path` load as a fallback/default.
4. **Serializer/adapter (`handheld`-side, pure):** convert `examine()` output →
   on-disk JSON → `edit_state()` input. Handle the RAM tuple↔dict conversion and
   any non-JSON types (tuples → lists). Pure and unit-testable on the dev Mac
   against a captured `examine()` sample per core.
5. **Storage:** `~/.local/share/BrickEmuPy/saves/<config-id>.state` (JSON). EEPROM
   folded into the same dump (the per-game `path` becomes redundant but stays as
   a compatibility default).
6. **Triggers:** save in `GameScreen.teardown()` (back-to-launcher / quit); load
   in `GameScreen.__init__` after the emulator subprocess is up (send
   `CMD_LOAD_STATE` once the child is ready). Corrupt/missing save → clean boot.

## 4. Components

- **`handheld/save_state.py`** (pure): `to_disk(state, path)` / `from_disk(path)`
  (JSON, tuple↔list); `examine_to_editstate(cpu_dict)` (RAM tuple → index dict,
  drop non-restorable keys like `ICTR`/`DEBUG`/disassembly). Unit-tested.
- **`emulator_process.py`** (emulator side): `CMD_SAVE_STATE` → `MSG_STATE_DUMP`;
  `CMD_LOAD_STATE` → apply via `edit_state` + peripheral `set_state`. This is the
  one place the "don't touch emulator_process" constraint is relaxed — the
  additions are small and additive (new command branches), the core loop is
  untouched.
- **`peripherals/HT24LC08.py`**: add `get_state()`/`set_state(bytes)`; register so
  the interconnect can reach it for save/restore.
- **`brick_widget.py` / `handheld/game_screen.py`**: `saveState(path)` /
  `loadState(path)` wrappers over the IPC; called from `GameScreen`.

## 5. Risks (why this is device-gated)

| Risk | Note |
|---|---|
| `examine()` not lossless for a given core | Round-trip correctness (pet actually resumes) can only be confirmed by saving, restarting, and observing on the device |
| RAM tuple↔dict + other type asymmetries | The adapter must be validated per core family (HT4BIT, E0C6200, SPLB32, SPLB20, KS57…) |
| Peripheral state beyond EEPROM | Audit each stateful peripheral (CON_V3_IR, CON_DGM) for hidden state |
| Load timing | `CMD_LOAD_STATE` must land after the child has initialised the core; sequence via a ready handshake or apply-on-first-loop |

## 6. Testing

- **Pure (dev Mac):** `save_state` round-trip (JSON tuple↔list), `examine_to_editstate`
  adapter (RAM tuple→dict, dropped keys) against captured `examine()` fixtures.
- **On-device (pending):** run a pet (e.g. Tamagotchi V3 and an E0C6200 Digimon),
  advance its state, quit, relaunch → state resumes; power-cycle equivalent
  (kill the process) → EEPROM still persisted; verify `saves/<id>.state` written.

## 7. Milestones (implementation-plan tasks — to run when device is back)

1. `handheld/save_state.py` (pure: disk JSON + examine→editstate adapter) + tests.
2. `HT24LC08.get_state/set_state` + tests (pure I2C mem round-trip).
3. `emulator_process` CMD_SAVE_STATE / CMD_LOAD_STATE + MSG_STATE_DUMP.
4. `brick_widget`/`game_screen` save on teardown, load on open.
5. On-device acceptance (pet resumes across relaunch + kill; per-core check).

## 8. Status note

Tasks 1–2 are pure and Mac-verifiable and could be implemented offline; tasks 3–5
touch the emulator and are only meaningfully validated on the device, and the
`examine()` losslessness / adapter correctness is the crux. Per the offline
constraint, this phase is **left at design** until the uConsole is back online,
then executed via the standard subagent-driven flow with the on-device gate.
