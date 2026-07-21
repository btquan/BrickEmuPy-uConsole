import os
import queue

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


class _ShortWriteFile:
    """Wraps a raw binary file object and caps every write() to `chunk`
    bytes, deterministically simulating the short writes a real OS pipe can
    produce once a payload exceeds the pipe's buffer capacity. A plain
    os.pipe() on a blocking fd tends to loop internally in the kernel and
    rarely reproduces a short write on its own, so this makes the failure
    mode reproducible in a test.
    """

    def __init__(self, f, chunk=4096):
        self._f = f
        self._chunk = chunk

    def write(self, data):
        n = min(len(data), self._chunk)
        return self._f.write(data[:n])

    def flush(self):
        self._f.flush()

    def close(self):
        self._f.close()


def test_round_trip_payload_larger_than_pipe_buffer():
    # Payload far exceeds typical OS pipe buffer sizes (4KB-64KB depending on
    # platform), and the underlying stream is wrapped so write() can only
    # ever accept a small chunk per call -- forcing the short-write scenario
    # described in the FramedWriter.put review finding. FramedWriter.put must
    # loop until the whole frame is written, or the length-prefixed framing
    # desyncs and the tail is silently dropped, causing reads to hang or
    # misparse.
    r_fd, w_fd = os.pipe()
    writer = FramedWriter(_ShortWriteFile(os.fdopen(w_fd, "wb", buffering=0)))
    reader = FramedReader(os.fdopen(r_fd, "rb", buffering=0))
    payload = (7, b"x" * 300_000)
    writer.put(payload)
    assert reader.get(timeout=5.0) == payload
    reader.close()
    writer.close()


def test_put_does_not_raise_on_dead_pipe():
    # Mirrors the scenario where the emulator subprocess has died: the UI's
    # FramedWriter still has the write end of the pipe open, but the read end
    # is gone, so the kernel signals SIGPIPE/EPIPE on write. UI button
    # presses are wired as partial(self._cmdQueue.put, ...) directly into Qt
    # slots, so put() raising BrokenPipeError here would propagate straight
    # into the Qt event loop. The old multiprocessing.Queue.put() never
    # raised in this situation, so FramedWriter.put must degrade to a silent
    # no-op instead, matching that behavior.
    r_fd, w_fd = os.pipe()
    writer = FramedWriter(os.fdopen(w_fd, "wb", buffering=0))
    os.close(r_fd)  # kill the read end so writes fail
    # Payload is larger than the OS pipe buffer to guarantee the underlying
    # write() call actually attempts I/O (and hits BrokenPipeError) rather
    # than being satisfied entirely by internal buffering.
    writer.put((1, b"x" * 300_000))
