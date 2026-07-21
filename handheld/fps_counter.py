"""Frame-rate accumulator. Pure and PyQt6-free; caller supplies timestamps."""


class FpsCounter:
    def __init__(self):
        self._frames = 0
        self._last = None

    def tick(self):
        self._frames += 1

    def sample(self, now_seconds):
        if self._last is None:
            self._last = now_seconds
            self._frames = 0
            return 0.0
        dt = now_seconds - self._last
        frames = self._frames
        self._last = now_seconds
        self._frames = 0
        if dt <= 0:
            return 0.0
        return frames / dt
