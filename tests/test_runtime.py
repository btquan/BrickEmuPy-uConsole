import os
import sys

import runtime


def test_env_override_wins(tmp_path, monkeypatch):
    fake = tmp_path / "myinterp"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("BRICKEMU_EMULATOR_PYTHON", str(fake))
    assert runtime.emulator_interpreter() == str(fake)


def test_falls_back_to_cpython(monkeypatch):
    monkeypatch.delenv("BRICKEMU_EMULATOR_PYTHON", raising=False)
    monkeypatch.setattr(runtime, "_BUNDLED", "/nonexistent/pypy3")
    monkeypatch.setattr(runtime.shutil, "which", lambda name: None)
    assert runtime.emulator_interpreter() == sys.executable
