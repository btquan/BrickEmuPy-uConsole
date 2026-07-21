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

    def teardown(self):
        self._batteryTimer.stop()

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
