# Phase 1 — PyPy Subprocess IPC Rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `multiprocessing.Queue` transport with an explicit
subprocess + length-prefixed-pickle pipe transport so the emulator can run under
PyPy (JIT) while the PyQt6 UI stays on CPython, delivered as a brick game (E-23)
running end-to-end under PyPy.

**Architecture:** A new framing transport (`ipc.py`) exposes the same
`put()/get()/get_nowait()/close()/cancel_join_thread()` surface the existing code
already calls, so `emulator_process.py` is untouched and `brick_widget.py`
changes only at the process boundary. A new entrypoint (`emulator_main.py`) runs
the emulator in a child process launched with an interpreter chosen by
`runtime.py` (PyPy if available, else CPython).

**Tech Stack:** Python 3 (CPython 3.13 UI / PyPy 3.11 emulator), PyQt6 (UI only),
`subprocess`, `pickle` protocol 5, `struct`, `threading`, pytest.

## Global Constraints

- Do NOT modify `cores/`, `interconnect.py`, `peripherals/`, or the loop/logic in
  `emulator_process.py`. Only its constructor-injected channels change behavior,
  and only via duck-typed replacements — no edits to that file in this phase.
- IPC payloads are builtin types only (tuple/dict/list/int/bytes/str/bool/None);
  pickle protocol 5; must round-trip between CPython 3.13 and PyPy 3.11.
- Emulator subprocess runs under PyPy when available, CPython as fallback — one
  code path, interpreter resolved at spawn time.
- Reuse the existing message opcodes (`MSG_VRAM`, `MSG_EXAMINE`, `CMD_QUIT`, …)
  from `emulator_process.py` verbatim; do not renumber them.
- The child's framed data stream uses the real fd 1; stray text output must be
  redirected to stderr so it cannot corrupt the stream.
- Portable PyPy is already installed on the target at `~/pypy-portable/bin/pypy3`.

---

### Task 1: Framing IPC transport (`ipc.py`)

**Files:**
- Create: `ipc.py`
- Create: `tests/__init__.py` (empty)
- Test: `tests/test_ipc.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `FramedWriter(fileobj)` with `.put(obj)`, `.close()`, `.cancel_join_thread()`.
  - `FramedReader(fileobj, maxsize=0)` with `.get(timeout=None)`,
    `.get_nowait()`, `.close()`, `.cancel_join_thread()`. `.get*` raise
    `queue.Empty` when no message is ready and `EOFError` once the stream ends.

- [ ] **Step 1: Set up test scaffolding**

Run: `python3 -m pip install pytest` (use `--user` or a venv if the environment
is externally managed). Then create the empty file `tests/__init__.py`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_ipc.py`:

```python
import os
import queue
import time

import pytest

from ipc import FramedReader, FramedWriter


def _pipe_pair(maxsize=0):
    r_fd, w_fd = os.pipe()
    writer = FramedWriter(os.fdopen(w_fd, "wb", buffering=0))
    reader = FramedReader(os.fdopen(r_fd, "rb", buffering=0), maxsize=maxsize)
    return reader, writer


def test_round_trip_builtin_payloads():
    reader, writer = _pipe_pair()
    messages = [
        (10, 11),                                  # MSG_VRAM-like tuple
        (0, {"ACC": 5, "PC": 0x123, "RAM": (0, 1, 2)}),
        (40, b"\x00\xff\x10"),                     # MSG_SEND_DATA-like bytes
        (0,),                                      # single-element tuple
    ]
    for m in messages:
        writer.put(m)
    received = [reader.get(timeout=2.0) for _ in messages]
    assert received == messages
    reader.close()
    writer.close()


def test_get_nowait_empty_raises():
    reader, writer = _pipe_pair()
    with pytest.raises(queue.Empty):
        reader.get_nowait()
    reader.close()
    writer.close()


def test_eof_after_writer_closes():
    reader, writer = _pipe_pair()
    writer.put((99,))
    assert reader.get(timeout=2.0) == (99,)
    writer.close()
    with pytest.raises(EOFError):
        # drain until the EOF sentinel surfaces
        for _ in range(100):
            reader.get(timeout=2.0)
    reader.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/test_ipc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ipc'`.

- [ ] **Step 4: Write minimal implementation**

Create `ipc.py`:

```python
"""Length-prefixed pickle transport over binary pipes.

Exposes the subset of the multiprocessing.Queue API that EmulatorProcess and
BrickWidget already call (put / get / get_nowait / close / cancel_join_thread)
so the transport can be swapped without touching that code.
"""
import pickle
import queue
import struct
import threading

_HEADER = struct.Struct("<I")   # 4-byte little-endian payload length
_PROTO = 5
_EOF = object()                 # internal sentinel: stream closed


class FramedWriter:
    def __init__(self, fileobj):
        self._f = fileobj
        self._lock = threading.Lock()
        self._closed = False

    def put(self, obj):
        data = pickle.dumps(obj, protocol=_PROTO)
        frame = _HEADER.pack(len(data)) + data
        with self._lock:
            if self._closed:
                return
            self._f.write(frame)
            self._f.flush()

    def cancel_join_thread(self):
        pass

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._f.close()
            except Exception:
                pass


class FramedReader:
    def __init__(self, fileobj, maxsize=0):
        self._f = fileobj
        self._q = queue.Queue(maxsize=maxsize)
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self._f.read(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _reader(self):
        try:
            while self._running:
                header = self._read_exact(_HEADER.size)
                if header is None:
                    break
                (length,) = _HEADER.unpack(header)
                payload = self._read_exact(length)
                if payload is None:
                    break
                self._q.put(pickle.loads(payload))
        except Exception:
            pass
        finally:
            self._q.put(_EOF)

    def get(self, timeout=None):
        item = self._q.get(timeout=timeout)
        if item is _EOF:
            self._q.put(_EOF)          # keep signalling EOF to later callers
            raise EOFError("emulator stream closed")
        return item

    def get_nowait(self):
        item = self._q.get_nowait()
        if item is _EOF:
            self._q.put(_EOF)
            raise EOFError("emulator stream closed")
        return item

    def cancel_join_thread(self):
        pass

    def close(self):
        self._running = False
        try:
            self._f.close()
        except Exception:
            pass
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_ipc.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add ipc.py tests/__init__.py tests/test_ipc.py
git commit -m "feat: length-prefixed pickle IPC transport for emulator subprocess"
```

---

### Task 2: Interpreter resolution (`runtime.py`)

**Files:**
- Create: `runtime.py`
- Test: `tests/test_runtime.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `emulator_interpreter() -> str` — absolute path/name of the
  interpreter to launch the emulator subprocess with. Resolution order:
  `$BRICKEMU_EMULATOR_PYTHON` (if it exists) → bundled
  `~/pypy-portable/bin/pypy3` → `pypy3` on PATH → `sys.executable`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_runtime.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'runtime'`.

- [ ] **Step 3: Write minimal implementation**

Create `runtime.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_runtime.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add runtime.py tests/test_runtime.py
git commit -m "feat: resolve emulator interpreter (PyPy preferred, CPython fallback)"
```

---

### Task 3: Emulator subprocess entrypoint (`emulator_main.py`)

**Files:**
- Create: `emulator_main.py`
- Test: `tests/test_emulator_subprocess.py`

**Interfaces:**
- Consumes: `FramedReader`/`FramedWriter` from `ipc.py`; `EmulatorProcess` from
  `emulator_process.py`; the message opcodes `CMD_QUIT`, `MSG_VRAM`,
  `MSG_EXAMINE` from `emulator_process.py`.
- Produces: an executable module run as `<interpreter> emulator_main.py
  <config_json_path>` that reads commands as pickle frames on fd 0, writes
  data messages as pickle frames on the original fd 1, and runs the emulator.

- [ ] **Step 1: Write the failing test**

Create `tests/test_emulator_subprocess.py` (runs the child under CPython; a brick
ROM that ships in the repo is used so the test is self-contained):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_emulator_subprocess.py -v`
Expected: FAIL — `emulator_main.py` does not exist yet (FileNotFoundError from
`subprocess.Popen`, surfaced as a test error).

- [ ] **Step 3: Write minimal implementation**

Create `emulator_main.py`:

```python
"""Subprocess entrypoint for the emulator (runs under PyPy or CPython).

    <interpreter> emulator_main.py <config_json_path>

Commands arrive as length-prefixed pickle frames on fd 0 (stdin).
Data messages are written as frames on the ORIGINAL fd 1; fd 1 is then pointed
at stderr so stray prints/warnings cannot corrupt the binary data stream.
"""
import json
import os
import sys

from ipc import FramedReader, FramedWriter
from emulator_process import EmulatorProcess


def main():
    config_path = sys.argv[1]
    with open(config_path) as f:
        config = json.load(f)

    data_fd = os.dup(1)          # keep a private copy of the real stdout
    os.dup2(2, 1)                # anything printed to stdout now goes to stderr
    data_file = os.fdopen(data_fd, "wb", buffering=0)
    cmd_file = os.fdopen(0, "rb", buffering=0)

    cmd_reader = FramedReader(cmd_file)
    data_writer = FramedWriter(data_file)

    EmulatorProcess(config, cmd_reader, data_writer).run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_emulator_subprocess.py -v`
Expected: PASS — the child boots the HT943 core, emits VRAM + examine frames,
then exits cleanly on CMD_QUIT.

- [ ] **Step 5: Commit**

```bash
git add emulator_main.py tests/test_emulator_subprocess.py
git commit -m "feat: emulator subprocess entrypoint over framed pipes"
```

---

### Task 4: Rewire `BrickWidget` to the subprocess transport

**Files:**
- Modify: `brick_widget.py` (imports; `QueueReaderThread.run`;
  `BrickWidget._start_emulator`; `BrickWidget.close`)

**Interfaces:**
- Consumes: `FramedReader`/`FramedWriter` (Task 1), `emulator_interpreter`
  (Task 2), `emulator_main.py` (Task 3), and the existing `DATA_QUEUE_MAXSIZE`,
  `CMD_QUIT`, and `_processMessage` already in `brick_widget.py`.
- Produces: a `BrickWidget` whose `_cmdQueue`/`_dataQueue` are framed
  reader/writer objects wrapping a child `subprocess.Popen`; every existing
  `self._cmdQueue.put(...)` call site keeps working unchanged.

- [ ] **Step 1: Replace the multiprocessing import**

In `brick_widget.py`, change the top-of-file import block.

Find:
```python
import queue
import multiprocessing
```
Replace with:
```python
import queue
import os
import json
import tempfile
import subprocess

from ipc import FramedReader, FramedWriter
from runtime import emulator_interpreter
```

- [ ] **Step 2: Make the reader thread stop on EOF**

In `brick_widget.py`, update `QueueReaderThread.run`.

Find:
```python
    def run(self):
        while self._running:
            try:
                self.messageSignal.emit(self._dataQueue.get(timeout=0.1))
            except queue.Empty:
                continue
```
Replace with:
```python
    def run(self):
        while self._running:
            try:
                self.messageSignal.emit(self._dataQueue.get(timeout=0.1))
            except queue.Empty:
                continue
            except EOFError:
                break
```

- [ ] **Step 3: Rewrite `_start_emulator`**

In `brick_widget.py`, replace the whole `_start_emulator` method.

Find (current body):
```python
    def _start_emulator(self):
        self._cmdQueue = multiprocessing.Queue()
        self._dataQueue = multiprocessing.Queue(maxsize=DATA_QUEUE_MAXSIZE)

        self._QueueReaderThread = QueueReaderThread(self._dataQueue)
        self._QueueReaderThread.messageSignal.connect(self._processMessage)
        self._QueueReaderThread.start()

        self._proc = multiprocessing.Process(
            target=EmulatorProcess.spawn,
            args=(self._config, self._cmdQueue, self._dataQueue),
            daemon=False,
        )
        self._proc.start()
```
Replace with:
```python
    def _start_emulator(self):
        fd, self._config_path = tempfile.mkstemp(suffix=".brickcfg.json")
        with os.fdopen(fd, "w") as f:
            json.dump(self._config, f)

        repo_dir = os.path.dirname(os.path.abspath(__file__))
        entry = os.path.join(repo_dir, "emulator_main.py")
        self._proc = subprocess.Popen(
            [emulator_interpreter(), entry, self._config_path],
            cwd=repo_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            bufsize=0,
        )
        self._cmdQueue = FramedWriter(self._proc.stdin)
        self._dataQueue = FramedReader(self._proc.stdout, maxsize=DATA_QUEUE_MAXSIZE)

        self._QueueReaderThread = QueueReaderThread(self._dataQueue)
        self._QueueReaderThread.messageSignal.connect(self._processMessage)
        self._QueueReaderThread.start()
```

- [ ] **Step 4: Rewrite `close` process teardown**

In `brick_widget.py`, replace the process-teardown portion of `close`.

Find:
```python
        if (self._proc and self._proc.is_alive()):
            self._cmdQueue.put((CMD_QUIT,))
            self._proc.join(timeout=1.0)
            if (self._proc.is_alive()):
                self._proc.terminate()
                self._proc.join()

        self._saveSettings()
        super().close()
```
Replace with:
```python
        if (self._proc and self._proc.poll() is None):
            try:
                self._cmdQueue.put((CMD_QUIT,))
            except Exception:
                pass
            try:
                self._proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()

        if (getattr(self, "_config_path", None)):
            try:
                os.remove(self._config_path)
            except OSError:
                pass

        self._saveSettings()
        super().close()
```

- [ ] **Step 5: Byte-compile check (no PyQt import needed)**

Run: `python3 -m py_compile brick_widget.py`
Expected: no output, exit 0 (syntax valid). `from emulator_process import *`
still provides `CMD_QUIT`, `DATA_QUEUE_MAXSIZE`, and `MSG_*`; `EmulatorProcess`
is no longer referenced here.

- [ ] **Step 6: Full test suite still green**

Run: `python3 -m pytest tests/ -v`
Expected: PASS (all tests from Tasks 1–3).

- [ ] **Step 7: Commit**

```bash
git add brick_widget.py
git commit -m "feat: run emulator as PyPy subprocess via framed-pipe transport"
```

---

### Task 5: On-device acceptance — brick game under PyPy on the uConsole

**Files:**
- None (verification task; no repo changes unless a defect is found).

**Interfaces:**
- Consumes: everything from Tasks 1–4, plus PyQt6 installed on the uConsole and
  the bundled PyPy at `~/pypy-portable/bin/pypy3`.

- [ ] **Step 1: Ensure UI deps on the uConsole**

Run on the device: `python3 -c "import PyQt6.QtCore; print('pyqt ok')"`
If it fails: `sudo apt install -y python3-pyqt6 libxcb-cursor0` and retry.

- [ ] **Step 2: Confirm the interpreter resolver picks PyPy**

Run on the device from the repo dir:
`python3 -c "import runtime; print(runtime.emulator_interpreter())"`
Expected: prints `.../pypy-portable/bin/pypy3` (not the CPython path).

- [ ] **Step 3: Headless subprocess check under PyPy**

Run on the device from the repo dir:
`BRICKEMU_EMULATOR_PYTHON=~/pypy-portable/bin/pypy3 python3 -m pytest tests/test_emulator_subprocess.py -v`

Then edit the test invocation is not required — instead run the entrypoint
directly under PyPy to confirm cross-interpreter framing:
`~/pypy-portable/bin/pypy3 emulator_main.py assets/E23PlusMarkII96in1.brick </dev/null | head -c 8 | xxd`
Expected: prints a 4-byte little-endian length header followed by pickle bytes
(non-empty), proving PyPy writes frames CPython can read.

- [ ] **Step 4: Launch the app and play a brick game**

Run on the device (with a display/session): `python3 main.py -brick assets/E23PlusMarkII96in1.brick`
Expected: the E-23 brick game boots and renders; the child process is PyPy
(verify with `pgrep -af pypy3` in another shell). Press the mapped keys and
confirm the game responds. Note the first few seconds may run slightly slow
(PyPy JIT warmup) then reach full speed — this is expected per the spec §8.

- [ ] **Step 5: Record the result**

Append a short note to the spec's benchmark section or a `NOTES.md`: interpreter
used, observed warmup feel, any stderr warnings from the child. No commit needed
unless a defect fix was required in Tasks 1–4.

---

## Self-Review

**Spec coverage (Phase 1 scope):**
- §4 runtime split (CPython UI + PyPy emulator subprocess) → Tasks 2, 3, 4. ✓
- §4 IPC via pipe/pickle replacing multiprocessing.Queue → Tasks 1, 3, 4. ✓
- §4 payloads builtin types, protocol 5 → Task 1 (`_PROTO = 5`, round-trip test). ✓
- §4 stray-print isolation on fd 1 → Task 3 (`os.dup`/`os.dup2`). ✓
- §4 CPython fallback → Task 2 (`emulator_interpreter` fallback + test). ✓
- §4 cores/interconnect/peripherals/loop untouched → enforced by the duck-typed
  channel surface; Task 4 Step 5 confirms `EmulatorProcess` is no longer imported
  in `brick_widget.py` and `emulator_process.py` is unmodified. ✓
- Priority: brick game (HT943) is the acceptance content → Tasks 3 & 5 use
  `E23PlusMarkII96in1.brick`. ✓
- Out of Phase-1 scope (later plans): GameScreen panels (§5), InputMapper (§5),
  SaveStateManager (§6), LauncherScreen (§5), packaging (§9). Not covered here by
  design.

**Placeholder scan:** No TBD/TODO; every code step contains full code; every run
step states the expected result. ✓

**Type consistency:** `FramedWriter.put`/`FramedReader.get`/`get_nowait`/`close`/
`cancel_join_thread` names are identical across `ipc.py`, `emulator_main.py`,
`brick_widget.py`, and all tests. `emulator_interpreter()` name matches between
`runtime.py`, its test, and `brick_widget.py`. Message opcodes (`CMD_QUIT` tuple
`(0,)`, `MSG_VRAM=10`, `MSG_EXAMINE=0`) match `emulator_process.py` constants. ✓

## Notes for later phases
- Later plans depend on this IPC API: send a command with `self._cmdQueue.put(tuple)`,
  receive with the reader thread → `_processMessage`. New commands
  (`CMD_SAVE_STATE`, `CMD_LOAD_STATE`) and replies (`MSG_STATE_DUMP`) plug into
  the same transport with no transport changes.
