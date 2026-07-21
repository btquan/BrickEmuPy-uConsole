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
