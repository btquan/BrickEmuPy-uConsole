# BrickEmuPy → uConsole Handheld Fork — Design

**Date:** 2026-07-21
**Target device:** ClockworkPi uConsole with Raspberry Pi Compute Module 4
**Fork:** `git@github.com:btquan/BrickEmuPy-uConsole.git` (upstream: azya52/BrickEmuPy)
**Status:** Approved design, ready for implementation planning
**Priority:** Brick games first (HT943 / EM73000 / SPL0x group) as the primary
target and acceptance content for the early phases; virtual pets and their
EEPROM save-state polish come after. HT943 brick games run comfortably on both
CPython (2.10x) and PyPy (11.71x), making them a low-risk vertical slice.

## 1. Overview

Fork BrickEmuPy into a handheld-native experience for the ClockworkPi uConsole
(CM4). The device boots into a grid launcher of the ~64 bundled games, runs the
selected game fullscreen on the 1280×480 ultrawide screen with side panels,
maps the uConsole's physical controls to game buttons, and auto-saves/restores
each game's state (critical for the always-running virtual pets).

The emulator core logic (`cores/`, `interconnect.py`, `peripherals/`) is **not
modified**. All new work lives in a UI/handheld layer plus a reworked
process/IPC boundary that lets the emulation run under **PyPy** for speed while
the Qt UI stays on CPython.

## 2. Goals / Non-Goals

**Goals**
- Boot-to-launcher, grid picker with SVG thumbnails, controller/keyboard navigation.
- Fullscreen game view: game centered, info panel (left) + controls panel (right).
- Global physical-input mapping with optional per-game override.
- Auto-persist state on exit/switch, auto-restore on open (CPU + RAM + EEPROM).
- Real-time emulation for the whole library on CM4 via a PyPy emulator subprocess.

**Non-Goals**
- Rewriting or "optimizing" individual CPU cores (PyPy handles performance).
- Netplay/serial-link features beyond what already exists.
- Supporting non-CM4 uConsole core modules in this fork (documented, not built).
- Adding new emulated machines.

## 3. Hardware baseline (measured on the actual device)

| Property | Value |
|---|---|
| SoC | Raspberry Pi CM4 Rev 1.1, Cortex-A72 aarch64 |
| Clock under load | 1.8 GHz all 4 cores (schedutil ramps to max) |
| RAM | 3.5 GiB |
| OS | Debian GNU/Linux 13 (trixie) |
| CPython | 3.13.5 (PyQt6 **not** preinstalled; apt/pip available) |
| PyPy | not installed; portable pypy3.11 v7.3.19 aarch64 verified working |
| Idle temp | ~43 °C (no throttling observed) |

### 3.1 Benchmark verdict (Phase-0, measured on this uConsole)

Headless dispatch-loop benchmark (`realtime_factor = emulated_cycles_per_sec /
chip_clock`). CPython already runs at the 1.8 GHz ceiling, so its numbers are the
hardware limit. PyPy figures are **steady-state after ~6 s JIT warmup**.

| Core | Games | CPython | PyPy (warm) |
|---|---|---:|---:|
| E0C6200 | Tamagotchi / Digimon virtual pets | 0.90x | 2.85x |
| HT943 | Brick E-23 / E-88 / GA888 | 2.10x | 11.71x |
| EM73000 | E-33 2-in-1 | 0.94x | 4.12x |
| SPL02 | Apollo 126-in-1 | 0.88x | 5.08x |
| SPL03 | Apollo 18-in-1 | 0.97x | 5.10x |
| SPLB20 | Big Cat / Gyaoppi | 1.51x | 2.47x |
| KS57C21308 | Pocket Puppy | 1.37x | 1.64x |
| KS57C2504 | Kunekunetchyo | 0.96x | 1.43x |

**Conclusion:** CPython cannot sustain real time for ~5 cores (including virtual
pets) even at max clock. PyPy clears every tested core (1.4x–11.7x). The only
cost is a multi-second JIT warmup, handled in §8.

## 4. Runtime architecture

```
CPython 3.13 process (system)                 PyPy 3.11 subprocess
┌───────────────────────────────┐            ┌─────────────────────────┐
│ PyQt6 UI                       │  cmd pipe  │ emulator_main.py        │
│  Window (QStackedWidget)       │ ─────────► │  EmulatorProcess (loop) │
│   ├ LauncherScreen             │            │   ├ Interconnect        │
│   └ GameScreen                 │  data pipe │   ├ cores/* (unchanged) │
│      [Info | Brick | Controls] │ ◄───────── │   └ peripherals/*       │
│  InputMapper, SaveStateManager │  (pickle)  │                         │
└───────────────────────────────┘            └─────────────────────────┘
```

- **Why a subprocess, not `multiprocessing`:** PyQt6 cannot run on PyPy, and
  `multiprocessing` reuses the parent interpreter (`sys.executable`). To run the
  emulator on PyPy while the UI stays on CPython, the child is launched as an
  explicit `pypy3 emulator_main.py` subprocess.
- **IPC:** two byte pipes (child stdin = commands, child stdout = data), each
  message length-prefixed and pickled (protocol 5). Payloads are plain
  tuples/dicts/ints/bytes → compatible across CPython 3.13 ↔ PyPy 3.11. `stderr`
  is captured for error surfacing. This replaces the existing
  `multiprocessing.Queue` pair; the message opcodes (`MSG_VRAM`, `CMD_BTN_PRESS`,
  …) and the emulator loop body are reused as-is.
- **Isolation preserved:** `cores/`, `interconnect.py`, `peripherals/`,
  `emulator_process.py` loop logic are untouched. Only the transport
  (`brick_widget._start_emulator` / new `emulator_main.py` entrypoint) changes.
- **Fallback:** if `pypy3` is absent, launch the same entrypoint under CPython so
  the app still runs (slower). One code path, interpreter chosen at spawn time.

## 5. UI components (each: one responsibility, testable in isolation)

- **`Window`** — `QStackedWidget` holding LauncherScreen (index 0, boot target)
  and GameScreen (index 1). Owns fullscreen, global shortcuts, screen switching.
- **`LauncherScreen`** — scans `assets/*.brick`, renders a keyboard/trackball
  navigable grid of SVG `body`-element thumbnails, grouped (Brick / Virtual Pet /
  Other). Enter launches; shows only games whose ROM is present.
- **`GameScreen`** — horizontal layout `[InfoPanel | BrickWidget | ControlsPanel]`.
  Reuses the existing `BrickWidget` unchanged for the emulated display.
- **`InfoPanel`** (left) — game name, group, battery % (`/sys/class/power_supply`),
  live FPS / emulation headroom (from the existing 30 Hz examine stream),
  warmup indicator.
- **`ControlsPanel`** (right) — per-game control legend derived from the active
  input mapping.
- **`InputMapper`** — translates uConsole physical keys → canonical roles
  (D-pad, A/B/X/Y, Start, Select, Menu) → the Qt key codes each `.brick` already
  listens for. Loads a global profile (`uconsole.json`); a `.brick` may carry an
  `input_override` block. Falls back to the game's existing `hot_keys`.
- **`SaveStateManager`** — orchestrates save/restore over the IPC boundary,
  persists to `~/.local/share/BrickEmuPy/saves/<config-id>.state`.

## 6. Save-state

- New commands `CMD_SAVE_STATE` / `CMD_LOAD_STATE`; new reply `MSG_STATE_DUMP`.
- Baseline serialization reuses `cpu.examine()` (already returns ACC/PC/STACK/
  RAM/ports/…) and `cpu.edit_state()` (already restores them).
- **Investigation item (do first):** confirm whether the `HT24LC08` EEPROM
  peripheral (virtual-pet NVRAM) already persists to disk. If not, add
  `get_state()/set_state()` to it (and any other stateful peripheral). This is
  the survival data for Tamagotchi/Digimon and must round-trip.
- Auto-save triggers: leaving GameScreen, app close. Auto-restore on game open if
  a state file exists; corrupt/missing → clean boot.

## 7. Display layout on 1280×480

- GameScreen uses a 3-column layout; the center reuses `BrickWidget`'s existing
  `fitInView(KeepAspectRatio)`, so portrait faces letterbox cleanly between the
  panels and landscape faces (Game Watch, soccer) fill more width.
- Panel widths are a fraction of screen width, collapsible for very wide faces.
- Fullscreen kiosk; menubar/statusbar hidden (existing fullscreen path reused).

## 8. JIT warmup handling

PyPy needs ~5–8 s to reach steady state for a core's opcode set. Strategy:
- On game launch, the InfoPanel shows a brief "warming up" state; emulation still
  runs (just below full speed initially), matching the real device's boot/attract
  sequence, so it is largely masked.
- Speed ramps automatically as the JIT compiles; no code change needed to the
  loop. Optionally cap perceived-slow startup by keeping the display responsive.
- Not pre-warming with synthetic input (YAGNI) unless testing shows the ramp is
  intrusive.

## 9. Packaging & deployment

- **`install.sh`** (idempotent, runs on the uConsole):
  - apt: `python3-pyqt6`, `libxcb-cursor0` (UI on system CPython).
  - PyPy: install `pypy3` via apt *or* unpack the bundled portable pypy3 aarch64
    into the repo (no-sudo path). Record the interpreter path in config.
  - Set the CPU governor / keep-max-clock hint while a game runs (userspace where
    permitted; documented sudo step otherwise).
  - Autostart entry (systemd user service or desktop autostart) that launches the
    app fullscreen into the launcher.
- **`uconsole.json`** — physical-key → role profile, shipped default + editable.
- Saves and settings under `~/.local/share/BrickEmuPy/` and `QSettings`.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| PyPy JIT warmup feels slow at game start | §8; masked by boot/attract; ramps in seconds |
| EEPROM state not currently persisted | §6 investigation item done before wiring auto-save |
| Cross-interpreter pickle incompatibility | Payloads restricted to builtin types; protocol 5; covered by IPC tests |
| Thermal throttling in enclosed handheld | Monitor temp in InfoPanel; PyPy headroom (1.4–11.7x) absorbs mild throttling |
| uConsole physical keys differ from assumptions | Mapping isolated in `uconsole.json` + `InputMapper`; adjustable without code |

## 11. Testing

- **IPC layer:** unit tests for message framing/round-trip; a CPython↔PyPy
  round-trip smoke test for every message opcode.
- **SaveStateManager:** save→restore equivalence per core (examine() before/after),
  including an EEPROM-backed virtual pet.
- **InputMapper:** role→keycode resolution, override precedence, hot_keys fallback.
- **LauncherScreen:** ROM-presence filtering, grouping.
- **On-device Phase-0 re-check:** `bench_cores.py` (already written) as a
  regression gate for real-time headroom.

## 12. Phased milestones

Acceptance content is a **brick game (HT943, e.g. E-23 PLUS)** through Phases
1–3 and 5; virtual pets enter at Phase 4.

0. **Phase 0 — perf validation (DONE):** headless benchmark on the device;
   PyPy-for-emulator decision confirmed with data.
1. **IPC rework:** replace `multiprocessing.Queue` with a PyPy subprocess +
   pipe/pickle transport (CPython fallback); a brick game runs end-to-end.
2. **GameScreen layout:** 3-column panels, InfoPanel (battery/FPS/warmup),
   ControlsPanel — validated on a brick game.
3. **InputMapper + `uconsole.json`:** global mapping + per-game override; tuned
   for brick-game controls (D-pad + rotate + start) first.
4. **SaveStateManager:** EEPROM investigation, save/restore, auto-persist —
   brings virtual pets into scope.
5. **LauncherScreen:** grid thumbnails, navigation, grouping (Brick group
   first), boot target.
6. **Packaging:** `install.sh`, autostart, PyPy bundling, on-device acceptance.
