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
