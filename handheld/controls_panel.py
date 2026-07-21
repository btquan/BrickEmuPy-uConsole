from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from handheld.controls import controls_legend


class ControlsPanel(QtWidgets.QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        for name, keys in controls_legend(config, lambda c: Qt.Key(c).name.removeprefix("Key_")):
            label = QtWidgets.QLabel("%s: %s" % (name, keys))
            label.setObjectName("controlLabel")
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addStretch(1)
