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
