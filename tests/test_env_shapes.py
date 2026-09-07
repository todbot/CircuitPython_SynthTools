# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Numeric checks on the AHR envelope shape in synthtools/waves.py.

Runs the REAL fill_env_rise (not a copy of it) against whichever ulab
backend is available (real numpy under CPython, the pure fallback under
MicroPython).

There is only one shape, and it is only a rise:
  - the HOLD is what synthio's `once=True` already does after the last
    sample, so writing a plateau into the buffer would only shorten the
    rise and force the release rate to compensate for it;
  - the RELEASE re-runs this same rising curve through a CONSTRAINED_LERP
    with swapped endpoints, so there is no falling buffer either.
See synthtools/ahr_envelope.py.

Because the release is `V * (1 - s(t))`, it INVERTS whatever curvature the
buffer has, so the buffer holds 1-(1-t)^curve, and the release comes out
as V*(1-t)^curve, a conventional quick-drop-then-tail decay. Several checks
below assert the "wrong" direction on purpose for that reason.

    python3 tests/test_env_shapes.py
    micropython tests/test_env_shapes.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/stubs")
sys.path.insert(0, _D + "/..")

import ulab.numpy as np  # noqa: E402
from synthtools.waves import (  # noqa: E402
    ENV_SIZE, ENV_PEAK, env_buffer, fill_env_rise,
)

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


def vals(a):
    """List of plain ints; works for numpy arrays and the pure fallback."""
    return [int(v) for v in a]


# --- range, endpoints and monotonicity, across curves --------------------
# curve 0 (and anything below 1) must clamp to linear rather than blowing up.
for curve in (0, -3, 1, 2, 3, 5):
    b = env_buffer()
    fill_env_rise(b, curve)
    v = vals(b)
    tag = "curve=%s" % curve
    ck(len(v) == ENV_SIZE, "buffer length unchanged, " + tag)
    ck(min(v) >= -32768 and max(v) <= 32767, "int16 range, " + tag)
    ck(v[0] == 0, "starts at 0, %s (got %d)" % (tag, v[0]))
    ck(v[-1] == ENV_PEAK, "ends at peak, %s (got %d)" % (tag, v[-1]))
    ck(all(v[i] <= v[i + 1] for i in range(len(v) - 1)),
       "non-decreasing, " + tag)

# --- the rise must span the WHOLE buffer, with no plateau ----------------
# This is the regression guard for the retired hold segment: if a flat tail
# ever comes back, the release rate silently becomes wrong.
b = env_buffer()
fill_env_rise(b, 1)
v = vals(b)
ck(all(v[i] < v[i + 1] for i in range(len(v) - 1)),
   "a linear rise must be STRICTLY increasing: any flat run means a "
   "plateau has crept back into the buffer")

# --- curve=1 must stay bit-identical to a plain linear ramp --------------
# Hardcoded expected samples, NOT a re-run of the implementation. Rebuilding
# the shape here with the same linspace call would be a tautology: it could
# only fail if someone edited two places at once. Both backends must
# reproduce these exactly.
GOLDEN_LINEAR = {0: 0, 8: 4160, 16: 8321, 32: 16643, 48: 24965, 63: ENV_PEAK}
b = env_buffer()
fill_env_rise(b, 1)
v = vals(b)
for i, want in GOLDEN_LINEAR.items():
    ck(v[i] == want,
       "linear index %d: expected %d, got %d" % (i, want, v[i]))

# The buffer holds 1-(1-t)^curve, NOT t^curve; see fill_env_rise. So a
# higher curve rises FASTER off the mark, not slower. That is chosen for what
# it does to the release, which reruns this shape as V*(1-s(t)) and therefore
# inverts it into V*(1-t)^curve, a conventional decay.
GOLDEN_SQUARED = {0: 0, 8: 7793, 16: 14530, 32: 24833, 48: 30909, 63: ENV_PEAK}
b = env_buffer()
fill_env_rise(b, 2)
v = vals(b)
for i, want in GOLDEN_SQUARED.items():
    ck(v[i] == want,
       "squared index %d: expected %d, got %d" % (i, want, v[i]))

# --- shape: curve=2 is FASTER off the mark than linear -------------------
lin, sq = env_buffer(), env_buffer()
fill_env_rise(lin, 1)
fill_env_rise(sq, 2)
lv, sv = vals(lin), vals(sq)
ck(all(sv[i] >= lv[i] for i in range(len(lv))),
   "squared must be >= linear everywhere")
ck(sv[len(sv) // 2] > lv[len(lv) // 2] * 1.25,
   "squared well above linear at midpoint")

# --- the release this implies is a real decay ----------------------------
# This is the property the shape exists for, so assert it here in numeric
# form as well as through the block graph in test_wiring.py.
#   release(t) = V * (1 - s(t))
for curve, want_half in ((1, 0.5), (2, 0.25), (3, 0.125)):
    b = env_buffer()
    fill_env_rise(b, curve)
    half = 1.0 - vals(b)[len(b) // 2] / float(ENV_PEAK)
    ck(abs(half - want_half) < 0.02,
       "curve=%s: release should be ~%.3f of its start by halfway, got %.3f"
       % (curve, want_half, half))
    ck(curve == 1 or half < 0.5,
       "curve=%s: a decay must be past half by halfway; %.3f means the "
       "envelope hangs at the top and then plunges" % (curve, half))

# --- steeper curves nest, and the endpoint never drifts ------------------
# The peak comes from the ramp's last sample rather than from a plateau fill,
# so float error at the top of linspace would show up directly.
prev = lv
for curve in (2, 3, 5):
    b = env_buffer()
    fill_env_rise(b, curve)
    v = vals(b)
    ck(v[0] == 0, "curve=%s must start exactly at 0, got %d" % (curve, v[0]))
    ck(v[-1] == ENV_PEAK,
       "curve=%s must land exactly on peak, got %d" % (curve, v[-1]))
    ck(all(v[i] >= prev[i] for i in range(len(v))),
       "curve=%s must sit at or above the next-shallower curve" % curve)
    prev = v

idx = (0, 16, 32, 48, 63)
print("backend:", np.BACKEND)
print("shape linear:", [lv[i] for i in idx])
print("shape curve2:", [sv[i] for i in idx])
print()
if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_env_shapes: all checks passed")
