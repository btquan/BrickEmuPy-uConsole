import os
import subprocess
import sys
import time

from ipc import FramedReader, FramedWriter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(REPO, "assets", "E23PlusMarkII96in1.brick")
CMD_QUIT = (0,)          # matches emulator_process.CMD_QUIT tuple form
MSG_VRAM = 10
MSG_EXAMINE = 0


def test_subprocess_emits_vram_and_examine_then_quits():
    proc = subprocess.Popen(
        [sys.executable, os.path.join(REPO, "emulator_main.py"), CONFIG],
        cwd=REPO,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    reader = FramedReader(proc.stdout)
    writer = FramedWriter(proc.stdin)

    seen = set()
    deadline = time.time() + 10.0
    try:
        while time.time() < deadline and {MSG_VRAM, MSG_EXAMINE} - seen:
            try:
                msg = reader.get(timeout=1.0)
            except Exception:
                continue
            seen.add(msg[0])
        assert MSG_VRAM in seen, "never received a VRAM frame"
        assert MSG_EXAMINE in seen, "never received an examine frame"

        writer.put(CMD_QUIT)
        proc.wait(timeout=5.0)
        assert proc.returncode is not None
    finally:
        reader.close()
        writer.close()
        if proc.poll() is None:
            proc.kill()
