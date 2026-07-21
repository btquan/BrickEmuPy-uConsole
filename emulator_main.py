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
