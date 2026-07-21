# Phase 5 — Grid Launcher — Design

**Date:** 2026-07-21
**Target device:** ClockworkPi uConsole (Raspberry Pi CM4)
**Fork:** `git@github.com:btquan/BrickEmuPy-uConsole.git`
**Depends on:** Phase 2 (handheld GameScreen), Phase 3 (gamepad input) — merged to `main`.
**Status:** Approved design, ready for implementation planning
**Priority:** Brick games first.

## 1. Overview

Boot the uConsole into a console-style **grid launcher**: one horizontal,
scrollable row per game group (Brick / Virtual Pet / Other), each showing the
machine-face thumbnail. Navigate with the gamepad (D-pad + A) or keyboard,
launch a game, and return to the launcher with the **Y** button. Only games
whose ROM is present are listed.

This completes the "power on → pick → play" loop. It reuses the Phase 2
`GameScreen` and Phase 3 gamepad input, and refactors the single `GamepadReader`
up to `HandheldWindow` so it serves both the launcher and the game.

## 2. Decisions (from brainstorming)

- **Back-to-launcher button:** **BTN_Y** (unmapped in games), plus Esc for dev.
- **Layout:** grouped horizontal rows (console-style). D-pad ◄► moves within a
  row, ▲▼ changes group; **A** launches the selected game.
- **Horizontal navigation:** clamp at row ends (no wrap); ▲▼ clamps at first/last
  group and preserves a sensible column.
- **Thumbnail:** the machine-face SVG (`body` element), the recognizable game.
- **Group labels:** shown as text headers above each row.
- **Boot:** launcher first; `-brick` remains optional for booting straight into a
  game (dev convenience).

## 3. Screen management & gamepad refactor

```
main_handheld.py  (-brick optional)
  └─ HandheldWindow (fullscreen QStackedWidget)
       ├─ [0] LauncherScreen        (boot target)
       ├─ [1] GameScreen            (created on launch, torn down on back)
       └─ GamepadReader             (single reader, owned here)
```

- **`GamepadReader` moves from `GameScreen` to `HandheldWindow`.** The window
  receives `rolePressed`/`roleReleased` and routes them:
  - If a game is active and role == `BTN_Y` (press) → return to launcher.
  - Else → dispatch to the active screen's handler (LauncherScreen: navigate /
    launch; GameScreen: `handleRolePressed`/`handleRoleReleased`, keeping the
    Phase-3 reference-count logic, only the call source changes).
- **Launch:** LauncherScreen emits `gameSelected(brick_path)`; the window loads
  the config, creates a `GameScreen`, adds it to the stack, switches to it, and
  gives it focus.
- **Back:** the window calls `GameScreen.teardown()` (stops the FPS timer, stops
  the InfoPanel battery timer, closes the `BrickWidget` — reaping the PyPy
  child), removes it from the stack, switches to the launcher, and gives it
  focus. This fixes the Phase-2 final-review notes about stopping the battery
  timer and doing screen teardown explicitly rather than via `close()`.
- Keyboard: in the game, `BrickWidget` handles keys as before; in the launcher,
  `LauncherScreen.keyPressEvent` handles arrows + Enter (+ Esc = quit app).

## 4. Components (each: one responsibility, own interface)

### `handheld/game_catalog.py` — pure catalog (no Qt)
- `scan_catalog(assets_dir) -> list[GameEntry]` where `GameEntry` is a small
  dataclass `{name, group, brick_path, svg_path}`.
- Reads every `assets/*.brick`, keeps only entries whose ROM
  (`mask_options.rom_path`) exists, derives `name`/`group` via the Phase-2
  `handheld.metadata` helpers, and resolves the SVG face path.
- `group_catalog(entries) -> list[(group_name, [entries])]` in a fixed group
  order (Brick, Virtual Pet, Other), each group's entries sorted by name.
- Pure and dependency-free → unit-tested against a fake assets directory.

### `handheld/launcher_selection.py` — pure selection model (no Qt)
- `LauncherSelection(groups)` where groups is `list[(name, [entries])]`.
- `move(direction)` for `LEFT/RIGHT/UP/DOWN` (clamped); `selected() -> GameEntry
  | None`; `position() -> (group_index, item_index)`.
- Vertical moves clamp the item index into the new group's length.
- Pure and deterministic → unit-tested.

### `handheld/launcher_screen.py` — Qt
- `LauncherScreen(catalog_groups, parent=None)` with signal
  `gameSelected(str)` (brick_path).
- Renders a group label + a horizontal strip of machine-face thumbnails per
  group (thumbnails via `QSvgRenderer("...").render` of the `body` element into a
  `QPixmap`, sized to the row height, cached).
- Highlights the selected tile and scrolls the row so it stays visible.
- `handleRolePressed(role)` maps D-pad roles → `LauncherSelection.move` and
  `BTN_A` → emit `gameSelected`; `keyPressEvent` maps arrows/Enter the same way.

### Changes to existing files
- **`handheld/window.py`**: host the launcher + games, own the `GamepadReader`,
  route roles, create/tear down `GameScreen`, handle Y/Esc = back, Esc-in-launcher
  = quit.
- **`handheld/game_screen.py`**: remove its own `GamepadReader`; add public
  `handleRolePressed(role)` / `handleRoleReleased(role)` (the former private
  `_onRole*`) and a `teardown()` that stops both timers and closes the brick;
  `close()` delegates to `teardown()`.
- **`handheld/info_panel.py`**: expose a way to stop the battery `QTimer` (a
  `teardown()` or stop in the parent's teardown) so a torn-down GameScreen stops
  polling.
- **`main_handheld.py`**: make `-brick` optional; with it, boot straight into a
  game (current behaviour); without it, build the catalog and boot the launcher.

## 5. Data flow

```
Launcher nav:  js0 → role → HandheldWindow.route → LauncherScreen.handleRolePressed
               → LauncherSelection.move / gameSelected

Launch:        LauncherScreen.gameSelected(brick_path)
               → HandheldWindow: load config → new GameScreen → stack.switch

In game:       role → HandheldWindow.route → (BTN_Y → back) | GameScreen.handleRole*

Back:          HandheldWindow: GameScreen.teardown() → stack.switch(launcher)
```

## 6. Error handling / edge cases

- No games with ROM present → launcher shows an empty-state message, does not
  crash.
- A `.brick` that fails to load/parse during scan → skipped (logged to stderr),
  scan continues.
- Missing/invalid SVG for a thumbnail → a placeholder tile; the game still
  launches.
- Rapid back/relaunch → `teardown()` is idempotent; the reader keeps running in
  the window (never stopped between games), only its routing target changes.
- Launching while a game already active shouldn't happen (launcher isn't the
  active screen then), but `gameSelected` is ignored if a game is already up.

## 7. Testing

- **Pure (dev Mac):** `game_catalog.scan_catalog`/`group_catalog` (fake assets:
  ROM-present filter, grouping order, name/group derivation, bad-brick skip);
  `LauncherSelection.move` (clamp at edges, group changes preserve/clamp column,
  `selected`).
- **Qt (on-device, offscreen):** build `LauncherScreen` from the real catalog
  without raising; a screenshot to tune the visual layout (as in Phase 2).
- **On-device acceptance:** boot into the launcher; D-pad navigates rows/groups;
  A launches a brick game; Y returns to the launcher; launch a second game; no
  leaked PyPy process or QThread across launches; keyboard nav also works.

## 8. Milestones (implementation-plan tasks)

1. `game_catalog.py` (scan + group) + tests.
2. `launcher_selection.py` (pure nav model) + tests.
3. `game_screen.py` refactor: `handleRolePressed/Released` + `teardown()`;
   `info_panel.py` battery-timer stop.
4. `launcher_screen.py` (Qt: thumbnails, layout, nav handlers, `gameSelected`).
5. `window.py` refactor: own `GamepadReader`, route roles, create/tear-down
   GameScreen, Y/Esc back; `main_handheld.py` optional `-brick` + boot launcher.
6. On-device acceptance (launcher navigation + launch/back + no leaks).

## 9. Risks

| Risk | Mitigation |
|---|---|
| Moving GamepadReader up refactors Phase-3 wiring | Keep the ref-count handlers intact; only the reader's owner + routing move; on-device suite/gameplay re-verified |
| Thumbnail rendering (39 SVGs) slows launcher start | Render at a small fixed size, cache per game; lazy-render offscreen rows if needed |
| GameScreen not torn down on back → PyPy/thread leak | Explicit `teardown()` called by the window on back; on-device `pgrep pypy3` check across launches |
| Short 480px height crowds 3 group rows | Compact labels + row height tuned via on-device screenshot |
