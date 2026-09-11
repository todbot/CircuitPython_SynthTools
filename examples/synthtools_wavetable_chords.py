# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthtools_wavetable_chords.py -- WavetableSynth playing a five-note
# chord progression, the wavetable swept under it, with knobB A/B-ing the
# polyphony headroom fix.
#
#   knobA  wave-position sweep rate
#   knobB  left half  = RAW   (WT_HEADROOM 1.0, mixer 0.25): synthio's
#                              mix-bus limiter crunches every chord
#          right half = FIXED (WT_HEADROOM 0.5 + mixer 0.5 makeup):
#                              same loudness, chords stay clean
#
# Board note: wt.update() blends the shared wave buffer in place (~1.5 ms,
# the table is preloaded, no file I/O). The risk is not that cost but a
# stop-the-world GC pause: WavetableSynth carries a big resident heap (the
# ~32 KB table + the synthio block graph per voice), so gc.collect() is
# ~7-11 ms here vs ~2 ms for a bare one-Note scan. synth_setup.py runs
# rp2040 at mono / 4096 (~46 ms refill deadline); measured, this
# progression + sweep never missed a refill there (worst ~18 ms). At the
# stereo / 2048 config (other platforms, and pico_test_synth.Hardware) it
# misses ~10% of passes. So: big buffer, light main loop, or an rp2350.

import microcontroller

microcontroller.cpu.frequency = 200_000_000

import time

from synth_setup import knobA, knobB, mixer
from synth_setup import synth as engine

from synthtools import Patch, WavetableSynth

# fmt: off
patch = Patch(name="wavetable pad", synth_type="wavetable",
              wave_file="/wavetables/BRAIDS02.WAV",
              wave_pos=0, wave_lfo_rate=0.04, wave_lfo_range=63,
              #wave_lfo_shape="saw", wave_lfo_once=False,
              amp_env=[0.06, 0.0, 1.0, 0.3])
# fmt: on

wt = WavetableSynth(engine, patch)

progression = (
    (45, 52, 60, 64),  # Am, had 57
    (41, 48, 57, 60),  # Fmaj7, had 53
    (48, 52, 59, 62),  # Cmaj7, had 55
    (43, 50, 59, 64),  # G, had 50
)


def apply_mode(fixed):
    WavetableSynth.WT_HEADROOM = 0.5 if fixed else 1.0
    mixer.voice[0].level = 0.5 if fixed else 0.25
    print("mode:", "FIXED" if fixed else "RAW")


fixed = knobB.value > 32768
apply_mode(fixed)

step = 0
playing = False
next_chord = time.monotonic()

while True:
    wt.update()
    wt.wave_lfo_rate = (knobA.value / 65535) * 0.1

    want_fixed = knobB.value > 32768
    if want_fixed != fixed:
        fixed = want_fixed
        apply_mode(fixed)

    now = time.monotonic()
    if now >= next_chord:
        if playing:
            wt.all_notes_off()
            playing = False
            next_chord = now + 0.4
        else:
            for note in progression[step % len(progression)]:
                wt.note_on(note)
            playing = True
            step += 1
            next_chord = now + 1.4

    time.sleep(0.012)
