# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""StepSequencer timing: on-time steps don't drift, a little lateness
stays on the grid, a stall resyncs instead of bursting catch-up steps, and
none of it breaks across ticks_ms()'s 2**29 wrap.

step_sequencer.py needs only adafruit_ticks, vendored unchanged in
tests/lib/, so this runs on a bare interpreter with a fake clock.

    python3 tests/test_step_sequencer.py
    micropython tests/test_step_sequencer.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/../synthtools")  # direct: skips synthtools/__init__
sys.path.insert(0, _D + "/lib")

import step_sequencer  # noqa: E402
from step_sequencer import StepSequencer  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


_now = [0]
WRAP = 1 << 29
step_sequencer.ticks_ms = lambda: _now[0] % WRAP  # wraps like the real one

ons = []
offs = []


def make(bpm=120, t0=0):
    ons.clear()
    offs.clear()
    seq = StepSequencer(4, 4, on_func=lambda *a: ons.append(_now[0]),
                        off_func=lambda *a: offs.append(_now[0]))
    seq.bpm = bpm  # 120: 125 ms/step
    _now[0] = t0
    seq.start()
    return seq


def run_until(seq, end, stall_at=None, stall=0):
    while _now[0] < end:
        _now[0] += stall if _now[0] == stall_at else 1
        seq.update()


# --- on time: no drift ------------------------------------------------------
seq = make()
run_until(seq, 1000)
ck(ons == [1, 125, 250, 375, 500, 625, 750, 875, 1000],
   "on-time steps must land every 125 ms, got %r" % ons)

# --- a little late: the next step stays on the grid -------------------------
seq = make()
run_until(seq, 400, stall_at=124, stall=30)  # step 2 fires 29 ms late
ck(ons[1] == 154 and ons[2] == 250,
   "a late step must not push the grid back, got %r" % ons)

# --- a stall: one late step, then a fresh grid, no burst --------------------
seq = make()
run_until(seq, 1200, stall_at=500, stall=300)
gaps = [b - a for a, b in zip(ons, ons[1:])]
ck(min(gaps) >= 124, "a stall must not burst catch-up steps, gaps %r" % gaps)
ck(ons[5] == 800 and ons[6] == 925,
   "after a stall the grid must restart from the late step, got %r" % ons)

# --- the gate still releases each step -------------------------------------
ck(len(offs) >= len(ons) - 1, "every step but the last must note_off, %r" % offs)

# --- across the wrap: no stop, no hiccup ------------------------------------
# supervisor.ticks_ms() first wraps ~65 s after power-on
seq = make(t0=WRAP - 600)
run_until(seq, WRAP + 1000)
gaps = [b - a for a, b in zip(ons, ons[1:])]
ck(len(ons) == 13 and min(gaps[1:]) == max(gaps) == 125,  # [0] is the start
   "steps must keep coming every 125 ms across the wrap, got gaps %r" % gaps)
ck(len(offs) == len(ons), "gates must keep releasing across the wrap, got %d" % len(offs))

# --- a tempo that isn't whole ms doesn't drift -------------------------------
seq = make(bpm=113)  # 132.743... ms/step
run_until(seq, 100 * 132.743 + 1)
ck(abs(ons[100] - 100 * 60_000 / 4 / 113) < 1,
   "100 steps at 113 bpm must land within 1 ms of 13274 ms, got %r" % ons[100])
ck(all(isinstance(t, int) for t in (seq.next_millis, seq.gate_off_millis)),
   "tick math must stay int; a 30-bit float can't hold a tick near 2**29")

# --- trigger() is the same step update() plays, on the owner's clock ---------
seq = make()
seq.external_clock = True
played = []
seq.on_func = lambda *a: played.append(seq.i)
run_until(seq, 500)
ck(played == [], "external_clock: update() must not step on its own, got %r" % played)
seq.trigger()
seq.trigger()
ck(played == [0, 1] and seq.i == 2, "trigger() must play then advance, got %r" % played)
offs.clear()
_now[0] += 200
seq.update()
ck(len(offs) == 1, "external_clock: update() must still release the gate, %r" % offs)

# --- pause keeps position, stop rewinds, neither double-releases ------------
seq = make()
run_until(seq, 130)  # past step 2's start, gate still open
offs.clear()
seq.pause()
ck(seq.i == 2 and not seq.playing, "pause() must keep position, got %r" % seq.i)
ck(len(offs) == 1, "pause() must release the held note, %r" % offs)
seq.start()
_now[0] += 1
seq.update()
ck(len(offs) == 1, "start() after pause() must not note_off again, %r" % offs)
offs.clear()
seq.stop()
ck(seq.i == 0 and len(offs) == 1, "stop() must rewind and release, %r %r" % (seq.i, offs))
seq.start()
_now[0] += 1
seq.update()
ck(len(offs) == 1, "start() after stop() must not note_off again, %r" % offs)

# --- shrinking step_count wraps instead of playing a stale step --------------
seq = make()
seq.i = 3
seq.step_count = 2
seq.trigger()
ck(seq.i == 1, "a shrunk step_count must wrap i before playing, got %r" % seq.i)

# --- catch_up_steps: a stall delays steps instead of losing them -------------
seq = make()
seq.catch_up_steps = 8
run_until(seq, 1000, stall_at=500, stall=300)
ck(len(ons) == 9, "catch-up must play every step despite the stall, got %r" % ons)
ck(ons[-1] == 1000, "catch-up must return to the grid, got %r" % ons)
seq = make()
seq.catch_up_steps = 1
run_until(seq, 1500, stall_at=500, stall=500)
gaps = [b - a for a, b in zip(ons, ons[1:])]
ck(min(gaps) >= 124, "a stall past catch_up_steps must resync, gaps %r" % gaps)

if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_step_sequencer: all checks passed")
