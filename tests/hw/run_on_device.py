#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Run a snippet on a CircuitPython board over the serial REPL.

    python3 cpy.py snippet.py [--port /dev/tty.usbmodem11201] [--timeout 20]
    echo "print(1+1)" | python3 cpy.py -

Uses the raw REPL (ctrl-A), so the board's own code.py stays untouched on
disk; it is only interrupted for the duration. Exits back to the friendly
REPL afterwards.
"""
import sys
import time
import argparse
import serial

CTRL_A, CTRL_B, CTRL_C, CTRL_D = b"\x01", b"\x02", b"\x03", b"\x04"


def read_until(ser, token, timeout):
    """Accumulate until `token` appears or we run out of patience."""
    end = time.time() + timeout
    buf = b""
    while time.time() < end:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buf += chunk
            if token in buf:
                return buf, True
        else:
            time.sleep(0.01)
    return buf, False


def run(port, code, timeout, reboot):
    with serial.Serial(port, 115200, timeout=0.1) as ser:
        # interrupt whatever code.py is doing
        ser.write(CTRL_C)
        time.sleep(0.1)
        ser.write(CTRL_C)
        time.sleep(0.2)
        ser.reset_input_buffer()

        ser.write(CTRL_A)                       # raw REPL
        _, ok = read_until(ser, b"raw REPL", 5)
        if not ok:
            print("!! could not enter raw REPL", file=sys.stderr)
            return 2
        read_until(ser, b">", 2)

        ser.write(code.encode() + CTRL_D)
        # device echoes "OK", then stdout, \x04, stderr, \x04
        buf, ok = read_until(ser, CTRL_D * 2, timeout)
        if not ok:                              # maybe still running
            buf2, _ = read_until(ser, CTRL_D * 2, 5)
            buf += buf2

        text = buf.decode("utf-8", "replace")
        if text.startswith("OK"):
            text = text[2:]
        parts = text.split("\x04")
        out = parts[0] if parts else ""
        err = parts[1] if len(parts) > 1 else ""

        sys.stdout.write(out)
        if err.strip():
            sys.stdout.write("\n--- device traceback ---\n" + err)

        ser.write(CTRL_B)                       # back to friendly REPL
        time.sleep(0.1)
        if reboot:
            ser.write(CTRL_D)                   # soft reboot -> runs code.py
            time.sleep(0.2)
        return 1 if err.strip() else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="file of code to run, or - for stdin")
    ap.add_argument("--port", default="/dev/tty.usbmodem11201")
    ap.add_argument("--timeout", type=float, default=20)
    ap.add_argument("--reboot", action="store_true",
                    help="soft-reboot afterwards so code.py resumes")
    a = ap.parse_args()
    code = sys.stdin.read() if a.file == "-" else open(a.file).read()
    sys.exit(run(a.port, code, a.timeout, a.reboot))


main()
