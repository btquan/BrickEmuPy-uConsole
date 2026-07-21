# Phase 2 — Handheld GameScreen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fullscreen handheld shell (`main_handheld.py` + `handheld/` package) that opens a `.brick` game in a 3-column GameScreen — InfoPanel (name/group/battery/FPS) | reused BrickWidget | ControlsPanel (key legend) — on the uConsole's 1280×480 screen.

**Architecture:** Pure, PyQt6-free helpers (`battery`, `metadata`, `fps_counter`, `controls`) hold all testable logic and are unit-tested on the dev machine. Thin Qt widgets (`info_panel`, `controls_panel`, `game_screen`, `window`) and `main_handheld.py` only lay out and wire those helpers plus the Phase-1 `BrickWidget`, and are runtime-verified on-device. The only change to existing code is one additive `frameRendered` signal on `BrickWidget`.

**Tech Stack:** Python 3, PyQt6 (UI only, on-device), pytest (pure tests, dev machine).

## Global Constraints

- Do NOT modify `emulator_process.py`, `cores/`, `interconnect.py`, or `peripherals/`. The only change to existing code is an additive `frameRendered` signal in `brick_widget.py`; `BrickWidget` is otherwise reused as-is.
- Pure helpers (`handheld/battery.py`, `handheld/metadata.py`, `handheld/fps_counter.py`, `handheld/controls.py`) must NOT import PyQt6, so they run in CI/dev without Qt. All PyQt6 imports live only in `info_panel.py`, `controls_panel.py`, `game_screen.py`, `window.py`, `main_handheld.py`.
- `controls_legend(config, key_name)` takes an injected `key_name(code) -> str` function so its logic stays PyQt6-free; the widget passes `lambda c: Qt.Key(c).name`.
- The dev Mac has NO PyQt6 — Qt modules are verified there with `python3 -m py_compile` only; their runtime behavior is verified on-device (Task 7), mirroring Phase 1.
- Run pure tests with `/Users/i4cu/.venv/bin/python -m pytest` (plain `python3 -m pytest` is intercepted by a shell hook on the dev machine).
- Emulator still runs as the Phase-1 PyPy subprocess via `BrickWidget`; nothing in this phase changes that path.

---

### Task 1: Battery reader (`handheld/battery.py`)

**Files:**
- Create: `handheld/__init__.py` (empty)
- Create: `handheld/battery.py`
- Test: `tests/test_battery.py`

**Interfaces:**
- Produces: `BatteryStatus` dataclass `{percent: int, charging: bool}` and
  `read_battery(sysfs_root="/sys/class/power_supply") -> BatteryStatus | None`.
  Returns `None` when no battery/capacity is found or any read fails.

- [ ] **Step 1: Write the failing test**

Create `handheld/__init__.py` (empty), then `tests/test_battery.py`:

```python
from handheld.battery import read_battery, BatteryStatus


def _make_supply(root, name, capacity=None, status=None):
    d = root / name
    d.mkdir()
    if capacity is not None:
        (d / "capacity").write_text(capacity)
    if status is not None:
        (d / "status").write_text(status)
    return d


def test_reads_percent_and_discharging(tmp_path):
    _make_supply(tmp_path, "BAT0", capacity="83\n", status="Discharging\n")
    s = read_battery(str(tmp_path))
    assert s == BatteryStatus(percent=83, charging=False)


def test_charging_and_full_map_to_charging(tmp_path):
    _make_supply(tmp_path, "BAT0", capacity="50", status="Charging")
    assert read_battery(str(tmp_path)).charging is True
    (tmp_path / "BAT0" / "status").write_text("Full")
    assert read_battery(str(tmp_path)).charging is True


def test_skips_supplies_without_capacity(tmp_path):
    _make_supply(tmp_path, "AC", status="Charging")          # no capacity file
    _make_supply(tmp_path, "BAT0", capacity="12", status="Discharging")
    assert read_battery(str(tmp_path)).percent == 12


def test_none_when_no_battery(tmp_path):
    assert read_battery(str(tmp_path)) is None


def test_none_on_missing_root():
    assert read_battery("/nonexistent/path/xyz") is None


def test_none_on_malformed_capacity(tmp_path):
    _make_supply(tmp_path, "BAT0", capacity="not-a-number", status="Full")
    assert read_battery(str(tmp_path)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_battery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'handheld.battery'`.

- [ ] **Step 3: Write minimal implementation**

Create `handheld/battery.py`:

```python
"""Read uConsole battery state from sysfs. Pure and PyQt6-free."""
import os
from dataclasses import dataclass


@dataclass
class BatteryStatus:
    percent: int
    charging: bool


def read_battery(sysfs_root="/sys/class/power_supply"):
    try:
        for name in sorted(os.listdir(sysfs_root)):
            base = os.path.join(sysfs_root, name)
            cap_path = os.path.join(base, "capacity")
            if not os.path.isfile(cap_path):
                continue
            with open(cap_path) as f:
                percent = int(f.read().strip())
            charging = False
            status_path = os.path.join(base, "status")
            if os.path.isfile(status_path):
                with open(status_path) as f:
                    charging = f.read().strip().lower() in ("charging", "full")
            return BatteryStatus(percent=percent, charging=charging)
    except (OSError, ValueError):
        return None
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_battery.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add handheld/__init__.py handheld/battery.py tests/test_battery.py
git commit -m "feat: pure sysfs battery reader for handheld InfoPanel"
```

---

### Task 2: Name/group derivation (`handheld/metadata.py`)

**Files:**
- Create: `handheld/metadata.py`
- Test: `tests/test_metadata.py`

**Interfaces:**
- Produces: `game_name(config: dict, brick_path: str) -> str` and
  `game_group(config: dict) -> str`. `game_name` prefers `config["name"]`, else a
  prettified `.brick` filename stem. `game_group` prefers `config["category"]`,
  else a coarse `config["core"]` → group map, else `"Other"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_metadata.py`:

```python
from handheld.metadata import game_name, game_group


def test_name_prefers_explicit_field():
    assert game_name({"name": "Tetris Jr."}, "/x/GA888.brick") == "Tetris Jr."


def test_name_falls_back_to_prettified_stem():
    assert game_name({}, "/x/E23PlusMarkII96in1.brick") == "E23PlusMarkII96in1"
    assert game_name({}, "/x/E33_2in1.brick") == "E33 2in1"


def test_group_prefers_explicit_category():
    assert game_group({"category": "Puzzle", "core": "HT943"}) == "Puzzle"


def test_group_falls_back_to_core_map():
    assert game_group({"core": "HT943"}) == "Brick"
    assert game_group({"core": "E0C6200"}) == "Virtual Pet"


def test_group_unknown_core_is_other():
    assert game_group({"core": "T6770S"}) == "Other"
    assert game_group({}) == "Other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_metadata.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'handheld.metadata'`.

- [ ] **Step 3: Write minimal implementation**

Create `handheld/metadata.py`:

```python
"""Derive a display name and group for a .brick game. Pure and PyQt6-free.

The .brick format has no name/category fields; these are best-effort. Phase 5
will formalize categories for the launcher.
"""
import os

_CORE_GROUP = {
    "HT943": "Brick",
    "EM73000": "Brick",
    "SPL02": "Brick",
    "SPL03": "Brick",
    "SPL81408": "Brick",
    "E0C6200": "Virtual Pet",
    "SPLB32": "Virtual Pet",
    "SPLB20": "Virtual Pet",
    "KS57C21308": "Virtual Pet",
}


def game_name(config, brick_path):
    name = config.get("name")
    if name:
        return name
    stem = os.path.splitext(os.path.basename(brick_path))[0]
    return stem.replace("_", " ")


def game_group(config):
    category = config.get("category")
    if category:
        return category
    return _CORE_GROUP.get(config.get("core"), "Other")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_metadata.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add handheld/metadata.py tests/test_metadata.py
git commit -m "feat: game name/group derivation for handheld InfoPanel"
```

---

### Task 3: FPS counter + controls legend (`handheld/fps_counter.py`, `handheld/controls.py`)

**Files:**
- Create: `handheld/fps_counter.py`
- Create: `handheld/controls.py`
- Test: `tests/test_fps_counter.py`
- Test: `tests/test_controls.py`

**Interfaces:**
- Produces: `FpsCounter` with `tick()` and `sample(now_seconds) -> float`
  (frames since last sample ÷ elapsed; first sample seeds and returns 0.0).
- Produces: `controls_legend(config, key_name) -> list[tuple[str, str]]` — one
  `(button_name, "K1, K2")` row per `config["buttons"]` entry, formatting each
  hot-key code through the injected `key_name(code) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fps_counter.py`:

```python
from handheld.fps_counter import FpsCounter


def test_first_sample_seeds_and_returns_zero():
    c = FpsCounter()
    assert c.sample(100.0) == 0.0


def test_counts_frames_per_elapsed_second():
    c = FpsCounter()
    c.sample(0.0)                 # seed
    for _ in range(30):
        c.tick()
    assert c.sample(1.0) == 30.0


def test_resets_between_samples():
    c = FpsCounter()
    c.sample(0.0)
    c.tick(); c.tick()
    assert c.sample(1.0) == 2.0
    assert c.sample(2.0) == 0.0   # no ticks since last sample


def test_zero_elapsed_returns_zero():
    c = FpsCounter()
    c.sample(5.0)
    c.tick()
    assert c.sample(5.0) == 0.0   # dt == 0, no divide-by-zero
```

Create `tests/test_controls.py`:

```python
from handheld.controls import controls_legend


def test_builds_rows_with_injected_key_name():
    config = {"buttons": {
        "btnLeft": {"hot_keys": [65, 16777234]},
        "btnRotate": {"hot_keys": [32]},
    }}
    rows = controls_legend(config, lambda c: f"K{c}")
    assert rows == [
        ("btnLeft", "K65, K16777234"),
        ("btnRotate", "K32"),
    ]


def test_handles_missing_buttons_and_hotkeys():
    assert controls_legend({}, lambda c: str(c)) == []
    rows = controls_legend({"buttons": {"btnX": {}}}, lambda c: str(c))
    assert rows == [("btnX", "")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_fps_counter.py tests/test_controls.py -v`
Expected: FAIL with `ModuleNotFoundError` for `handheld.fps_counter` / `handheld.controls`.

- [ ] **Step 3: Write minimal implementations**

Create `handheld/fps_counter.py`:

```python
"""Frame-rate accumulator. Pure and PyQt6-free; caller supplies timestamps."""


class FpsCounter:
    def __init__(self):
        self._frames = 0
        self._last = None

    def tick(self):
        self._frames += 1

    def sample(self, now_seconds):
        if self._last is None:
            self._last = now_seconds
            self._frames = 0
            return 0.0
        dt = now_seconds - self._last
        frames = self._frames
        self._last = now_seconds
        self._frames = 0
        if dt <= 0:
            return 0.0
        return frames / dt
```

Create `handheld/controls.py`:

```python
"""Build a button->keys legend from a .brick config. Pure and PyQt6-free.

key_name(code) is injected so this module never imports PyQt6; the widget
passes lambda c: Qt.Key(c).name.
"""


def controls_legend(config, key_name):
    rows = []
    for name, value in config.get("buttons", {}).items():
        keys = ", ".join(key_name(code) for code in value.get("hot_keys", []))
        rows.append((name, keys))
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_fps_counter.py tests/test_controls.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add handheld/fps_counter.py handheld/controls.py tests/test_fps_counter.py tests/test_controls.py
git commit -m "feat: pure FPS counter and controls-legend builder"
```

---

### Task 4: `frameRendered` signal on `BrickWidget`

**Files:**
- Modify: `brick_widget.py` (class attribute + emit in the `MSG_VRAM` branch)

**Interfaces:**
- Produces: `BrickWidget.frameRendered` (`pyqtSignal()`), emitted once per VRAM
  frame rendered — GameScreen (Task 6) connects it to `FpsCounter.tick`.

- [ ] **Step 1: Add the signal declaration**

In `brick_widget.py`, find:
```python
class BrickWidget(QtWidgets.QGraphicsView):
    examineSignal = pyqtSignal(dict)
    connectionSignal = pyqtSignal(bytes)
```
Replace with:
```python
class BrickWidget(QtWidgets.QGraphicsView):
    examineSignal = pyqtSignal(dict)
    connectionSignal = pyqtSignal(bytes)
    frameRendered = pyqtSignal()
```

- [ ] **Step 2: Emit on each VRAM frame**

In `brick_widget.py`, find:
```python
        if (op == MSG_VRAM):
            self._renderVRAM(msg[1])
```
Replace with:
```python
        if (op == MSG_VRAM):
            self._renderVRAM(msg[1])
            self.frameRendered.emit()
```

- [ ] **Step 3: Byte-compile and run the existing suite**

Run: `python3 -m py_compile brick_widget.py`
Expected: exit 0, no output.

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/ -q`
Expected: all Phase-1 + Phase-2 pure tests still PASS (Qt not imported by any test).

- [ ] **Step 4: Commit**

```bash
git add brick_widget.py
git commit -m "feat: BrickWidget.frameRendered signal for FPS measurement"
```

---

### Task 5: Qt leaf panels (`handheld/info_panel.py`, `handheld/controls_panel.py`)

**Files:**
- Create: `handheld/info_panel.py`
- Create: `handheld/controls_panel.py`

**Interfaces:**
- Produces: `InfoPanel(QWidget)` with `set_game(name, group)`, `set_fps(value)`,
  and an internal 5 s battery poll; `ControlsPanel(config, parent=None)` rendering
  the legend rows.
- Consumes: `handheld.battery.read_battery`, `handheld.controls.controls_legend`.

**Note:** The dev Mac has no PyQt6, so these are verified here with `py_compile`
only; runtime construction is verified on-device in Task 7.

- [ ] **Step 1: Write `info_panel.py`**

Create `handheld/info_panel.py`:

```python
from PyQt6 import QtWidgets, QtCore

from handheld.battery import read_battery


class InfoPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        self._name = QtWidgets.QLabel("")
        self._group = QtWidgets.QLabel("")
        self._battery = QtWidgets.QLabel("")
        self._fps = QtWidgets.QLabel("")
        for w in (self._name, self._group, self._battery, self._fps):
            w.setObjectName("infoLabel")
            layout.addWidget(w)
        layout.addStretch(1)

        self._batteryTimer = QtCore.QTimer(self)
        self._batteryTimer.timeout.connect(self._pollBattery)
        self._batteryTimer.start(5000)
        self._pollBattery()

    def set_game(self, name, group):
        self._name.setText(name)
        self._group.setText(group)

    def set_fps(self, value):
        self._fps.setText("%.0f FPS" % value)

    def _pollBattery(self):
        status = read_battery()
        if status is None:
            self._battery.setVisible(False)
            return
        self._battery.setVisible(True)
        self._battery.setText(
            "%d%%%s" % (status.percent, " (charging)" if status.charging else "")
        )
```

- [ ] **Step 2: Write `controls_panel.py`**

Create `handheld/controls_panel.py`:

```python
from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from handheld.controls import controls_legend


class ControlsPanel(QtWidgets.QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        for name, keys in controls_legend(config, lambda c: Qt.Key(c).name):
            label = QtWidgets.QLabel("%s: %s" % (name, keys))
            label.setObjectName("controlLabel")
            layout.addWidget(label)
        layout.addStretch(1)
```

- [ ] **Step 3: Byte-compile both**

Run: `python3 -m py_compile handheld/info_panel.py handheld/controls_panel.py`
Expected: exit 0, no output. (Runtime import of PyQt6 is verified on-device in Task 7.)

- [ ] **Step 4: Commit**

```bash
git add handheld/info_panel.py handheld/controls_panel.py
git commit -m "feat: handheld InfoPanel and ControlsPanel widgets"
```

---

### Task 6: Qt shell (`handheld/game_screen.py`, `handheld/window.py`, `main_handheld.py`)

**Files:**
- Create: `handheld/game_screen.py`
- Create: `handheld/window.py`
- Create: `main_handheld.py`

**Interfaces:**
- Produces: `GameScreen(config, brick_path, settings, parent=None)` (3-column
  layout, owns a `BrickWidget`, drives FPS); `HandheldWindow(config, brick_path,
  settings)` (fullscreen, `QStackedWidget` host, Esc to exit); `main_handheld.py`
  entry point (`-brick` required).
- Consumes: `BrickWidget` (+ its `frameRendered`), `InfoPanel`, `ControlsPanel`,
  `FpsCounter`, `game_name`, `game_group`.

**Note:** Verified with `py_compile` here; runtime verified on-device in Task 7.
Exit shortcut is **Esc only** (not Q) — the spec mentioned Q, but Q can collide
with a game button, so it is intentionally omitted.

- [ ] **Step 1: Write `game_screen.py`**

Create `handheld/game_screen.py`:

```python
import time

from PyQt6 import QtWidgets, QtCore

from brick_widget import BrickWidget
from handheld.info_panel import InfoPanel
from handheld.controls_panel import ControlsPanel
from handheld.fps_counter import FpsCounter
from handheld.metadata import game_name, game_group

PANEL_WIDTH = 220


class GameScreen(QtWidgets.QWidget):
    def __init__(self, config, brick_path, settings, parent=None):
        super().__init__(parent)

        self._info = InfoPanel()
        self._info.setFixedWidth(PANEL_WIDTH)
        self._brick = BrickWidget(config, settings)
        self._controls = ControlsPanel(config)
        self._controls.setFixedWidth(PANEL_WIDTH)

        layout = QtWidgets.QHBoxLayout(self)
        layout.addWidget(self._info)
        layout.addWidget(self._brick, 1)
        layout.addWidget(self._controls)

        self._info.set_game(game_name(config, brick_path), game_group(config))

        self._fps = FpsCounter()
        self._brick.frameRendered.connect(self._fps.tick)
        self._fpsTimer = QtCore.QTimer(self)
        self._fpsTimer.timeout.connect(self._sampleFps)
        self._fpsTimer.start(1000)

        self._brick.setFocus()

    def _sampleFps(self):
        self._info.set_fps(self._fps.sample(time.monotonic()))

    def close(self):
        self._fpsTimer.stop()
        self._brick.close()
        return super().close()
```

- [ ] **Step 2: Write `window.py`**

Create `handheld/window.py`:

```python
from PyQt6 import QtWidgets, QtCore
from PyQt6.QtGui import QShortcut

from handheld.game_screen import GameScreen


class HandheldWindow(QtWidgets.QMainWindow):
    def __init__(self, config, brick_path, settings, parent=None):
        super().__init__(parent)
        self._stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self._stack)

        self._game = GameScreen(config, brick_path, settings)
        self._stack.addWidget(self._game)
        self._stack.setCurrentWidget(self._game)

        QShortcut(QtCore.Qt.Key.Key_Escape, self).activated.connect(self.close)

    def closeEvent(self, event):
        self._game.close()
        super().closeEvent(event)
```

- [ ] **Step 3: Write `main_handheld.py`**

Create `main_handheld.py`:

```python
import sys
import json
import argparse

from PyQt6 import QtWidgets, QtCore

from handheld.window import HandheldWindow


def main():
    parser = argparse.ArgumentParser(description="BrickEmuPy handheld shell.")
    parser.add_argument("-brick", required=True, help="Brick Game config (*.brick)")
    args = parser.parse_args()

    try:
        with open(args.brick) as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print("Cannot open brick config: %s" % e, file=sys.stderr)
        return 2

    app = QtWidgets.QApplication(sys.argv)
    try:
        with open("ui/style.css") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        pass

    settings = QtCore.QSettings("azya", "BrickEmuPy")
    window = HandheldWindow(config, args.brick, settings)
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Byte-compile all three**

Run: `python3 -m py_compile main_handheld.py handheld/game_screen.py handheld/window.py`
Expected: exit 0, no output.

- [ ] **Step 5: Commit**

```bash
git add main_handheld.py handheld/game_screen.py handheld/window.py
git commit -m "feat: handheld GameScreen, window, and fullscreen entry point"
```

---

### Task 7: On-device offscreen smoke + GUI acceptance (uConsole)

**Files:** None (verification; no repo changes unless a defect is found).

**Interfaces:** Consumes everything from Tasks 1–6, plus PyQt6 on the uConsole
(`python3-pyqt6`, `python3-pyqt6.qtsvg`, `python3-pyqt6.qtmultimedia`,
`python3-pyqt6.qtserialport`, `pyqt6-dev-tools`) and the bundled
`~/pypy-portable/bin/pypy3`.

- [ ] **Step 1: Get the branch onto the device**

On the uConsole:
`cd ~/Projects/BrickEmuPy && git fetch fork phase2-handheld-gamescreen && git checkout phase2-handheld-gamescreen`

- [ ] **Step 2: Offscreen construction smoke (no display needed)**

On the uConsole, from the repo dir:
```bash
QT_QPA_PLATFORM=offscreen python3 -c "
import sys, json
from PyQt6 import QtWidgets
from handheld.window import HandheldWindow
from PyQt6.QtCore import QSettings
app = QtWidgets.QApplication(sys.argv)
cfg = json.load(open('assets/E23PlusMarkII96in1.brick'))
w = HandheldWindow(cfg, 'assets/E23PlusMarkII96in1.brick', QSettings('azya','BrickEmuPy'))
print('constructed OK; child pid', w._game._brick._proc.pid)
w.close()
print('closed OK')
"
```
Expected: prints `constructed OK; child pid <n>` then `closed OK` with no traceback — proves the widget tree builds, the emulator child spawns via Phase-1 path, and teardown works. (`pgrep -af pypy3` should show nothing left after close.)

- [ ] **Step 3: GUI acceptance (physical display)**

On the uConsole with a session:
`cd ~/Projects/BrickEmuPy && python3 main_handheld.py -brick assets/E23PlusMarkII96in1.brick`
Expected: fullscreen 3-column view — InfoPanel (name "E23PlusMarkII96in1", group "Brick", battery %, FPS updating each second) on the left, the E-23 game centered and rendering, ControlsPanel (button→key rows) on the right; keys play the game; `pgrep -af pypy3` shows the PyPy child. Esc exits cleanly.

- [ ] **Step 4: Record the result**

Note in the progress ledger: offscreen smoke result, observed FPS at steady state, battery reading present, any stderr noise. No commit needed unless a defect fix was required in Tasks 1–6.

---

## Self-Review

**Spec coverage:**
- §3 architecture (main_handheld → HandheldWindow → QStackedWidget → GameScreen[Info|Brick|Controls]) → Tasks 5, 6. ✓
- §4 battery.py → Task 1; metadata name/group → Task 2; fps_counter + controls_legend → Task 3; InfoPanel/ControlsPanel → Task 5; GameScreen/window → Task 6; frameRendered signal → Task 4. ✓
- §4 pure helpers PyQt6-free (battery/metadata/fps_counter/controls) → enforced by import lists; tests import them without Qt. ✓
- §5 FPS from frameRendered (not examine) → Task 4 emit + Task 6 wiring. ✓
- §7 error handling: `-brick` invalid exits non-zero (Task 6 main); `read_battery` None hides line (Task 1 + Task 5). ✓
- §8 testing: pure unit tests (Tasks 1–3), py_compile for Qt (Tasks 4–6), on-device offscreen + GUI (Task 7). ✓
- Constraint: no changes to emulator_process/cores/interconnect/peripherals; only additive `frameRendered` on brick_widget → Task 4 is the sole existing-file edit. ✓
- Deliberate deviation from spec §3: exit is **Esc only**, Q omitted (collision risk) — noted in Task 6.

**Placeholder scan:** No TBD/TODO; every code step has full code; every run step states expected output. ✓

**Type consistency:** `read_battery`/`BatteryStatus`, `game_name`/`game_group`, `FpsCounter.tick`/`sample`, `controls_legend(config, key_name)`, `BrickWidget.frameRendered`, `InfoPanel.set_game`/`set_fps`, `GameScreen(config, brick_path, settings)`, `HandheldWindow(config, brick_path, settings)` are used identically across tasks and tests. ✓

## Notes for later phases
- Phase 5 adds `LauncherScreen` as `QStackedWidget` index 0 and switches to the GameScreen page on selection — `HandheldWindow` already hosts the stack.
- Phase 3 (input mapping) will make `ControlsPanel` reflect the global uConsole mapping instead of the raw `.brick` hot_keys.
