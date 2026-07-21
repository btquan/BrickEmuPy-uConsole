"""Length-prefixed pickle transport over binary pipes.

Exposes the subset of the multiprocessing.Queue API that EmulatorProcess and
BrickWidget already call (put / get / get_nowait / close / cancel_join_thread)
so the transport can be swapped without touching that code.
"""
import pickle
import queue
import struct
import sys
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
            # write() on a pipe can return fewer bytes than given once the
            # payload exceeds the OS pipe buffer; loop until the whole frame
            # is sent, mirroring the _read_exact loop on the read side.
            try:
                view = memoryview(frame)
                while view:
                    n = self._f.write(view)
                    view = view[n:]
                self._f.flush()
            except (BrokenPipeError, OSError, ValueError):
                # The consumer (emulator subprocess) is gone -- the old
                # multiprocessing.Queue.put() never raised in this
                # situation, so degrade to a silent no-op instead of
                # throwing BrokenPipeError into whatever called put()
                # (e.g. a Qt slot wired via partial(self._cmdQueue.put, ...)).
                self._closed = True
                return

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
        except Exception as e:
            # Not a clean EOF (that's handled by header/payload being None
            # above) -- surface the corruption/decoding failure instead of
            # silently hanging, since a bare pass here turns data corruption
            # into an unexplained hang with no diagnostic.
            print(f"FramedReader: stream error: {e!r}", file=sys.stderr)
        finally:
            # Always enqueue EOF so blocked/future get() calls raise
            # EOFError instead of hanging -- this mirrors the
            # multiprocessing.Queue behavior where subprocess termination
            # closes the pipe and the daemon reader thread exits on EOF.
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
