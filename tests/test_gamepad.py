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
