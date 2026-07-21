import time

from PyQt6 import QtWidgets, QtCore

from brick_widget import BrickWidget
from handheld.info_panel import InfoPanel
from handheld.controls_panel import ControlsPanel
from handheld.fps_counter import FpsCounter
from handheld.metadata import game_name, game_group
from handheld.input_map import load_profile, resolve_role

PANEL_WIDTH = 240
DEFAULT_ASPECT = 0.75


class GameScreen(QtWidgets.QWidget):
    def __init__(self, config, brick_path, settings, parent=None):
        super().__init__(parent)

        self._config = config
        self._profile = load_profile()
        self._heldRoles = {}          # game button name -> set of roles holding it

        self._info = InfoPanel()
        self._brick = BrickWidget(config, settings)
        self._controls = ControlsPanel(config, self._profile)

        self._info.setFixedWidth(PANEL_WIDTH)
        self._controls.setFixedWidth(PANEL_WIDTH)

        # Show only the LCD: fit to the segment/display region so the plastic
        # body outside it is clipped by the (aspect-locked) view.
        self._brick.fitToScreen(True)
        self._aspect = self._brick.contentAspect() or DEFAULT_ASPECT

        # Panels pinned to the edges; the game sits centred between stretch
        # spacers so its side margins are the dark app background, not plastic.
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._info)
        layout.addStretch(1)
        layout.addWidget(self._brick)
        layout.addStretch(1)
        layout.addWidget(self._controls)

        self._info.set_game(game_name(config, brick_path), game_group(config))

        self._fps = FpsCounter()
        self._brick.frameRendered.connect(self._fps.tick)
        self._fpsTimer = QtCore.QTimer(self)
        self._fpsTimer.timeout.connect(self._sampleFps)
        self._fpsTimer.start(1000)

        self._brick.setFocus()

    def resizeEvent(self, event):
        # Lock the game widget to the LCD aspect ratio at full height, so it
        # stays LCD-shaped (no plastic in the letterbox margins).
        self._brick.setFixedWidth(max(1, int(self.height() * self._aspect)))
        return super().resizeEvent(event)

    def _sampleFps(self):
        self._info.set_fps(self._fps.sample(time.monotonic()))

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

    def teardown(self):
        self._fpsTimer.stop()
        self._info.teardown()
        self._brick.close()

    def close(self):
        self.teardown()
        return super().close()
