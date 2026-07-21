# Phase 5 — Grid Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Boot into a console-style grid launcher (grouped rows: Brick / Virtual Pet / Other) of ROM-present games with machine-face thumbnails; navigate with D-pad/keyboard, launch with A, return from a game with Y.

**Architecture:** Pure helpers (`game_catalog`, `launcher_selection`) hold scanning/navigation logic (TDD on dev Mac). `LauncherScreen` (Qt) renders the grid. `HandheldWindow` now owns the single `GamepadReader` and routes roles to the active screen (launcher or game), creating/tearing down `GameScreen` on launch/back. `GameScreen` loses its own reader and gains `handleRolePressed/Released` + `teardown()`.

**Tech Stack:** Python 3, PyQt6 (UI/thread only), pytest.

## Global Constraints

- Do NOT modify `emulator_process.py`, `cores/`, `interconnect.py`, or `peripherals/`. Existing-file edits are limited to `handheld/game_screen.py`, `handheld/info_panel.py`, `handheld/window.py`, `main_handheld.py`.
- Pure helpers (`handheld/game_catalog.py`, `handheld/launcher_selection.py`) must NOT import PyQt6. All Qt stays in `launcher_screen.py`, `window.py`, `game_screen.py`, `info_panel.py`, `main_handheld.py`.
- Reuse existing code: `handheld.metadata.game_name/game_group`, `handheld.gamepad.GamepadReader`, `handheld.input_map.load_profile/resolve_role`, and the Phase-3 reference-count logic in `GameScreen`.
- Keyboard input must keep working (game: BrickWidget; launcher: LauncherScreen).
- Back-to-launcher control is **BTN_Y** (and Esc); Esc in the launcher quits the app.
- Dev Mac has NO PyQt6 → Qt files verified with `python3 -m py_compile`; runtime on the uConsole. Run pure tests with `/Users/i4cu/.venv/bin/python -m pytest`.

---

### Task 1: Game catalog (`handheld/game_catalog.py`)

**Files:**
- Create: `handheld/game_catalog.py`
- Test: `tests/test_game_catalog.py`

**Interfaces:**
- Produces: `GameEntry` dataclass `{name, group, brick_path, svg_path}`;
  `scan_catalog(assets_dir) -> list[GameEntry]` (only ROM-present games);
  `group_catalog(entries) -> list[(group_name, [entries])]` in Brick / Virtual
  Pet / Other order, each group's entries sorted by name.

- [ ] **Step 1: Write the failing test**

Create `tests/test_game_catalog.py`:

```python
import json
import os

from handheld.game_catalog import scan_catalog, group_catalog, GameEntry


def _game(assets, stem, core, with_rom=True, name=None, category=None):
    cfg = {"core": core, "face_path": "./assets/%s.svg" % stem,
           "mask_options": {"rom_path": "./assets/%s.bin" % stem}}
    if name:
        cfg["name"] = name
    if category:
        cfg["category"] = category
    (assets / (stem + ".brick")).write_text(json.dumps(cfg))
    (assets / (stem + ".svg")).write_text("<svg/>")
    if with_rom:
        (assets / (stem + ".bin")).write_bytes(b"\x00")


def test_scan_keeps_only_rom_present(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    _game(assets, "E23", "HT943", with_rom=True)
    _game(assets, "Tama", "E0C6200", with_rom=False)   # no .bin -> skipped
    entries = scan_catalog(str(assets))
    stems = sorted(os.path.basename(e.brick_path) for e in entries)
    assert stems == ["E23.brick"]
    e = entries[0]
    assert e.name == "E23" and e.group == "Brick"
    assert e.svg_path.endswith("E23.svg")


def test_scan_skips_malformed_brick(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "bad.brick").write_text("{ not json")
    _game(assets, "E88", "HT943")
    entries = scan_catalog(str(assets))
    assert [e.name for e in entries] == ["E88"]


def test_group_order_and_sort(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    _game(assets, "zzz", "HT943", name="Zzz Brick")
    _game(assets, "aaa", "HT943", name="Aaa Brick")
    _game(assets, "pet", "E0C6200", name="Pet One")
    _game(assets, "misc", "T6770S", name="Misc One")
    grouped = group_catalog(scan_catalog(str(assets)))
    names = [g[0] for g in grouped]
    assert names == ["Brick", "Virtual Pet", "Other"]
    brick_names = [e.name for e in dict(grouped)["Brick"]]
    assert brick_names == ["Aaa Brick", "Zzz Brick"]   # sorted by name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_game_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'handheld.game_catalog'`.

- [ ] **Step 3: Write minimal implementation**

Create `handheld/game_catalog.py`:

```python
"""Scan the assets directory for playable games. Pure, PyQt6-free."""
import os
import json
from dataclasses import dataclass

from handheld.metadata import game_name, game_group

_GROUP_ORDER = ["Brick", "Virtual Pet", "Other"]


@dataclass
class GameEntry:
    name: str
    group: str
    brick_path: str
    svg_path: str


def _asset(assets_dir, ref):
    # A .brick path like "./assets/Foo.bin" -> that file inside assets_dir.
    return os.path.join(assets_dir, os.path.basename(ref)) if ref else ""


def _rom_present(config, assets_dir):
    rp = config.get("mask_options", {}).get("rom_path")
    return bool(rp) and os.path.exists(_asset(assets_dir, rp))


def scan_catalog(assets_dir):
    entries = []
    for fname in sorted(os.listdir(assets_dir)):
        if not fname.endswith(".brick"):
            continue
        brick_path = os.path.join(assets_dir, fname)
        try:
            with open(brick_path) as f:
                config = json.load(f)
        except (OSError, ValueError):
            continue
        if not _rom_present(config, assets_dir):
            continue
        entries.append(GameEntry(
            name=game_name(config, brick_path),
            group=game_group(config),
            brick_path=brick_path,
            svg_path=_asset(assets_dir, config.get("face_path", "")),
        ))
    return entries


def group_catalog(entries):
    buckets = {}
    for e in entries:
        buckets.setdefault(e.group, []).append(e)
    result = []
    seen = set()
    for name in _GROUP_ORDER:
        if buckets.get(name):
            result.append((name, sorted(buckets[name], key=lambda x: x.name)))
            seen.add(name)
    for name in sorted(buckets):
        if name not in seen and buckets[name]:
            result.append((name, sorted(buckets[name], key=lambda x: x.name)))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_game_catalog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handheld/game_catalog.py tests/test_game_catalog.py
git commit -m "feat: pure game catalog (scan ROM-present games, group + sort)"
```

---

### Task 2: Launcher selection model (`handheld/launcher_selection.py`)

**Files:**
- Create: `handheld/launcher_selection.py`
- Test: `tests/test_launcher_selection.py`

**Interfaces:**
- Produces: `LEFT/RIGHT/UP/DOWN` constants; `LauncherSelection(groups)` with
  `move(direction)` (clamped), `selected() -> entry|None`, `position() ->
  (group_index, item_index)`. `groups` is `list[(name, [entries])]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_launcher_selection.py`:

```python
from handheld.launcher_selection import (LauncherSelection,
                                         LEFT, RIGHT, UP, DOWN)

# groups: (name, [items]); items are plain strings here for simplicity
GROUPS = [
    ("Brick", ["a", "b", "c"]),
    ("Pet", ["p", "q"]),
    ("Other", ["x"]),
]


def test_starts_top_left():
    s = LauncherSelection(GROUPS)
    assert s.position() == (0, 0)
    assert s.selected() == "a"


def test_right_and_left_clamp():
    s = LauncherSelection(GROUPS)
    s.move(RIGHT); s.move(RIGHT); s.move(RIGHT)     # clamp at last (index 2)
    assert s.position() == (0, 2)
    s.move(LEFT); s.move(LEFT); s.move(LEFT)         # clamp at 0
    assert s.position() == (0, 0)


def test_down_changes_group_and_clamps_column():
    s = LauncherSelection(GROUPS)
    s.move(RIGHT); s.move(RIGHT)                      # (0, 2)
    s.move(DOWN)                                      # Pet has 2 -> clamp to 1
    assert s.position() == (1, 1)
    assert s.selected() == "q"
    s.move(DOWN)                                      # Other has 1 -> clamp to 0
    assert s.position() == (2, 0)


def test_up_clamps_at_top():
    s = LauncherSelection(GROUPS)
    s.move(UP)
    assert s.position() == (0, 0)


def test_empty_groups_safe():
    s = LauncherSelection([])
    assert s.selected() is None
    s.move(RIGHT)     # no crash
    assert s.selected() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_launcher_selection.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `handheld/launcher_selection.py`:

```python
"""Pure gamepad/keyboard selection model for the launcher grid. No Qt."""

LEFT, RIGHT, UP, DOWN = "LEFT", "RIGHT", "UP", "DOWN"


class LauncherSelection:
    def __init__(self, groups):
        self._groups = [g for g in groups if g[1]]   # drop empty groups
        self._g = 0
        self._i = 0

    def move(self, direction):
        if not self._groups:
            return
        row = self._groups[self._g][1]
        if direction == LEFT:
            self._i = max(0, self._i - 1)
        elif direction == RIGHT:
            self._i = min(len(row) - 1, self._i + 1)
        elif direction == UP:
            self._g = max(0, self._g - 1)
            self._i = min(self._i, len(self._groups[self._g][1]) - 1)
        elif direction == DOWN:
            self._g = min(len(self._groups) - 1, self._g + 1)
            self._i = min(self._i, len(self._groups[self._g][1]) - 1)

    def selected(self):
        if not self._groups:
            return None
        return self._groups[self._g][1][self._i]

    def position(self):
        return (self._g, self._i)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/test_launcher_selection.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handheld/launcher_selection.py tests/test_launcher_selection.py
git commit -m "feat: pure launcher grid selection model (clamped navigation)"
```

---

### Task 3: `GameScreen`/`InfoPanel` refactor (remove own reader; add handleRole* + teardown)

**Files:**
- Modify: `handheld/game_screen.py`
- Modify: `handheld/info_panel.py`

**Interfaces:**
- Produces: `GameScreen.handleRolePressed(role)` / `handleRoleReleased(role)`
  (public; the former private `_onRole*`) and `GameScreen.teardown()`;
  `InfoPanel.teardown()` (stops the battery timer). `GameScreen` no longer
  constructs a `GamepadReader` (the window owns it now).

- [ ] **Step 1: Drop the GamepadReader import**

In `handheld/game_screen.py`, find:
```python
from handheld.gamepad import GamepadReader
from handheld.input_map import load_profile, resolve_role
```
Replace with:
```python
from handheld.input_map import load_profile, resolve_role
```

- [ ] **Step 2: Remove the reader construction, keep focus**

In `handheld/game_screen.py`, find:
```python
        self._gamepad = GamepadReader(self._profile)
        self._gamepad.rolePressed.connect(self._onRolePressed)
        self._gamepad.roleReleased.connect(self._onRoleReleased)
        self._gamepad.start()

        self._brick.setFocus()
```
Replace with:
```python
        self._brick.setFocus()
```

- [ ] **Step 3: Make the role handlers public**

In `handheld/game_screen.py`, find:
```python
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
Replace with:
```python
    def handleRolePressed(self, role):
        button = resolve_role(role, self._config, self._profile)
        if button is None:
            return
        held = self._heldRoles.setdefault(button, set())
        was_empty = not held
        held.add(role)
        if was_empty:
            self._brick.pressButton(button)

    def handleRoleReleased(self, role):
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

- [ ] **Step 4: Replace close() with teardown() + close()**

In `handheld/game_screen.py`, find:
```python
    def close(self):
        self._gamepad.stop()
        self._fpsTimer.stop()
        self._brick.close()
        return super().close()
```
Replace with:
```python
    def teardown(self):
        self._fpsTimer.stop()
        self._info.teardown()
        self._brick.close()

    def close(self):
        self.teardown()
        return super().close()
```

- [ ] **Step 5: Add `InfoPanel.teardown()`**

In `handheld/info_panel.py`, find:
```python
    def set_game(self, name, group):
        self._name.setText(name)
        self._group.setText(group)
```
Replace with:
```python
    def teardown(self):
        self._batteryTimer.stop()

    def set_game(self, name, group):
        self._name.setText(name)
        self._group.setText(group)
```

- [ ] **Step 6: Byte-compile and run the pure suite**

Run: `python3 -m py_compile handheld/game_screen.py handheld/info_panel.py`
Expected: exit 0, no output.

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/ --ignore=tests/test_gamepad.py -q`
Expected: all pure tests pass (no test imports these Qt modules).

Grep-confirm: `handleRolePressed`/`handleRoleReleased`/`teardown` present in
game_screen.py; no `GamepadReader` reference remains in game_screen.py.

- [ ] **Step 7: Commit**

```bash
git add handheld/game_screen.py handheld/info_panel.py
git commit -m "refactor: GameScreen exposes handleRole*/teardown; InfoPanel.teardown"
```

---

### Task 4: Launcher screen (`handheld/launcher_screen.py`)

**Files:**
- Create: `handheld/launcher_screen.py`

**Interfaces:**
- Produces: `LauncherScreen(groups, parent=None)` (QWidget) with signal
  `gameSelected(str)` (brick_path); `handleRolePressed(role)` /
  `handleRoleReleased(role)`; keyboard navigation. `groups` is the
  `group_catalog` output `list[(name, [GameEntry])]`.

**Note:** No PyQt6 on the dev Mac → verified with `py_compile`; runtime/visual
verified on-device in Task 6.

- [ ] **Step 1: Write the implementation**

Create `handheld/launcher_screen.py`:

```python
from PyQt6 import QtWidgets, QtCore, QtGui, QtSvg

from handheld.launcher_selection import LauncherSelection, LEFT, RIGHT, UP, DOWN

_THUMB_HEIGHT = 110
_ROLE_DIR = {"DPAD_LEFT": LEFT, "DPAD_RIGHT": RIGHT,
             "DPAD_UP": UP, "DPAD_DOWN": DOWN}
_KEY_DIR = {
    QtCore.Qt.Key.Key_Left: LEFT, QtCore.Qt.Key.Key_Right: RIGHT,
    QtCore.Qt.Key.Key_Up: UP, QtCore.Qt.Key.Key_Down: DOWN,
}


def _render_thumbnail(svg_path, height):
    renderer = QtSvg.QSvgRenderer(svg_path)
    if not renderer.isValid():
        pix = QtGui.QPixmap(int(height * 0.6), height)
        pix.fill(QtCore.Qt.GlobalColor.darkGray)
        return pix
    bounds = renderer.boundsOnElement("body")
    if bounds.isEmpty():
        bounds = renderer.viewBoxF()
    aspect = bounds.width() / bounds.height() if bounds.height() else 0.6
    width = max(1, int(height * aspect))
    pix = QtGui.QPixmap(width, height)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pix)
    renderer.render(painter, "body", QtCore.QRectF(0, 0, width, height))
    painter.end()
    return pix


def _make_tile(entry):
    tile = QtWidgets.QWidget()
    tile.setObjectName("launcherTile")
    v = QtWidgets.QVBoxLayout(tile)
    v.setContentsMargins(6, 6, 6, 6)
    thumb = QtWidgets.QLabel()
    thumb.setPixmap(_render_thumbnail(entry.svg_path, _THUMB_HEIGHT))
    thumb.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    name = QtWidgets.QLabel(entry.name)
    name.setObjectName("launcherName")
    name.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    v.addWidget(thumb)
    v.addWidget(name)
    return tile


class LauncherScreen(QtWidgets.QWidget):
    gameSelected = QtCore.pyqtSignal(str)

    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            'QWidget#launcherTile[selected="true"] '
            '{ border: 3px solid palette(highlight); border-radius: 6px; }')
        self._groups = [(name, items) for name, items in groups if items]
        self._selection = LauncherSelection(self._groups)
        self._tiles = {}      # (g, i) -> tile widget
        self._rows = []       # per group -> QScrollArea

        outer = QtWidgets.QVBoxLayout(self)
        if not self._groups:
            outer.addWidget(QtWidgets.QLabel("No games with ROMs found."))
            outer.addStretch(1)
            return

        for g, (gname, items) in enumerate(self._groups):
            label = QtWidgets.QLabel(gname)
            label.setObjectName("launcherGroup")
            outer.addWidget(label)

            row_area = QtWidgets.QScrollArea()
            row_area.setWidgetResizable(True)
            row_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            row_area.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            row_area.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            row = QtWidgets.QWidget()
            hbox = QtWidgets.QHBoxLayout(row)
            hbox.setContentsMargins(0, 0, 0, 0)
            for i, entry in enumerate(items):
                tile = _make_tile(entry)
                self._tiles[(g, i)] = tile
                hbox.addWidget(tile)
            hbox.addStretch(1)
            row_area.setWidget(row)
            self._rows.append(row_area)
            outer.addWidget(row_area)
        outer.addStretch(1)
        self._refresh()

    def _refresh(self):
        g, i = self._selection.position()
        for (tg, ti), tile in self._tiles.items():
            tile.setProperty("selected", tg == g and ti == i)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
        sel = self._tiles.get((g, i))
        if sel is not None and 0 <= g < len(self._rows):
            self._rows[g].ensureWidgetVisible(sel)

    def handleRolePressed(self, role):
        if role in _ROLE_DIR:
            self._selection.move(_ROLE_DIR[role])
            self._refresh()
        elif role == "BTN_A":
            self._launch()

    def handleRoleReleased(self, role):
        pass

    def keyPressEvent(self, event):
        key = event.key()
        if key in _KEY_DIR:
            self._selection.move(_KEY_DIR[key])
            self._refresh()
        elif key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self._launch()
        else:
            super().keyPressEvent(event)

    def _launch(self):
        entry = self._selection.selected()
        if entry is not None:
            self.gameSelected.emit(entry.brick_path)
```

- [ ] **Step 2: Byte-compile**

Run: `python3 -m py_compile handheld/launcher_screen.py`
Expected: exit 0, no output. (Runtime/visual verified on-device in Task 6.)

- [ ] **Step 3: Commit**

```bash
git add handheld/launcher_screen.py
git commit -m "feat: LauncherScreen grid (grouped rows, thumbnails, nav, gameSelected)"
```

---

### Task 5: `HandheldWindow` + `main_handheld.py` (own reader, route, launch/back)

**Files:**
- Modify: `handheld/window.py` (rewrite)
- Modify: `main_handheld.py` (rewrite)

**Interfaces:**
- Produces: `HandheldWindow(groups, settings, initial_brick=None)` — hosts the
  launcher + games, owns the `GamepadReader`, routes roles (BTN_Y in-game →
  back; else → active screen), creates/tears down `GameScreen` on launch/back.
  `main_handheld.py` builds the catalog and boots the launcher (or a game if
  `-brick` is given).

- [ ] **Step 1: Rewrite `handheld/window.py`**

Replace the whole file `handheld/window.py` with:
```python
import sys
import json

from PyQt6 import QtWidgets, QtCore
from PyQt6.QtGui import QShortcut

from handheld.game_screen import GameScreen
from handheld.launcher_screen import LauncherScreen
from handheld.gamepad import GamepadReader
from handheld.input_map import load_profile


class HandheldWindow(QtWidgets.QMainWindow):
    def __init__(self, groups, settings, initial_brick=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._profile = load_profile()
        self._game = None

        self._stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self._stack)

        self._launcher = LauncherScreen(groups)
        self._launcher.gameSelected.connect(self._launchGame)
        self._stack.addWidget(self._launcher)
        self._stack.setCurrentWidget(self._launcher)
        self._launcher.setFocus()

        self._gamepad = GamepadReader(self._profile)
        self._gamepad.rolePressed.connect(self._onRolePressed)
        self._gamepad.roleReleased.connect(self._onRoleReleased)
        self._gamepad.start()

        QShortcut(QtCore.Qt.Key.Key_Escape, self).activated.connect(self._onEscape)

        if initial_brick:
            self._launchGame(initial_brick)

    def _active(self):
        return self._stack.currentWidget()

    def _onRolePressed(self, role):
        active = self._active()
        if active is self._game and role == "BTN_Y":
            self._backToLauncher()
            return
        if hasattr(active, "handleRolePressed"):
            active.handleRolePressed(role)

    def _onRoleReleased(self, role):
        active = self._active()
        if hasattr(active, "handleRoleReleased"):
            active.handleRoleReleased(role)

    def _launchGame(self, brick_path):
        if self._game is not None:
            return
        try:
            with open(brick_path) as f:
                config = json.load(f)
        except (OSError, ValueError) as e:
            print("Cannot open %s: %s" % (brick_path, e), file=sys.stderr)
            return
        self._game = GameScreen(config, brick_path, self._settings)
        self._stack.addWidget(self._game)
        self._stack.setCurrentWidget(self._game)
        self._game.setFocus()

    def _backToLauncher(self):
        if self._game is None:
            return
        game = self._game
        self._game = None
        self._stack.setCurrentWidget(self._launcher)
        self._stack.removeWidget(game)
        game.teardown()
        game.deleteLater()
        self._launcher.setFocus()

    def _onEscape(self):
        if self._game is not None:
            self._backToLauncher()
        else:
            self.close()

    def closeEvent(self, event):
        self._gamepad.stop()
        if self._game is not None:
            self._game.teardown()
        super().closeEvent(event)
```

- [ ] **Step 2: Rewrite `main_handheld.py`**

Replace the whole file `main_handheld.py` with:
```python
import sys
import argparse

from PyQt6 import QtWidgets, QtCore

from handheld.window import HandheldWindow
from handheld.game_catalog import scan_catalog, group_catalog

ASSETS_DIR = "assets"


def main():
    parser = argparse.ArgumentParser(description="BrickEmuPy handheld shell.")
    parser.add_argument("-brick", required=False,
                        help="Boot straight into this Brick Game config (*.brick)")
    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)
    try:
        with open("ui/style.css") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        pass

    settings = QtCore.QSettings("azya", "BrickEmuPy")
    groups = group_catalog(scan_catalog(ASSETS_DIR))
    window = HandheldWindow(groups, settings, initial_brick=args.brick)
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Byte-compile + pure suite**

Run: `python3 -m py_compile handheld/window.py main_handheld.py`
Expected: exit 0, no output.

Run: `/Users/i4cu/.venv/bin/python -m pytest tests/ --ignore=tests/test_gamepad.py -q`
Expected: all pure tests still pass.

- [ ] **Step 4: Commit**

```bash
git add handheld/window.py main_handheld.py
git commit -m "feat: boot into launcher; window owns gamepad, routes roles, launch/back"
```

---

### Task 6: On-device acceptance (uConsole)

**Files:** None (verification; no repo changes unless a defect is found).

**Interfaces:** Consumes Tasks 1–5, plus PyQt6 on the uConsole and js0 in Game Mode.

- [ ] **Step 1: Get the branch on the device and run the suite**

On the uConsole:
`cd ~/Projects/BrickEmuPy && git fetch fork phase5-launcher && git checkout phase5-launcher`
Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests/ -q`
Expected: all pass (pure + test_gamepad under PyQt6).

- [ ] **Step 2: Offscreen construction smoke**

On the uConsole, from the repo dir:
```bash
QT_QPA_PLATFORM=offscreen python3 -c "
import sys
from PyQt6 import QtWidgets
from PyQt6.QtCore import QSettings
from handheld.window import HandheldWindow
from handheld.game_catalog import scan_catalog, group_catalog
app = QtWidgets.QApplication(sys.argv)
groups = group_catalog(scan_catalog('assets'))
print('groups:', [(n, len(items)) for n, items in groups])
w = HandheldWindow(groups, QSettings('azya','BrickEmuPy'))
print('launcher built OK; games:', sum(len(i) for _, i in groups))
w.close()
print('closed OK')
"
```
Expected: prints the group counts, `launcher built OK`, `closed OK`, no traceback.

- [ ] **Step 3: GUI acceptance (physical display, Game Mode on)**

Enable Game Mode (Fn+G), then run: `cd ~/Projects/BrickEmuPy && python3 main_handheld.py`
Expected: boots into the launcher (grouped rows with machine-face thumbnails);
D-pad ◄► moves within a row, ▲▼ changes group, the selected tile is highlighted
and scrolls into view; **A** launches the selected game; in-game controls work
(Phase 3); **Y** returns to the launcher; launching a second game works; keyboard
arrows/Enter also navigate. In another shell, `pgrep -af pypy3` shows exactly one
child while a game is up and **none** after returning to the launcher (no leak
across launches). Esc from the launcher quits.

- [ ] **Step 4: Record the result**

Note in the ledger: suite result, group counts, navigation/launch/back
observations, `pgrep pypy3` across two launches (leak check), any stderr noise.
No commit needed unless a defect fix was required in Tasks 1–5.

---

## Self-Review

**Spec coverage:**
- §3 boot flow + gamepad refactor to window → Task 5. ✓
- §3 launch (gameSelected → new GameScreen) and back (teardown) → Task 5. ✓
- §4 game_catalog → Task 1; launcher_selection → Task 2; launcher_screen → Task 4. ✓
- §4 GameScreen handleRole*/teardown + InfoPanel.teardown → Task 3. ✓
- §4 main_handheld optional -brick + boot launcher → Task 5. ✓
- §6 edge cases: empty catalog (Task 4 empty-state + Task 1 filter), bad brick
  skip (Task 1), missing SVG placeholder (Task 4 `_render_thumbnail`), launch
  while active ignored (`_launchGame` guard), teardown idempotent (Task 5). ✓
- §7 testing split: pure Tasks 1–2; py_compile Tasks 3–5; on-device Task 6. ✓
- Constraint: no emulator/core edits; keyboard preserved (BrickWidget unchanged;
  LauncherScreen.keyPressEvent added). ✓

**Placeholder scan:** No TBD/TODO; every code step has full code; every run step
states expected output. ✓

**Type consistency:** `GameEntry`/`scan_catalog`/`group_catalog`,
`LauncherSelection.move/selected/position` + `LEFT/RIGHT/UP/DOWN`,
`LauncherScreen(groups)` + `gameSelected(str)` + `handleRolePressed/Released`,
`GameScreen.handleRolePressed/handleRoleReleased/teardown`, `InfoPanel.teardown`,
`HandheldWindow(groups, settings, initial_brick)` are used identically across
tasks. The window's `handleRolePressed` duck-typed dispatch matches both
LauncherScreen and GameScreen method names. ✓

## Notes for later phases
- Phase 6 (packaging) autostarts `python3 main_handheld.py` (no `-brick`) so the
  device boots into the launcher.
- The `_GROUP_ORDER`/`game_group` mapping is coarse (Phase 2 note); adding a
  `category` field to `.brick` files refines launcher grouping without code.
