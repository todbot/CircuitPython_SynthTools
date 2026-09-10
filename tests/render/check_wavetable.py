# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# check_wavetable.py -- correctness of Wavetable.set_wave_pos() under a real
# CircuitPython unix build (real ulab, real adafruit_wave). The CPython /
# MicroPython test tiers cannot reach WavetableSynth (no adafruit_wave stub;
# tests/test_wiring.py pins that), so this is where the lerp gets checked.
#
#   micropython tests/render/check_wavetable.py --wave-lib <dir with adafruit_wave.py>
#
# Run from the repo root. Exits non-zero on any failure.

import sys

_argv = sys.argv[1:]
for _i, _a in enumerate(_argv):
    if _a == "--wave-lib":
        sys.path.insert(0, _argv[_i + 1])
sys.path.insert(0, ".")

import ulab.numpy as np  # noqa: E402

from synthtools.wavetable import Wavetable  # noqa: E402

WAV = "examples/wavetables/BRAIDS02.WAV"
SIZE = 256

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)
        print("FAIL:", msg)


def ref_lerp(raw_wt, pos):
    """Independent float reference: what set_wave_pos(pos) should produce."""
    n = raw_wt.num_waves
    if pos < 0:
        pos = 0.0
    elif pos > n - 1:
        pos = n - 1.0
    i = int(pos)
    if i > n - 2:
        i = n - 2
    frac = pos - i
    a = [int(x) for x in raw_wt._read_wave(i)]
    if frac <= 0.0:
        return a
    b = [int(x) for x in raw_wt._read_wave(i + 1)]
    return [int(a[k] + frac * (b[k] - a[k])) for k in range(len(a))]


def maxdiff(buf, ref):
    return max(abs(int(buf[k]) - ref[k]) for k in range(len(ref)))


wt = Wavetable(WAV)  # preload=True
n = wt.num_waves
print("loaded", WAV, "-", n, "waves, preload w =", wt.w)

# --- object identity across many calls ---
first = wt.waveform
for p in (0.0, 1.3, 1.3, 4.7, 20.1, 3.0, 3.0, 63.0, 62.5):
    wt.set_wave_pos(p)
    ck(wt.waveform is first, "waveform identity broke at pos %s" % p)

# --- correctness vs the float reference, <= 1 LSB ---
for p in (0.0, 5.0, 5.25, 5.5, 5.75, -3.0, n + 10.0, n - 1.0, n - 1):
    wt.set_wave_pos(p)
    d = maxdiff(wt.waveform, ref_lerp(wt, p))
    ck(d <= 1, "pos %s: max abs diff %d > 1 LSB" % (p, d))

# --- int16 range at a high-amplitude zero straddle ---
for p in (2.5, 10.5, 30.5, 45.5):
    wt.set_wave_pos(p)
    lo = min(int(x) for x in wt.waveform)
    hi = max(int(x) for x in wt.waveform)
    ck(-32768 <= lo and hi <= 32767, "pos %s out of int16 range: %d..%d" % (p, lo, hi))

# --- cache-coherence edges (exact-wave / non-adjacent jump must not corrupt) ---
wt.set_wave_pos(3.5)
want = list(wt.waveform)
wt.set_wave_pos(3.0)  # exact wave, same i
wt.set_wave_pos(3.5)
ck(list(wt.waveform) == want, "3.5 -> 3.0 -> 3.5 did not return to the same buffer")
wt.set_wave_pos(3.5)
want = list(wt.waveform)
wt.set_wave_pos(9.0)  # non-adjacent pair
wt.set_wave_pos(3.5)
ck(list(wt.waveform) == want, "3.5 -> 9.0 -> 3.5 did not return to the same buffer")

# --- preload=True and preload=False are bit-identical ---
lazy = Wavetable(WAV, preload=False)
ck(lazy.w is not None, "preload=False should keep the file open")
for p in (0.0, 5.25, 12.5, 40.75, n - 1.0):
    wt.set_wave_pos(p)
    lazy.set_wave_pos(p)
    ck(
        list(wt.waveform) == list(lazy.waveform),
        "preload vs lazy differ at pos %s" % p,
    )

if fails:
    print("\n%d failure(s)" % len(fails))
    sys.exit(1)
print("\ncheck_wavetable: all checks passed")
