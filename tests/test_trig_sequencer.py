# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""TrigSequencer checks: the missing step_millis init, the crashing
stop(), the aliasing set_pattern(), and the stall-recovery timing fix
(clamp, not arpeggiator.py's `// 2` damp -- that formula runs the
sequencer permanently slow; see CLAUDE.md/the trig_sequencer plan for
the algebra).

trig_sequencer.py imports only `time` (with a `supervisor.ticks_ms`
shim), so like test_arpeggiator.py this runs on a bare interpreter: no
stubs needed. ticks_ms is monkeypatched to a fake, settable clock so the
timing tests are exact and instant instead of racing real wall-clock
sleeps.

    python3 tests/test_trig_sequencer.py
    micropython tests/test_trig_sequencer.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/../synthtools")  # direct: skips synthtools/__init__

import trig_sequencer  # noqa: E402
from trig_sequencer import TrigSequencer  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


_now = [0]


def fake_ticks_ms():
    return _now[0]


def set_time(ms):
    _now[0] = ms


trig_sequencer.ticks_ms = fake_ticks_ms  # update()/start() call this by name,
# looked up in the module's globals at call time, so patching it here
# reaches every TrigSequencer instance regardless of when it was constructed

# --- construction: step_millis must exist before bpm is ever set -------

set_time(0)
seq = TrigSequencer(2, 4, 4)  # 2 trigs, 4 steps, 16th notes
ck(seq.step_millis == 0, "step_millis must be a real number right after "
   "construction, before bpm is ever assigned")
seq.start()
seq.update()  # must not raise AttributeError: step_millis

# --- bpm / step_millis ---------------------------------------------------

seq2 = TrigSequencer(2, 4, 4)
seq2.bpm = 120  # 16th notes at 120bpm = 125ms/step
ck(seq2.step_millis == 125.0, "120bpm 16th notes must be 125ms/step")
ck(seq2.bpm == 120, "bpm getter must round-trip the value just set")

# --- set_pattern(): must copy, not alias ---------------------------------

seq3 = TrigSequencer(2, 4, 4)
row0 = [1, 0, 1, 0]
row1 = [0, 1, 0, 1]
seq3.set_pattern([row0, row1])
row0[0] = 0  # mutate the caller's own list after the fact
ck(seq3.trigs[0] == [1, 0, 1, 0],
   "set_pattern() must copy each row; mutating the caller's list "
   "afterward must not change the sequencer's live pattern")
ck(seq3.trigs[0] is not row0, "set_pattern() must not alias the caller's row")

# --- stop(): must not raise, must reset -----------------------------------

seq4 = TrigSequencer(2, 4, 4, on_func=lambda t, d: None)
seq4.bpm = 120
seq4.start()
seq4.i = 2
seq4.stop()  # must not raise AttributeError: held_note
ck(seq4.playing is False, "stop() must turn playing off")
ck(seq4.i == 0, "stop() must reset i to 0")

# --- update(): steady state is driftless ----------------------------------

events = []


def on_func(t, d):
    events.append(t)


seq5 = TrigSequencer(1, 4, 4, on_func=on_func)
seq5.set_pattern([[1, 1, 1, 1]])
seq5.bpm = 120  # 125ms/step
set_time(0)
seq5.start()

ck_deadlines = []
for step in range(1, 6):
    set_time(step * 125)  # arrive exactly on time, every time
    seq5.update()
    ck_deadlines.append(seq5.next_millis)

ck(events == [0] * 5, "on-time steps must all fire")
ck(ck_deadlines == [125, 250, 375, 500, 625],
   "on-time deadlines must advance by exactly step_millis each step, "
   "with zero accumulated drift")

# --- update(): a stall resyncs instead of bursting ------------------------

events.clear()
seq6 = TrigSequencer(1, 4, 4, on_func=on_func)
seq6.set_pattern([[1, 1, 1, 1]])
seq6.bpm = 120  # 125ms/step
set_time(0)
seq6.start()
set_time(125)
seq6.update()  # on-time first step; next_millis == 125
events.clear()

set_time(900)  # a huge stall: 775ms past the 125ms deadline
seq6.update()
ck(events == [0], "a stall must fire the pending step exactly once, not a "
   "burst of catch-up triggers")
ck(seq6.next_millis == 900 + 125,
   "after a stall, next_millis must resync to now + step_millis rather "
   "than continuing to fall behind")

# a second immediate poll at the same instant must NOT fire again
events.clear()
seq6.update()
ck(events == [], "polling again before the resynced deadline must not fire")

if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_trig_sequencer: all checks passed")
