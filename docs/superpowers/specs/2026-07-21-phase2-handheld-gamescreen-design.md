# Phase 2 — Handheld GameScreen — Design

**Date:** 2026-07-21
**Target device:** ClockworkPi uConsole (Raspberry Pi CM4), 1280×480 landscape
**Fork:** `git@github.com:btquan/BrickEmuPy-uConsole.git`
**Depends on:** Phase 1 (PyPy subprocess IPC) — merged to `main`.
**Status:** Approved design, ready for implementation planning
**Priority:** Brick games first — acceptance runs on an HT943 brick game.

## 1. Overview

Give the uConsole a fullscreen, handheld-native game view: the emulated device
centered between an info panel (left) and a controls legend (right), on the
1280×480 ultrawide screen. This is a **separate handheld shell** (`main_handheld.py`
+ a `handheld/` package) that reuses the Phase 1 `BrickWidget` (which already
runs the emulator as a PyPy subprocess). The existing desktop/debug `main.py` +
`ui.py` `Window` are left untouched for development.

The launcher (Phase 5) is out of scope; Phase 2 boots directly into the
GameScreen for a `-brick` argument. A `QStackedWidget` host is introduced now so
Phase 5 can add the launcher as a new page with minimal rework.

## 2. Goals / Non-Goals

**Goals**
- `main_handheld.py`: fullscreen entry point that opens a `.brick` game.
- `GameScreen`: 3-column layout `[InfoPanel | BrickWidget | ControlsPanel]`.
- `InfoPanel`: game name, group, battery %, live display FPS.
- `ControlsPanel`: per-game legend of button → key(s), from `config["buttons"]`.
- No changes to `emulator_process.py`, `cores/`, `interconnect.py`, `peripherals/`.

**Non-Goals (later phases)**
- Global physical-input mapping (Phase 3) — Phase 2 uses each `.brick`'s existing
  keyboard `hot_keys`.
- Save-state / EEPROM persistence (Phase 4).
- Launcher grid + game browsing (Phase 5).
- A numeric "headroom" multiplier and a dedicated PyPy-warmup indicator — FPS
  surfaces warmup implicitly; a true headroom number would require touching the
  emulator loop, which this phase deliberately avoids.

## 3. Architecture

```
main_handheld.py ─ QApplication, load ui/style.css, parse -brick, showFullScreen
   └─ HandheldWindow (QMainWindow, frameless fullscreen)
        └─ QStackedWidget (currentIndex 0)
             └─ GameScreen (QWidget, QHBoxLayout)
                  ├─ InfoPanel      (fixed width, left)
                  ├─ BrickWidget    (stretch, center — reused unchanged in behavior)
                  └─ ControlsPanel  (fixed width, right)
```

- The emulator still runs as a PyPy subprocess spawned by `BrickWidget`
  (Phase 1). GameScreen owns one `BrickWidget` per game and gives it focus so it
  receives key events.
- `HandheldWindow` handles fullscreen and an exit shortcut (Esc and Q) that
  triggers `BrickWidget.close()` (its Phase-1 teardown reaps the child) then
  quits the app.

## 4. Components (each: one responsibility, own interface, testable)

### `handheld/battery.py` — pure sysfs reader
- `read_battery(sysfs_root="/sys/class/power_supply") -> BatteryStatus | None`
  where `BatteryStatus` is a small dataclass `{percent: int, charging: bool}`.
- Scans `sysfs_root` for the first supply dir that has a `capacity` file; reads
  `capacity` (int) and `status` (`"Charging"`/`"Full"` → charging=True).
- Returns `None` if no battery is found (e.g., on the dev Mac) or on read error.
- Pure and dependency-free → unit-tested against a fake sysfs directory.

### `handheld/metadata.py` — name/group derivation (pure)
- `game_name(config, brick_path) -> str`: `config.get("name")` else a prettified
  filename stem of `brick_path`.
- `game_group(config) -> str`: `config.get("category")` else a coarse map from
  `config["core"]` → `"Brick"` / `"Virtual Pet"` / `"Other"`. The map is a best
  effort for Phase 2; Phase 5 will formalize categories for the launcher.
- Pure → unit-tested.

### `handheld/fps_counter.py` — pure FPS accumulator
- `class FpsCounter`: `tick()` increments a frame count; `sample(now_seconds) -> float`
  returns frames-per-second since the last `sample` and resets. No Qt, no clock
  of its own (caller passes the timestamp) → unit-tested deterministically.

### `handheld/info_panel.py` — InfoPanel (Qt)
- `QWidget` showing name, group, battery, FPS as labels.
- `set_game(name, group)`; `set_battery(status_or_none)`; `set_fps(value)`.
- Owns a `QTimer` (~5 s) that calls `read_battery()` and updates the battery
  label (hidden/"—" when `None`).
- FPS: driven by GameScreen (see below), rendered as an integer.

### `handheld/controls_panel.py` — ControlsPanel (Qt)
- `QWidget` rendering rows of `button-name → key names` from `config["buttons"]`,
  reusing the key-name formatting already used for tooltips
  (`Qt.Key(code).name`). Pure legend rows are built by a helper
  `controls_legend(config) -> list[tuple[str, str]]` (unit-tested); the widget
  just lays them out.

### `handheld/game_screen.py` — GameScreen (Qt)
- `QWidget` with `QHBoxLayout`: InfoPanel (fixed) | BrickWidget (stretch) |
  ControlsPanel (fixed).
- Constructs `BrickWidget(config, settings)`, connects its new `frameRendered`
  signal to an internal frame tick, and drives a ~1 s `QTimer` that samples
  `FpsCounter` and calls `InfoPanel.set_fps`.
- Sets `game_name`/`game_group` on InfoPanel; gives BrickWidget focus.
- `close()` closes the BrickWidget (Phase-1 teardown).

### `handheld/window.py` — HandheldWindow (Qt)
- `QMainWindow`, frameless + `showFullScreen()`, central `QStackedWidget` with
  GameScreen at index 0.
- Exit shortcuts (Esc, Q) → close GameScreen → `QApplication.quit()`.

### `main_handheld.py` — entry point
- Mirrors `main.py`: `multiprocessing.set_start_method("spawn")` is NOT needed
  (Phase 1 replaced multiprocessing), load `ui/style.css`, parse `-brick`
  (required; error clearly if missing/unreadable), build `HandheldWindow`,
  `showFullScreen()`.

### Change to `brick_widget.py` (additive)
- Add `frameRendered = pyqtSignal()` and `self.frameRendered.emit()` inside the
  `MSG_VRAM` branch of `_processMessage` (or at the end of `_renderVRAM`). No
  behavior change to the desktop app, which simply ignores the signal.

## 5. Data flow

- Emulator → `BrickWidget._processMessage`: `MSG_VRAM` renders the display and
  emits `frameRendered`; GameScreen's `FpsCounter.tick()` counts it; a 1 s timer
  samples FPS → InfoPanel.
- `examineSignal` (already emitted by BrickWidget) is not required by Phase 2's
  InfoPanel (FPS comes from VRAM frames, not examine) — leave it unconnected in
  the handheld shell for now.
- Battery: InfoPanel's own 5 s timer polls `read_battery()`.

## 6. Layout on 1280×480

- `GameScreen` `QHBoxLayout`: side panels get fixed widths (a fraction of 1280,
  e.g. ~200–260 px each); BrickWidget takes the remaining center and self-fits
  via its existing `fitInView(KeepAspectRatio)`, so portrait faces letterbox
  cleanly between the panels.
- Fullscreen, frameless; no menu/status bar.

## 7. Error handling

- `-brick` missing/invalid JSON/missing ROM: `main_handheld.py` prints a clear
  message and exits non-zero (no silent blank window).
- `read_battery()` returns `None` on any error → battery line hidden; never
  raises into the UI.
- Emulator child death is already handled by Phase 1 (guarded `FramedWriter.put`,
  reader `EOFError`); GameScreen inherits that robustness.

## 8. Testing

- **Pure unit tests (run anywhere, incl. dev Mac without PyQt6):**
  `battery.read_battery` (fake sysfs: present/charging/absent/malformed),
  `metadata.game_name`/`game_group` (explicit field vs fallback vs core map),
  `fps_counter.FpsCounter` (deterministic timestamps), `controls_legend`.
- **Qt smoke tests (on-device, PyQt6 present, `QT_QPA_PLATFORM=offscreen`):**
  construct InfoPanel/ControlsPanel/GameScreen with a brick config without
  raising; assert the panels contain the expected labels/rows.
- **On-device GUI acceptance:** `python3 main_handheld.py -brick
  assets/E23PlusMarkII96in1.brick` — fullscreen 3-column view; game renders and
  responds to keys; battery % and FPS update; emulator child is PyPy.

## 9. Milestones (implementation-plan tasks)

1. `battery.py` + tests.
2. `metadata.py` (name/group) + tests.
3. `fps_counter.py` + tests; `controls_legend` helper + tests.
4. `brick_widget.py`: add `frameRendered` signal (additive) + py_compile.
5. `info_panel.py`, `controls_panel.py` (Qt) + on-device offscreen smoke.
6. `game_screen.py` + `window.py` + `main_handheld.py` (Qt wiring) + on-device
   offscreen smoke.
7. On-device GUI acceptance on a brick game.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Group metadata is coarse (core→category is imperfect) | Labeled best-effort; Phase 5 formalizes categories; name is always accurate |
| Qt tests can't run on the dev Mac (no PyQt6) | Pure logic covers most; Qt smoke + acceptance run on-device (offscreen) as in Phase 1 |
| Side-panel widths crowd portrait faces | Fixed but modest widths; center uses remaining space with aspect-fit |
| FPS is a proxy, not true headroom | Accepted per design; FPS still surfaces warmup/keeping-up |
