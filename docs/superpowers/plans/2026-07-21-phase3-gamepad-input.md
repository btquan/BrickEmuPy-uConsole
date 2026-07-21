# Phase 3 — Global Gamepad Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive any game from the uConsole's physical gamepad by reading `/dev/input/js0` (Game Mode), translating events into canonical roles, mapping roles to game buttons via an editable `uconsole.json` profile (with per-`.brick` overrides), and feeding them through the existing button-press path — keyboard input unchanged.

**Architecture:** Pure, PyQt6-free helpers decode joystick events (`js_events.py`) and resolve roles to buttons (`input_map.py` + `uconsole.json`). A `GamepadReader` QThread (`gamepad.py`) reads `js0` and emits role signals; `GameScreen` reference-counts held roles per button and calls new `BrickWidget.pressButton/releaseButton`. `ControlsPanel` shows the gamepad legend.

**Tech Stack:** Python 3, PyQt6 (UI/thread only), pytest.

## Global Constraints

- Do NOT modify `emulator_process.py`, `cores/`, `interconnect.py`, or `peripherals/`. Existing-file edits are limited to `brick_widget.py` (additive press/release methods + key-event refactor), `handheld/game_screen.py`, and `handheld/controls_panel.py`.
- Pure helpers (`handheld/js_events.py`, `handheld/input_map.py`) must NOT import PyQt6. All Qt lives in `gamepad.py`, `game_screen.py`, `controls_panel.py`, `brick_widget.py`.
- Keyboard `hot_keys` input must keep working exactly as before.
- Captured `js0` layout is authoritative: buttons 0-5 = A/B/X/Y/Select/Start; axis 0 = Left(−)/Right(+); axis 1 = Up(−)/Down(+); D-pad values are ±32767, release 0; button value 1=press/0=release.
- The shipped `handheld/uconsole.json` must load equal to `input_map.DEFAULT_PROFILE`.
- Default role mapping: `BTN_START→btnStart`, `BTN_SELECT→btnMute/btnSelect`, `BTN_A→btnRotate`, `BTN_B→btnRotate`, D-pad L/R/Down→`btnLeft/btnRight/btnDown`, `DPAD_UP→btnUp` (separate; no-op on brick games).
- Dev Mac has NO PyQt6 → Qt files verified with `python3 -m py_compile`; their runtime tests + gameplay run on the uConsole. Run pure tests with `/Users/i4cu/.venv/bin/python -m pytest`.

---

### Task 1: Joystick event decoding + role lookup (`handheld/js_events.py`)

**Files:**
- Create: `handheld/js_events.py`
- Test: `tests/test_js_events.py`

**Interfaces:**
- Produces: `EVENT_SIZE = 8`; `parse_js_event(data: bytes) -> (kind, number, value)`
  where kind ∈ {"button","axis","init","unknown"}; `button_role(number, profile)
  -> str|None`; `axis_roles(number, profile) -> (neg_role|None, pos_role|None)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_js_events.py`:

```python
import struct

import pytest

from handheld.js_events import (parse_js_event, button_role, axis_roles,
                                EVENT_SIZE)


def _ev(value, typ, number):
    return struct.pack("IhBB", 0, value, typ, number)


def test_parse_button_press_and_release():
    assert parse_js_event(_ev(1, 0x01, 5)) == ("button", 5, 1)
    assert parse_js_event(_ev(0, 0x01, 0)) == ("button", 0, 0)


def test_parse_axis():
    assert parse_js_event(_ev(-32767, 0x02, 1)) == ("axis", 1, -32767)


def test_init_flag_recognised():
    assert parse_js_event(_ev(1, 0x81, 5)) == ("init", 5, 1)


def test_wrong_size_raises():
    with pytest.raises(ValueError):
        parse_js_event(b"\x00\x00")


def test_role_lookup():
    profile = {"buttons": {"5": "BTN_START"},
               "axes": {"0": {"negative": "DPAD_LEFT", "positive": "DPAD_RIGHT"}}}
    assert button_role(5, profile) == "BTN_START"
    assert button_role(9, profile) is None
    assert axis_roles(0, profile) == ("DPAD_LEFT", "DPAD_RIGHT")
    assert axis_roles(7, profile) == (None, None)
    assert EVENT_SIZE == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_js_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'handheld.js_events'`.

- [ ] **Step 3: Write minimal implementation**

Create `handheld/js_events.py`:

```python
"""Pure decoding of Linux joystick (/dev/input/js0) events. No Qt, no I/O."""
import struct

# struct js_event { __u32 time; __s16 value; __u8 type; __u8 number; }
_FMT = "IhBB"
EVENT_SIZE = 8
_JS_EVENT_BUTTON = 0x01
_JS_EVENT_AXIS = 0x02
_JS_EVENT_INIT = 0x80


def parse_js_event(data):
    if len(data) != EVENT_SIZE:
        raise ValueError("js_event must be %d bytes, got %d"
                         % (EVENT_SIZE, len(data)))
    _time, value, typ, number = struct.unpack(_FMT, data)
    if typ & _JS_EVENT_INIT:
        return ("init", number, value)
    typ &= 0x7F
    if typ == _JS_EVENT_BUTTON:
        return ("button", number, value)
    if typ == _JS_EVENT_AXIS:
        return ("axis", number, value)
    return ("unknown", number, value)


def button_role(number, profile):
    return profile.get("buttons", {}).get(str(number))


def axis_roles(number, profile):
    entry = profile.get("axes", {}).get(str(number), {})
    return (entry.get("negative"), entry.get("positive"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_js_events.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handheld/js_events.py tests/test_js_events.py
git commit -m "feat: pure joystick event decoding and role lookup"
```

---

### Task 2: Axis-to-direction tracking (`AxisTracker` in `handheld/js_events.py`)

**Files:**
- Modify: `handheld/js_events.py` (append `AxisTracker`)
- Test: `tests/test_axis_tracker.py`

**Interfaces:**
- Produces: `AxisTracker(threshold)` with
  `feed(number, value, neg_role, pos_role) -> list[(role, pressed_bool)]` —
  emits press/release transitions as an axis crosses ±threshold, including a
  release+press pair when the direction flips without passing through center.

- [ ] **Step 1: Write the failing test**

Create `tests/test_axis_tracker.py`:

```python
from handheld.js_events import AxisTracker


def test_press_then_release():
    t = AxisTracker(16000)
    assert t.feed(0, -32767, "DPAD_LEFT", "DPAD_RIGHT") == [("DPAD_LEFT", True)]
    assert t.feed(0, 0, "DPAD_LEFT", "DPAD_RIGHT") == [("DPAD_LEFT", False)]


def test_direction_flip_without_center():
    t = AxisTracker(16000)
    t.feed(0, -32767, "DPAD_LEFT", "DPAD_RIGHT")
    assert t.feed(0, 32767, "DPAD_LEFT", "DPAD_RIGHT") == [
        ("DPAD_LEFT", False), ("DPAD_RIGHT", True)]


def test_below_threshold_is_noop():
    t = AxisTracker(16000)
    assert t.feed(0, 5000, "DPAD_LEFT", "DPAD_RIGHT") == []


def test_repeat_same_direction_is_noop():
    t = AxisTracker(16000)
    t.feed(0, -32767, "DPAD_LEFT", "DPAD_RIGHT")
    assert t.feed(0, -30000, "DPAD_LEFT", "DPAD_RIGHT") == []


def test_none_roles_are_safe():
    t = AxisTracker(16000)
    assert t.feed(2, -32767, None, None) == []
    assert t.feed(2, 0, None, None) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_axis_tracker.py -v`
Expected: FAIL — `ImportError: cannot import name 'AxisTracker'`.

- [ ] **Step 3: Write minimal implementation**

Append to `handheld/js_events.py`:

```python
class AxisTracker:
    """Turns raw axis values into role press/release transitions.

    Tracks, per axis, which direction (if any) is currently active, so a value
    stream becomes discrete press/release events. Pure and deterministic.
    """

    def __init__(self, threshold):
        self._threshold = threshold
        self._active = {}   # axis number -> "negative" / "positive" / None

    def feed(self, number, value, neg_role, pos_role):
        if value <= -self._threshold:
            direction = "negative"
        elif value >= self._threshold:
            direction = "positive"
        else:
            direction = None

        prev = self._active.get(number)
        if direction == prev:
            return []
        self._active[number] = direction

        transitions = []
        if prev == "negative" and neg_role:
            transitions.append((neg_role, False))
        elif prev == "positive" and pos_role:
            transitions.append((pos_role, False))
        if direction == "negative" and neg_role:
            transitions.append((neg_role, True))
        elif direction == "positive" and pos_role:
            transitions.append((pos_role, True))
        return transitions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_axis_tracker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handheld/js_events.py tests/test_axis_tracker.py
git commit -m "feat: AxisTracker turns joystick axis values into dpad transitions"
```

---

### Task 3: Profile + role resolution (`handheld/input_map.py`, `handheld/uconsole.json`)

**Files:**
- Create: `handheld/input_map.py`
- Create: `handheld/uconsole.json`
- Test: `tests/test_input_map.py`

**Interfaces:**
- Produces: `DEFAULT_PROFILE` (dict); `load_profile(path=_PROFILE_PATH) -> dict`;
  `resolve_role(role, config, profile) -> str|None`;
  `control_hints(config, profile) -> list[(button_name, [role,...])]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_input_map.py`:

```python
from handheld.input_map import (load_profile, resolve_role, control_hints,
                                DEFAULT_PROFILE)

E23 = {"buttons": {"btnStart": {}, "btnOnOff": {}, "btnMute": {}, "btnLeft": {},
                   "btnDown": {}, "btnRight": {}, "btnRotate": {}}}


def test_resolve_uses_first_existing_candidate():
    assert resolve_role("BTN_START", E23, DEFAULT_PROFILE) == "btnStart"
    assert resolve_role("BTN_SELECT", E23, DEFAULT_PROFILE) == "btnMute"
    assert resolve_role("BTN_A", E23, DEFAULT_PROFILE) == "btnRotate"
    assert resolve_role("DPAD_LEFT", E23, DEFAULT_PROFILE) == "btnLeft"


def test_up_is_unmapped_on_brick():
    assert resolve_role("DPAD_UP", E23, DEFAULT_PROFILE) is None   # no btnUp


def test_no_candidate_returns_none():
    assert resolve_role("BTN_X", E23, DEFAULT_PROFILE) is None


def test_per_game_override_wins():
    cfg = {"buttons": {"btnRotate": {}, "btnOnOff": {}},
           "input_map": {"BTN_B": "btnOnOff"}}
    assert resolve_role("BTN_B", cfg, DEFAULT_PROFILE) == "btnOnOff"


def test_load_profile_missing_returns_default():
    assert load_profile("/nonexistent/uconsole.json") == DEFAULT_PROFILE


def test_shipped_uconsole_json_matches_default():
    assert load_profile() == DEFAULT_PROFILE


def test_control_hints_group_roles_per_button():
    hints = dict(control_hints(E23, DEFAULT_PROFILE))
    assert set(hints["btnRotate"]) == {"BTN_A", "BTN_B"}
    assert hints["btnStart"] == ["BTN_START"]
    assert hints["btnMute"] == ["BTN_SELECT"]
    assert hints["btnLeft"] == ["DPAD_LEFT"]
    assert hints["btnOnOff"] == []           # nothing maps here
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_input_map.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'handheld.input_map'`.

- [ ] **Step 3: Write the implementation**

Create `handheld/input_map.py`:

```python
"""Load the gamepad profile and resolve roles to game buttons. Pure, no Qt."""
import json
import os

_PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "uconsole.json")

DEFAULT_PROFILE = {
    "buttons": {"0": "BTN_A", "1": "BTN_B", "2": "BTN_X", "3": "BTN_Y",
                "4": "BTN_SELECT", "5": "BTN_START"},
    "axes": {"0": {"negative": "DPAD_LEFT", "positive": "DPAD_RIGHT"},
             "1": {"negative": "DPAD_UP", "positive": "DPAD_DOWN"}},
    "axis_threshold": 16000,
    "roles": {
        "DPAD_LEFT": ["btnLeft"], "DPAD_RIGHT": ["btnRight"],
        "DPAD_DOWN": ["btnDown"], "DPAD_UP": ["btnUp"],
        "BTN_A": ["btnRotate"], "BTN_B": ["btnRotate"],
        "BTN_X": [], "BTN_Y": [],
        "BTN_START": ["btnStart"], "BTN_SELECT": ["btnMute", "btnSelect"],
    },
}


def load_profile(path=_PROFILE_PATH):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return DEFAULT_PROFILE


def resolve_role(role, config, profile):
    override = config.get("input_map")
    if override and role in override:
        return override[role]
    buttons = config.get("buttons", {})
    for candidate in profile.get("roles", {}).get(role, []):
        if candidate in buttons:
            return candidate
    return None


def control_hints(config, profile):
    order = list(config.get("buttons", {}))
    hints = {name: [] for name in order}
    roles = list(profile.get("buttons", {}).values())
    for ax in profile.get("axes", {}).values():
        for r in (ax.get("negative"), ax.get("positive")):
            if r:
                roles.append(r)
    for role in roles:
        button = resolve_role(role, config, profile)
        if button in hints:
            hints[button].append(role)
    return [(name, hints[name]) for name in order]
```

Create `handheld/uconsole.json` (must load equal to `DEFAULT_PROFILE`):

```json
{
  "buttons": {
    "0": "BTN_A", "1": "BTN_B", "2": "BTN_X", "3": "BTN_Y",
    "4": "BTN_SELECT", "5": "BTN_START"
  },
  "axes": {
    "0": {"negative": "DPAD_LEFT", "positive": "DPAD_RIGHT"},
    "1": {"negative": "DPAD_UP", "positive": "DPAD_DOWN"}
  },
  "axis_threshold": 16000,
  "roles": {
    "DPAD_LEFT": ["btnLeft"],
    "DPAD_RIGHT": ["btnRight"],
    "DPAD_DOWN": ["btnDown"],
    "DPAD_UP": ["btnUp"],
    "BTN_A": ["btnRotate"],
    "BTN_B": ["btnRotate"],
    "BTN_X": [],
    "BTN_Y": [],
    "BTN_START": ["btnStart"],
    "BTN_SELECT": ["btnMute", "btnSelect"]
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_input_map.py -v`
Expected: PASS (including `test_shipped_uconsole_json_matches_default`).

- [ ] **Step 5: Commit**

```bash
git add handheld/input_map.py handheld/uconsole.json tests/test_input_map.py
git commit -m "feat: gamepad profile loading and role->button resolution"
```

---

### Task 4: `BrickWidget.pressButton`/`releaseButton` + key-event refactor

**Files:**
- Modify: `brick_widget.py`

**Interfaces:**
- Produces: `BrickWidget.pressButton(name)` / `releaseButton(name)` sending
  `CMD_BTN_PRESS` / `CMD_BTN_RELEASE`; used by both key events (refactored) and
  the gamepad path (Task 6).

- [ ] **Step 1: Add the methods**

In `brick_widget.py`, find:
```python
    def setBreakpoint(self, pc, add):
        self._cmdQueue.put((CMD_BREAKPOINT, pc, add))
```
Replace with:
```python
    def setBreakpoint(self, pc, add):
        self._cmdQueue.put((CMD_BREAKPOINT, pc, add))

    def pressButton(self, name):
        self._cmdQueue.put((CMD_BTN_PRESS, name))

    def releaseButton(self, name):
        self._cmdQueue.put((CMD_BTN_RELEASE, name))
```

- [ ] **Step 2: Route key events through the new methods**

In `brick_widget.py`, find:
```python
    def keyPressEvent(self, event):
        if (not event.isAutoRepeat()):
            for name, value in self._config["buttons"].items():
                if (event.key() in value["hot_keys"]):
                    self._cmdQueue.put((CMD_BTN_PRESS, name))

    def keyReleaseEvent(self, event):
        if (not event.isAutoRepeat()):
            for name, value in self._config["buttons"].items():
                if (event.key() in value["hot_keys"]):
                    self._cmdQueue.put((CMD_BTN_RELEASE, name))
```
Replace with:
```python
    def keyPressEvent(self, event):
        if (not event.isAutoRepeat()):
            for name, value in self._config["buttons"].items():
                if (event.key() in value["hot_keys"]):
                    self.pressButton(name)

    def keyReleaseEvent(self, event):
        if (not event.isAutoRepeat()):
            for name, value in self._config["buttons"].items():
                if (event.key() in value["hot_keys"]):
                    self.releaseButton(name)
```

- [ ] **Step 3: Byte-compile and run the suite**

Run: `python3 -m py_compile brick_widget.py`
Expected: exit 0, no output.

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/ -q`
Expected: all pure tests pass (no behaviour change; no test imports brick_widget).

- [ ] **Step 4: Commit**

```bash
git add brick_widget.py
git commit -m "feat: BrickWidget.pressButton/releaseButton (used by keys and gamepad)"
```

---

### Task 5: Gamepad reader thread (`handheld/gamepad.py`)

**Files:**
- Create: `handheld/gamepad.py`
- Test: `tests/test_gamepad.py` (needs PyQt6 → runs on-device in Task 7)

**Interfaces:**
- Produces: `GamepadReader(profile, device="/dev/input/js0", parent=None)`
  (QThread) with signals `rolePressed(str)`, `roleReleased(str)`; `stop()`.
  `_handle(frame: bytes)` decodes one event and emits the resulting role(s).

- [ ] **Step 1: Write the implementation**

Create `handheld/gamepad.py`:

```python
"""Reads /dev/input/js0 on a background thread and emits role transitions."""
import os
import select

from PyQt6.QtCore import QThread, pyqtSignal

from handheld.js_events import (parse_js_event, button_role, axis_roles,
                                AxisTracker, EVENT_SIZE)

JS_DEVICE = "/dev/input/js0"


class GamepadReader(QThread):
    rolePressed = pyqtSignal(str)
    roleReleased = pyqtSignal(str)

    def __init__(self, profile, device=JS_DEVICE, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._device = device
        self._running = True
        self._axes = AxisTracker(profile.get("axis_threshold", 16000))

    def run(self):
        try:
            fd = os.open(self._device, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return          # no gamepad (dev machine / Game Mode off)
        try:
            buf = b""
            while self._running:
                r, _, _ = select.select([fd], [], [], 0.2)
                if not r:
                    continue
                try:
                    chunk = os.read(fd, EVENT_SIZE * 32)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= EVENT_SIZE:
                    frame, buf = buf[:EVENT_SIZE], buf[EVENT_SIZE:]
                    self._handle(frame)
        finally:
            os.close(fd)

    def _handle(self, frame):
        kind, number, value = parse_js_event(frame)
        if kind == "button":
            role = button_role(number, self._profile)
            if role:
                (self.rolePressed if value else self.roleReleased).emit(role)
        elif kind == "axis":
            neg, pos = axis_roles(number, self._profile)
            for role, pressed in self._axes.feed(number, value, neg, pos):
                (self.rolePressed if pressed else self.roleReleased).emit(role)

    def stop(self):
        self._running = False
        self.wait()
```

- [ ] **Step 2: Write the on-device test**

Create `tests/test_gamepad.py`:

```python
import struct
import sys

from PyQt6 import QtWidgets

from handheld.gamepad import GamepadReader
from handheld.input_map import DEFAULT_PROFILE


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _ev(value, typ, number):
    return struct.pack("IhBB", 0, value, typ, number)


def test_button_role_emitted():
    _app()
    r = GamepadReader(DEFAULT_PROFILE)
    pressed, released = [], []
    r.rolePressed.connect(pressed.append)
    r.roleReleased.connect(released.append)
    r._handle(_ev(1, 0x01, 5))   # button 5 -> BTN_START press
    r._handle(_ev(0, 0x01, 5))
    assert pressed == ["BTN_START"]
    assert released == ["BTN_START"]


def test_axis_dpad_emitted():
    _app()
    r = GamepadReader(DEFAULT_PROFILE)
    pressed, released = [], []
    r.rolePressed.connect(pressed.append)
    r.roleReleased.connect(released.append)
    r._handle(_ev(-32767, 0x02, 0))   # axis 0 neg -> DPAD_LEFT
    r._handle(_ev(0, 0x02, 0))
    assert pressed == ["DPAD_LEFT"]
    assert released == ["DPAD_LEFT"]


def test_absent_device_does_not_crash():
    _app()
    r = GamepadReader(DEFAULT_PROFILE, device="/nonexistent/js0")
    r.run()          # opens, fails, returns cleanly
```

- [ ] **Step 3: Byte-compile (Mac cannot import PyQt6)**

Run: `python3 -m py_compile handheld/gamepad.py tests/test_gamepad.py`
Expected: exit 0, no output. (Runtime test executes on-device in Task 7.)

- [ ] **Step 4: Commit**

```bash
git add handheld/gamepad.py tests/test_gamepad.py
git commit -m "feat: GamepadReader thread reading js0 into role signals"
```

---

### Task 6: Wire gamepad into GameScreen + gamepad ControlsPanel legend

**Files:**
- Modify: `handheld/game_screen.py`
- Modify: `handheld/controls_panel.py`

**Interfaces:**
- Consumes: `GamepadReader`, `load_profile`, `resolve_role`, `control_hints`.
- Produces: gamepad input driving the game with per-button reference counting;
  `ControlsPanel(config, profile)` showing the gamepad legend.

- [ ] **Step 1: Rewrite `controls_panel.py` for the gamepad legend**

Replace the whole body of `handheld/controls_panel.py` with:
```python
from PyQt6 import QtWidgets

from handheld.input_map import control_hints

_ROLE_SYMBOL = {
    "DPAD_LEFT": "◄", "DPAD_RIGHT": "►",
    "DPAD_UP": "▲", "DPAD_DOWN": "▼",
    "BTN_A": "A", "BTN_B": "B", "BTN_X": "X", "BTN_Y": "Y",
    "BTN_START": "Start", "BTN_SELECT": "Select",
}


class ControlsPanel(QtWidgets.QWidget):
    def __init__(self, config, profile, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        for name, roles in control_hints(config, profile):
            if not roles:
                continue
            symbols = " ".join(_ROLE_SYMBOL.get(r, r) for r in roles)
            label = QtWidgets.QLabel(
                "%s: %s" % (name.removeprefix("btn") or name, symbols))
            label.setObjectName("controlLabel")
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addStretch(1)
```

- [ ] **Step 2: Wire the gamepad in `game_screen.py`**

In `handheld/game_screen.py`, update the imports. Find:
```python
from brick_widget import BrickWidget
from handheld.info_panel import InfoPanel
from handheld.controls_panel import ControlsPanel
from handheld.fps_counter import FpsCounter
from handheld.metadata import game_name, game_group
```
Replace with:
```python
from brick_widget import BrickWidget
from handheld.info_panel import InfoPanel
from handheld.controls_panel import ControlsPanel
from handheld.fps_counter import FpsCounter
from handheld.metadata import game_name, game_group
from handheld.gamepad import GamepadReader
from handheld.input_map import load_profile, resolve_role
```

- [ ] **Step 3: Construct the reader and pass the profile to ControlsPanel**

In `handheld/game_screen.py`, find:
```python
        self._info = InfoPanel()
        self._brick = BrickWidget(config, settings)
        self._controls = ControlsPanel(config)
```
Replace with:
```python
        self._config = config
        self._profile = load_profile()
        self._heldRoles = {}          # game button name -> set of roles holding it

        self._info = InfoPanel()
        self._brick = BrickWidget(config, settings)
        self._controls = ControlsPanel(config, self._profile)
```

Then, in `handheld/game_screen.py`, find (near the end of `__init__`):
```python
        self._brick.setFocus()
```
Replace with:
```python
        self._gamepad = GamepadReader(self._profile)
        self._gamepad.rolePressed.connect(self._onRolePressed)
        self._gamepad.roleReleased.connect(self._onRoleReleased)
        self._gamepad.start()

        self._brick.setFocus()
```

- [ ] **Step 4: Add the role handlers and stop the reader on close**

In `handheld/game_screen.py`, find:
```python
    def _sampleFps(self):
        self._info.set_fps(self._fps.sample(time.monotonic()))
```
Replace with:
```python
    def _sampleFps(self):
        self._info.set_fps(self._fps.sample(time.monotonic()))

    def _onRolePressed(self, role):
        button = resolve_role(role, self._config, self._profile)
        if button is None:
            return
        held = self._heldRoles.setdefault(button, set())
        was_empty = not held
        held.add(role)
        if was_empty:
            self._brick.pressButton(button)

    def _onRoleReleased(self, role):
        button = resolve_role(role, self._config, self._profile)
        if button is None:
            return
        held = self._heldRoles.get(button)
        if not held or role not in held:
            return
        held.discard(role)
        if not held:
            self._brick.releaseButton(button)
```

In `handheld/game_screen.py`, find:
```python
    def close(self):
        self._fpsTimer.stop()
        self._brick.close()
        return super().close()
```
Replace with:
```python
    def close(self):
        self._gamepad.stop()
        self._fpsTimer.stop()
        self._brick.close()
        return super().close()
```

- [ ] **Step 5: Byte-compile both files**

Run: `python3 -m py_compile handheld/game_screen.py handheld/controls_panel.py`
Expected: exit 0, no output. (Runtime verified on-device in Task 7.)

- [ ] **Step 6: Commit**

```bash
git add handheld/game_screen.py handheld/controls_panel.py
git commit -m "feat: gamepad input wired into GameScreen with a gamepad legend"
```

---

### Task 7: On-device acceptance (uConsole)

**Files:** None (verification; no repo changes unless a defect is found).

**Interfaces:** Consumes Tasks 1–6, plus PyQt6 on the uConsole and a joystick at
`/dev/input/js0` in Game Mode.

- [ ] **Step 1: Get the branch on the device and ensure pytest is available**

On the uConsole:
`cd ~/Projects/BrickEmuPy && git fetch fork phase3-gamepad-input && git checkout phase3-gamepad-input`
Ensure a test runner: `python3 -m pytest --version` or install once with
`python3 -m pip install --user --break-system-packages pytest`.

- [ ] **Step 2: Run the full test suite on-device (pure + Qt)**

Run: `python3 -m pytest tests/ -q` (offscreen not needed for these).
Expected: all pass, including `tests/test_gamepad.py` (which needs PyQt6, present
on the device): button 5 → BTN_START, axis 0 neg → DPAD_LEFT, absent-device path
returns cleanly.

- [ ] **Step 3: Gameplay acceptance in Game Mode**

Enable Game Mode (Fn+G), then run:
`python3 main_handheld.py -brick assets/E23PlusMarkII96in1.brick`
Expected: D-pad moves the piece (Left/Right/Down), **A** and **B** rotate,
**Start** starts, **Select** mutes, **Up does nothing** (no `btnUp`). Holding A
then B then releasing A keeps rotate held until B is also released
(reference-count). ControlsPanel shows the gamepad legend
(`Rotate: A B`, `Start: Start`, `Mute: Select`, `Left: ◄`, `Right: ►`,
`Down: ▼`). `pgrep -af pypy3` shows the child; Esc exits with no leftover pypy.

- [ ] **Step 4: Keyboard fallback still works**

Turn Game Mode off; confirm the game still responds to the keyboard `hot_keys`
(A/S/D/arrows/Space etc.) — the gamepad path being idle must not break keyboard
input.

- [ ] **Step 5: Record the result**

Note in the ledger: suite result on-device, gameplay observations, any stderr
noise. No commit needed unless a defect fix was required in Tasks 1–6.

---

## Self-Review

**Spec coverage:**
- §2 captured js0 layout → Task 1 (parse) + Task 3 (`uconsole.json` buttons/axes). ✓
- §5 `uconsole.json` profile → Task 3 (file + `DEFAULT_PROFILE`, equality test). ✓
- §6 resolution (override > candidates > none) → Task 3 `resolve_role` + tests. ✓
- §7 `js_events` (parse, AxisTracker, role lookup) → Tasks 1–2. ✓
- §7 `input_map` (load/resolve/control_hints) → Task 3. ✓
- §7 `gamepad.GamepadReader` (js0, select-timeout stop, absence no-op) → Task 5. ✓
- §8 `brick_widget` press/release + key refactor → Task 4. ✓
- §8 `game_screen` wiring + reference counting → Task 6 (Steps 3–4). ✓
- §8 `controls_panel` gamepad legend + role symbols → Task 6 (Step 1). ✓
- §10 edge cases: absent device (Task 5 run), None role (Task 6 handlers return),
  reference counting (Task 6 held-role sets), missing profile (Task 3). ✓
- §11 testing split (pure on Mac, Qt on-device) → Tasks 1–3 pytest, Tasks 4–6
  py_compile, Task 7 on-device suite + gameplay. ✓
- Constraint: no emulator/core edits; keyboard unchanged (Task 4 keeps hot_keys
  behaviour, only routes through new methods). ✓

**Placeholder scan:** No TBD/TODO; every code step has full code; every run step
states expected output. ✓

**Type consistency:** `parse_js_event`/`button_role`/`axis_roles`/`AxisTracker.feed`/
`EVENT_SIZE`, `load_profile`/`resolve_role`/`control_hints`/`DEFAULT_PROFILE`,
`GamepadReader(profile, device)`/`rolePressed`/`roleReleased`/`_handle`/`stop`,
`BrickWidget.pressButton`/`releaseButton`, `ControlsPanel(config, profile)` are
used identically across tasks and tests. Reference-count structure `_heldRoles`
(button → set of roles) is consistent between Steps 3 and 4 of Task 6. ✓

## Notes for later phases
- Phase 4/5 reuse `load_profile`/`resolve_role`; the launcher (Phase 5) can bind
  D-pad + A/Start to menu navigation via the same roles.
- L/R shoulder buttons and X/Y are currently unmapped (empty candidate lists) —
  add candidates to `uconsole.json` when a game needs them.
