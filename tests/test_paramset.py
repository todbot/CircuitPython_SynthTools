# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""ParamSet knob-mode checks.

KNOB_PICKUP: a pot does nothing until it passes the value it points at,
then tracks 1:1.

KNOB_SCALE: every turn moves the value, scaled so the two converge; the
same "SCALE" takeover ui/param_scaler.py implements, and carrying the same
contract: never move against the knob, never move without the knob, and
land on a rail when the knob is driven onto one.

paramset.py imports only json, so this runs on a bare interpreter.

    python3 tests/test_paramset.py
    micropython tests/test_paramset.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/../synthtools")  # direct: skips synthtools/__init__

from paramset import Param, ParamSet  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


def mk(mode, val=50.0):
    ps = ParamSet(
        [Param("x", val, 0, 100, "%.1f", None), Param("y", 0, 0, 1, "%.1f", None)],
        2,
        knob_mode=mode,
    )
    ps.update_knobs((0.5, 0.0))  # adopt the starting knob position
    return ps, ps.params[0]


def sweep(ps, p, frm, to, steps=64, other=0.0):
    for i in range(1, steps + 1):
        ps.update_knobs((frm + (to - frm) * i / steps, other))
    return p.val


# --- KNOB_SCALE ---------------------------------------------------------

# 1. A knob that is not moving must not move the value. This is the bug
#    the mode's own "note this sucks currently" refers to: with no memory
#    of the previous knob position it used knob-minus-value as if it were
#    the knob's movement, so a mismatched value crept on its own.
ps, p = mk(ParamSet.KNOB_SCALE, 90.0)
for _ in range(50):
    ps.update_knobs((0.5, 0.0))  # knob pinned at centre, value up at 90
ck(p.val == 90.0, "stationary knob moved the value: 90.0 -> %.3f" % p.val)

# 2. A matched knob tracks 1:1.
ps, p = mk(ParamSet.KNOB_SCALE, 50.0)  # val 50/100 == knob 0.5
ps.update_knobs((0.75, 0.0))
ck(abs(p.val - 75.0) < 0.5, "matched knob not 1:1: %.2f, want 75" % p.val)

# 3. Never moves against the knob.
for val in (0.0, 20.0, 50.0, 80.0, 100.0):
    for knob in (0.0, 0.25, 0.5, 0.75, 1.0):
        for d in (-0.1, -0.02, 0.02, 0.1):
            k2 = knob + d
            if not 0.0 <= k2 <= 1.0:
                continue
            ps = ParamSet(
                [Param("x", val, 0, 100, "%.1f", None), Param("y", 0, 0, 1, "%.1f", None)],
                2,
                knob_mode=ParamSet.KNOB_SCALE,
            )
            ps.update_knobs((knob, 0.0))
            before = ps.params[0].val
            ps.update_knobs((k2, 0.0))
            got = ps.params[0].val
            if d > 0:
                ck(
                    got >= before - 1e-9,
                    "val fell on a rising knob: v%.0f k%.2f d%+.2f -> %.3f" % (val, knob, d, got),
                )
            else:
                ck(
                    got <= before + 1e-9,
                    "val rose on a falling knob: v%.0f k%.2f d%+.2f -> %.3f" % (val, knob, d, got),
                )

# 4. Both rails reachable from any mismatch.
for start in (0.0, 17.3, 50.0, 99.9):
    ps, p = mk(ParamSet.KNOB_SCALE, start)
    ck(
        abs(sweep(ps, p, 0.5, 1.0) - 100.0) < 0.5,
        "knob to max left val at %.3f (start %.1f)" % (p.val, start),
    )
    ps, p = mk(ParamSet.KNOB_SCALE, start)
    ck(
        abs(sweep(ps, p, 0.5, 0.0)) < 0.5,
        "knob to min left val at %.3f (start %.1f)" % (p.val, start),
    )

# 5. A turning knob is never dead: the whole point of SCALE over PICKUP.
ps, p = mk(ParamSet.KNOB_SCALE, 95.0)
ps.update_knobs((0.05, 0.0))
dead, v = 0, p.val
for i in range(1, 40):
    ps.update_knobs((0.05 + i * 0.02, 0.0))
    if p.val == v:
        dead += 1
    v = p.val
ck(dead == 0, "a turning knob did nothing on %d of 39 passes" % dead)

# 6. Value stays in range under a coarse sweep.
ps, p = mk(ParamSet.KNOB_SCALE, 99.0)
sweep(ps, p, 0.5, 1.0, steps=4)
ck(0.0 <= p.val <= 100.0, "val left its range: %.3f" % p.val)

# 7. A resting pot must not write. Its ADC jitter is a real movement to a
#    delta-based mode, and writing an envelope parameter rebuilds a
#    synthio.Envelope for every sounding note, so an untouched knob has
#    to cost nothing.
JITTER = 0.0013  # measured on a pico_test_synth pot, already filtered
_seed = [12345]


def rnd():
    """Deterministic LCG; `random` is not guaranteed on a bare port."""
    _seed[0] = (1103515245 * _seed[0] + 12345) % 2147483648
    return _seed[0] / 2147483648.0


ps, p = mk(ParamSet.KNOB_SCALE, 50.0)
writes, v = 0, p.val
for _ in range(2000):
    ps.update_knobs((0.5 + (rnd() * 2 - 1) * JITTER, 0.0))
    if p.val != v:
        writes += 1
    v = p.val
ck(writes == 0, "a resting pot wrote its param on %d of 2000 passes" % writes)

# 8. ...but movement under the deadband must accumulate, not vanish, or a
#    slow turn is thrown away one sample at a time.
ps, p = mk(ParamSet.KNOB_SCALE, 50.0)
before = p.val
for i in range(1, 51):  # 50 steps of 0.0005, all under the deadband
    ps.update_knobs((0.5 + i * 0.0005, 0.0))
ck(p.val > before, "sub-deadband movement vanished: %.3f -> %.3f" % (before, p.val))

# --- KNOB_PICKUP, unchanged --------------------------------------------

# 7. Dead until the knob crosses the value, then it tracks.
ps, p = mk(ParamSet.KNOB_PICKUP, 90.0)
ps.update_knobs((0.10, 0.0))
ck(p.val == 90.0, "pickup moved before the knob crossed: %.2f" % p.val)
sweep(ps, p, 0.10, 1.0)
ck(abs(p.val - 100.0) < 1.0, "pickup did not track after crossing: %.2f" % p.val)

if fails:
    print("FAIL (%d)" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_paramset: ok")
