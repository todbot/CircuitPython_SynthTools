# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# TrigSequencer's timing fix, checked against REAL supervisor.ticks_ms()
# jitter. tests/test_trig_sequencer.py proves the arithmetic against a
# fake, settable clock; this proves it holds up on the actual target MCU:
# real polling jitter in the steady state, and a real time.sleep() stall.
#
# Needs synthtools/ on the device. No audio, no synth_setup.py: this is
# pure polling/timing logic, same shape as test_display_cost.py.
#
#     PORT=$(ls /dev/tty.usbmodem* | head -1)
#     mkdir -p /Volumes/CIRCUITPY/synthtools
#     cp synthtools/*.py /Volumes/CIRCUITPY/synthtools/
#     dot_clean -m /Volumes/CIRCUITPY/
#     python3 tests/hw/run_on_device.py tests/hw/test_trig_sequencer_timing.py \
#             --port "$PORT" --timeout 60

import time

from supervisor import ticks_ms

from synthtools.trig_sequencer import TrigSequencer

fails = []


def ck(cond, msg):
    print(("  ok  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


print("--- construction: step_millis must exist before bpm is set --------")
seq = TrigSequencer(1, 4, 4, on_func=lambda t, d: None)
ck(seq.step_millis == 0, "step_millis must be 0 right after construction")
seq.start()
seq.update()  # must not raise AttributeError: step_millis
ck(True, "update() before bpm is ever assigned must not raise")

print("--- steady state: real ticks_ms() jitter, no induced stall --------")
events = []


def on_func(t, d):
    events.append(ticks_ms())


N = 40
seq2 = TrigSequencer(1, 4, 4, on_func=on_func)
seq2.set_pattern([[1, 1, 1, 1]])
seq2.bpm = 480  # 16th notes at 480bpm ~= 31.25ms/step: fast, exercises polling
step_millis = seq2.step_millis
seq2.start()

deadline = ticks_ms() + 5000  # hard stop so a regression can't hang the board
while len(events) < N and ticks_ms() < deadline:
    seq2.update()

ck(len(events) == N, "must fire all %d steps within the timeout (got %d)" % (N, len(events)))
if len(events) == N:
    span = events[-1] - events[0]
    want = (N - 1) * step_millis
    err = span - want
    print(
        "      span=%dms want=%.1fms err=%.1fms (%.2f%%)"
        % (span, want, err, 100.0 * err / want)
    )
    # generous tolerance: real polling jitter, not a fake clock
    ck(
        abs(err) < 0.25 * want,
        "steady-state timing must not drift by more than 25%% over %d steps "
        "(err=%.1fms of %.1fms)" % (N, err, want),
    )

print("--- induced stall: one late poll must not burst-fire ---------------")
events.clear()
seq3 = TrigSequencer(1, 4, 4, on_func=on_func)
seq3.set_pattern([[1, 1, 1, 1]])
seq3.bpm = 480
step_millis = seq3.step_millis
seq3.start()

# get one on-time firing in first, so next_millis is a real deadline rather
# than the start-time seed
deadline = ticks_ms() + 2000
while len(events) < 1 and ticks_ms() < deadline:
    seq3.update()
events.clear()

time.sleep(step_millis * 5 / 1000.0)  # sleep well past several step deadlines
before = ticks_ms()
seq3.update()  # the first poll after the stall
ck(
    len(events) == 1,
    "a stall must fire the pending step exactly once, not a burst "
    "(got %d events)" % len(events),
)
ck(
    seq3.next_millis >= before,
    "after a stall, next_millis must resync to at or after the poll time, "
    "not stay stuck in the past",
)

# a second immediate poll must not fire again
events.clear()
seq3.update()
ck(len(events) == 0, "polling again immediately after the resync must not fire")

print("--- stop() must not raise -------------------------------------------")
seq4 = TrigSequencer(1, 4, 4, on_func=lambda t, d: None)
seq4.bpm = 120
seq4.start()
seq4.i = 2
seq4.stop()
ck(seq4.playing is False, "stop() must turn playing off")
ck(seq4.i == 0, "stop() must reset i to 0")

print()
print("FAILURES: %d" % len(fails))
for f in fails:
    print("  -", f)
print("DONE")
