# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Arpeggiator checks; timing/sequencing logic plus a regression test
for the constructor bug fixed alongside this file: Arpeggiator.__init__
called `self.set_bpm(120)` with no rate, which overwrote self.rate with
set_bpm's own default (None) and raised TypeError on every construction.

arpeggiator.py imports only `time` (with a `supervisor.ticks_ms` shim), so
like test_patch.py this runs on a bare interpreter: no stubs needed.
ticks_ms is monkeypatched to a fake, settable clock so the timing tests are
exact and instant instead of racing real wall-clock sleeps.

    python3 tests/test_arpeggiator.py
    micropython tests/test_arpeggiator.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/../synthtools")  # direct: skips synthtools/__init__

import arpeggiator  # noqa: E402
from arpeggiator import Arpeggiator  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


_now = [0]


def fake_ticks_ms():
    return _now[0]


def set_time(ms):
    _now[0] = ms


arpeggiator.ticks_ms = fake_ticks_ms  # update()/start() call this by name,
# looked up in the module's globals at call time, so patching it here
# reaches every Arpeggiator instance regardless of when it was constructed

# --- construction: the bug this file guards against --------------------

set_time(0)
arp = Arpeggiator(4)  # rate=4 -> 16th notes; on_func/off_func default None
ck(arp.bpm == 120, "default bpm should be 120")
ck(arp.rate == 4,
   "rate must be the constructor's own arg, not dropped by the __init__ "
   "self-init call to set_bpm()")
ck(arp.step_millis == 60_000 / 4 / 120,
   "step_millis must be computed from the given rate; constructing an "
   "Arpeggiator must not raise TypeError")

arp.set_bpm(60, 1)  # quarter notes at 60bpm = exactly 1 step/sec
ck(arp.bpm == 60 and arp.rate == 1, "set_bpm must update both bpm and rate")
ck(arp.step_millis == 1000.0, "60bpm quarter notes must be 1000ms/step")

# --- add_note / del_note ------------------------------------------------

arp2 = Arpeggiator(4)
arp2.add_note(60)
arp2.add_note(64)
arp2.add_note(60)  # duplicate
ck(arp2.notes == [60, 64], "add_note must not add a note already present")

arp2.i = 0
arp2.add_note(67)
arp2.del_note(67)  # removes the LAST note; i=0 is still a valid index
ck(arp2.notes == [60, 64], "del_note must remove the given note")
ck(arp2.i == 0, "del_note must leave i alone when it is still in range")

arp2.i = 1
arp2.del_note(60)  # removes the FIRST note; i=1 now walks off the list
ck(arp2.notes == [64], "del_note must remove the given note")
ck(arp2.i == 0, "del_note must reset i to 0 once it is out of range")

# --- start() / stop() ---------------------------------------------------

set_time(1000)
stop_events = []
arp3 = Arpeggiator(4, on_func=lambda n: None,
                    off_func=lambda n: stop_events.append(n))
arp3.start()
ck(arp3.on is True, "start() must turn the arpeggiator on")
ck(arp3.next_millis == 1000, "start() must seed next_millis from ticks_ms()")

arp3.stop()
ck(arp3.on is False, "stop() must turn the arpeggiator off")
ck(stop_events == [None],
   "stop() calls off_func(held_note) unconditionally, even with nothing "
   "held; an off_func that doesn't tolerate None will raise here")

# --- update(): a full pass through a 3-note pattern, gate + octave -----

events = []


def on_func(n):
    events.append(("on", n))


def off_func(n):
    events.append(("off", n))


set_time(0)
arp4 = Arpeggiator(4, on_func, off_func)
arp4.set_bpm(120, 4)  # 125ms/step
arp4.notes = [60, 64, 67]
arp4.oct_range = 2  # so the wrap after one full pass is observable
arp4.start()


def advance(ms):
    """Move the fake clock to `ms` and run one update(), returning
    whatever events fired since the last advance()."""
    set_time(ms)
    arp4.update()
    got = list(events)
    events.clear()
    return got


# t=0: the first update() call after start() fires the first note
# immediately, since next_millis was seeded to the start time.
ck(advance(0) == [("on", 60)], "first update() at start time fires note 0")
ck(arp4.i == 1, "i must advance past the note just fired")
ck(arp4.held_note == 60, "held_note must be the note just fired")

# gate is 0.5 * 125ms = 62.5ms: before that, the note must stay held
ck(advance(60) == [], "must not release before gate time elapses")

# past the gate but before the next 125ms step: release only
ck(advance(70) == [("off", 60)], "must release once gate time has elapsed")
ck(arp4.held_note is None, "held_note must clear after release")

# the next step boundary: second note fires (held_note already None, so
# no release logic runs in this same call)
ck(advance(125) == [("on", 64)], "update() at the step boundary fires the next note")
ck(arp4.i == 2, "i must be 2 after the second note")

# release note 64 in its own call before the third step boundary, so the
# third note's on-event isn't muddied by a same-call release
ck(advance(200) == [("off", 64)], "release of the second note")

ck(advance(250) == [("on", 67)], "third note in the pattern")
ck(arp4.i == 0, "i must wrap back to 0 after the last note in the pattern")
ck(arp4.octave == 1,
   "completing a full pass must advance octave (oct_range=2 so it doesn't "
   "wrap back to 0 yet)")

ck(advance(325) == [("off", 67)], "release of the third note")

# fourth note: back to notes[0], now transposed up by oct_distance*octave
ck(advance(375) == [("on", 60 + 12)],
   "next pass must transpose by oct_distance * octave")
ck(arp4.i == 1, "i must advance normally within the transposed pass")

if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_arpeggiator: all checks passed")
