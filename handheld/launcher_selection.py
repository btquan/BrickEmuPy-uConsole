"""Pure gamepad/keyboard selection model for the launcher grid. No Qt."""

LEFT, RIGHT, UP, DOWN = "LEFT", "RIGHT", "UP", "DOWN"


class LauncherSelection:
    def __init__(self, groups):
        self._groups = [g for g in groups if g[1]]   # drop empty groups
        self._g = 0
        self._i = 0

    def move(self, direction):
        if not self._groups:
            return
        row = self._groups[self._g][1]
        if direction == LEFT:
            self._i = max(0, self._i - 1)
        elif direction == RIGHT:
            self._i = min(len(row) - 1, self._i + 1)
        elif direction == UP:
            self._g = max(0, self._g - 1)
            self._i = min(self._i, len(self._groups[self._g][1]) - 1)
        elif direction == DOWN:
            self._g = min(len(self._groups) - 1, self._g + 1)
            self._i = min(self._i, len(self._groups[self._g][1]) - 1)

    def selected(self):
        if not self._groups:
            return None
        return self._groups[self._g][1][self._i]

    def position(self):
        return (self._g, self._i)
