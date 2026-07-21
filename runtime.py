"""Choose the interpreter that runs the emulator subprocess.

Prefer PyPy (JIT) so CPU-heavy cores hit real time; fall back to the current
CPython interpreter so the app still runs where PyPy is absent.
"""
import os
import shutil
import sys

_ENV_VAR = "BRICKEMU_EMULATOR_PYTHON"
_BUNDLED = os.path.expanduser("~/pypy-portable/bin/pypy3")


def emulator_interpreter():
    override = os.environ.get(_ENV_VAR)
    if override and os.path.exists(override):
        return override
    if os.path.exists(_BUNDLED) and os.access(_BUNDLED, os.X_OK):
        return _BUNDLED
    found = shutil.which("pypy3")
    if found:
        return found
    return sys.executable
