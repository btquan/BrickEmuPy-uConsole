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
