# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Checks for the cached oscillator waveforms in synthtools/waves.py and the
``Waves`` factory in synthtools/wave_factory.py.

The Mozzi-derived "analog" tables are hand-drawn data with no recipe to
regenerate them, so golden values pin them: any change to how they are
stored must leave every rendered sample where it was.

    python3 tests/test_waves.py
    micropython tests/test_waves.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/stubs")
sys.path.insert(0, _D + "/..")

import ulab.numpy as np  # noqa: E402
from synthtools.wave_factory import Waves  # noqa: E402
from synthtools.waves import get_wave, get_wave_2x, wave_names  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


# --- Mozzi tables render exactly as before -------------------------------
# name -> (sum of all 256 samples, samples at 0, 37, 128, 200, 255)
GOLDEN = {
    "ASAW": (-442, (24693, 15984, -1323, -13228, 21276)),
    "ATRI": (1757, (-23370, -11079, 27559, -5071, -23315)),
    "ASQU": (-3974, (23591, 23701, -23370, -23811, 6173)),
    "SSQU": (-686, (-1102, 21165, 25795, -28000, -28000)),
}
for name, (total, samples) in GOLDEN.items():
    w = get_wave(name)
    ck(len(w) == 256, "%s: length %d" % (name, len(w)))
    ck(sum(int(v) for v in w) == total, "%s: sample sum changed" % name)
    got = tuple(int(w[i]) for i in (0, 37, 128, 200, 255))
    ck(got == samples, "%s: samples %r, want %r" % (name, got, samples))

# --- get_wave() and get_wave_2x() share one buffer ------------------------
for name in wave_names():
    if name == "NZE":
        continue
    one = list(get_wave(name, 128))
    two = get_wave_2x(name, 128)
    ck(len(two) == 256, "%s: 2x length %d" % (name, len(two)))
    ck(list(two[:128]) == one and list(two[128:]) == one, "%s: 2x must be two cycles" % name)
    ck(list(get_wave(name, 128)) == one, "%s: get_wave() changed after the 2x build" % name)
    if np.BACKEND == "numpy":
        import numpy

        ck(numpy.shares_memory(get_wave(name, 128), two),
           "%s: get_wave() must be a view of the 2x buffer once it exists" % name)

# --- the Waves factory still reaches get_wave() ---------------------------
ck(list(Waves.make_waveform("ANALOG_SAW", 256, 28000)) == list(get_wave("ASAW")),
   "make_waveform must alias ANALOG_SAW to the cached ASAW")
ck(len(Waves.make_waveform("SIL", 64)) == 64, "SIL must give a silent buffer")
ck(Waves.make_waveform("nope") is None, "an unknown name must give None")

print()
if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_waves: all checks passed")
