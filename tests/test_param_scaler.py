# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""ParamScaler checks -- proportional ("scale") knob takeover.

The contract, from param_scaler.py's own docstring: the value moves
relative to the knob's change and the runway each has left; it always
moves in the same direction as the knob; and once the knob reaches an end
stop the value is there too.

param_scaler.py imports only micropython.const, so like test_arpeggiator
this runs on a bare interpreter with no stubs.

    python3 tests/test_param_scaler.py
    micropython tests/test_param_scaler.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/../synthtools")  # direct: skips synthtools/__init__

from param_scaler import ParamScaler  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


def sweep(ps, frm, to, steps):
    """Turn the knob from frm to to in `steps` equal moves."""
    for i in range(1, steps + 1):
        ps.update(frm + (to - frm) * i / steps)
    return ps.val


# --- 1. a matched knob tracks 1:1, for ANY step size ---------------------
# The value and the knob agree, so turning the knob n counts must move the
# value n counts. This is the case that exposes whether the runway is
# measured before or after the move.
for step in (1, 5, 25, 60):
    ps = ParamScaler(128, 128)
    ps.update(128 + step)
    ck(
        abs(ps.val - (128 + step)) < 0.5,
        "matched knob not 1:1 over a step of %d: val %.2f, knob %d" % (step, ps.val, 128 + step),
    )

# --- 2. the value never moves against the knob --------------------------
for val in (0, 20, 128, 200, 255):
    for knob in (0, 40, 128, 210, 255):
        for d in (-20, -3, 3, 20):
            k2 = knob + d
            if not 0 <= k2 <= 255:
                continue
            ps = ParamScaler(val, knob)
            before = ps.val
            ps.update(k2)
            if d > 0:
                ck(
                    ps.val >= before - 1e-9,
                    "val fell on a rising knob: val %d knob %d d %d -> %.2f"
                    % (val, knob, d, ps.val),
                )
            else:
                ck(
                    ps.val <= before + 1e-9,
                    "val rose on a falling knob: val %d knob %d d %d -> %.2f"
                    % (val, knob, d, ps.val),
                )

# --- 3. an end stop brings the value with it ----------------------------
# "Once the knob reaches its max or min position, the value will move in
# sync with the knob" -- so from any mismatch, running the knob to a rail
# must land the value on that rail.
for start in (0, 30, 128, 200, 255):
    ck(
        abs(sweep(ParamScaler(start, 128), 128, 255, 64) - 255) < 0.5,
        "knob to max left val at %.2f (start %d)"
        % (sweep(ParamScaler(start, 128), 128, 255, 64), start),
    )
    ck(
        abs(sweep(ParamScaler(start, 128), 128, 0, 64) - 0) < 0.5,
        "knob to min left val at %.2f (start %d)"
        % (sweep(ParamScaler(start, 128), 128, 0, 64), start),
    )

# --- 4. a knob already at a rail, nudged further, pins the value --------
ps = ParamScaler(100, 255)
ps.update(255)  # no movement at the stop
ck(ps.val == 100, "a stationary knob moved the value: %.2f" % ps.val)

# --- 5. the value stays in range ----------------------------------------
ps = ParamScaler(250, 10)
sweep(ps, 10, 255, 8)  # big coarse steps, the overshoot-prone case
ck(0 <= ps.val <= 255, "val left 0-255: %.2f" % ps.val)

# --- 6. reset() clears the 1:1 lock -------------------------------------
ps = ParamScaler(128, 128)
ps.update(130)  # close enough to latch knob_match
ps.reset(val=20, knob_pos=200)
ps.update(205)
ck(ps.val < 100, "reset() did not clear the 1:1 lock: val %.2f" % ps.val)

if fails:
    print("FAIL (%d)" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_param_scaler: ok")
