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
