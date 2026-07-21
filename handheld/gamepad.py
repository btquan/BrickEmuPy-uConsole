"""Reads /dev/input/js0 on a background thread and emits role transitions."""
import os
import select

from PyQt6.QtCore import QThread, pyqtSignal

from handheld.js_events import (parse_js_event, button_role, axis_roles,
                                AxisTracker, EVENT_SIZE)

JS_DEVICE = "/dev/input/js0"


class GamepadReader(QThread):
    rolePressed = pyqtSignal(str)
    roleReleased = pyqtSignal(str)

    def __init__(self, profile, device=JS_DEVICE, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._device = device
        self._running = True
        self._axes = AxisTracker(profile.get("axis_threshold", 16000))

    def run(self):
        try:
            fd = os.open(self._device, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return          # no gamepad (dev machine / Game Mode off)
        try:
            buf = b""
            while self._running:
                r, _, _ = select.select([fd], [], [], 0.2)
                if not r:
                    continue
                try:
                    chunk = os.read(fd, EVENT_SIZE * 32)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= EVENT_SIZE:
                    frame, buf = buf[:EVENT_SIZE], buf[EVENT_SIZE:]
                    self._handle(frame)
        finally:
            os.close(fd)

    def _handle(self, frame):
        kind, number, value = parse_js_event(frame)
        if kind == "button":
            role = button_role(number, self._profile)
            if role:
                (self.rolePressed if value else self.roleReleased).emit(role)
        elif kind == "axis":
            neg, pos = axis_roles(number, self._profile)
            for role, pressed in self._axes.feed(number, value, neg, pos):
                (self.rolePressed if pressed else self.roleReleased).emit(role)

    def stop(self):
        self._running = False
        self.wait()
