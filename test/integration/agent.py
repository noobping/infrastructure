#!/usr/bin/env python3
"""Private test control channel. Installed only by the disposable VM overlay."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def serve(channel, temporary_directory="/var/tmp"):
    line = bytearray()
    while not line.endswith(b"\n"):
        byte = channel.read(1)
        if not byte:
            time.sleep(0.1)
            continue
        line.extend(byte)
        if len(line) > 65536:
            raise ValueError("Control request too large")
    request = json.loads(line)
    size = request.get("stdin_size", 0)
    if not 0 <= size <= 16 * 2**30:
        raise ValueError("Invalid input size")
    with tempfile.TemporaryFile(dir=temporary_directory) as source:
        remaining = size
        while remaining:
            chunk = channel.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise EOFError("Truncated control input")
            source.write(chunk)
            remaining -= len(chunk)
        source.seek(0)
        try:
            result = subprocess.run(["/usr/bin/bash", "-c", request["command"]], stdin=source,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=min(request.get("timeout", 300), 1800))
            response = {"code": result.returncode, "stdout": result.stdout.decode(errors="replace"),
                        "stderr": result.stderr.decode(errors="replace")}
        except subprocess.TimeoutExpired:
            response = {"code": 124, "stdout": "", "stderr": "Guest command timed out"}
        payload = memoryview(json.dumps(response).encode() + b"\n")
        while payload:
            count = channel.write(payload)
            payload = payload[count:]


def main():
    device = Path("/dev/virtio-ports/infrastructure.test")
    for _ in range(60):
        if device.exists():
            break
        time.sleep(1)
    # One request per connection. A guest-side timeout also prevents an orphaned
    # assertion from running indefinitely if the controller is interrupted.
    with device.open("r+b", buffering=0) as channel:
        serve(channel)


if __name__ == "__main__":
    os.umask(0o077)
    main()
