# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthtools_wavetable_simple.py -- one held note, its waveform swept
# across the whole wavetable by the wave-position LFO.
#
# Copy flat onto CIRCUITPY next to synth_setup.py and the synthtools/ package,
# also copy the "wavetables" directory over.
# then either rename this file code.py or, from the serial REPL:
#
#     import synthtools_swarm_demo
#
# The controls:
#
#   knobA  wave position (0-num_waves-1)
#   knobB  wave LFO range (0-num_waves-1)
#
# wt.update() pushes the LFO into the shared wave buffer every loop: it
# has to run from the main loop because Note.waveform is a plain buffer,
# not a synthio block. Each write is a ~1.5 ms in-place ulab blend (the
# table is preloaded, no file read). synth_setup.py runs rp2040 at
# mono / 4096 (~46 ms refill deadline), where one held note plus the sweep
# has wide margin. It gets tight at stereo / 2048 (other platforms, and
# pico_test_synth.Hardware), where a GC pause can miss a refill; see
# synthtools_wavetable_chords.py for the measured numbers.

import time

from synth_setup import knobA, knobB
from synth_setup import synth as engine

from synthtools import Patch, WavetableSynth

# fmt: off
patch = Patch(name="wavetable scan", synth_type="wavetable",
              wave_file="/wavetables/PLAITS02.WAV",
              wave_pos=10, wave_lfo_rate=0.3, wave_lfo_range=3)
# fmt: on

wt = WavetableSynth(engine, patch)
wt.note_on(48)
num_waves = wt.num_waves

rate_choices = (0.05, 0.1, 0.3, 0.5, 1.0)
rate_i = 0
while True:
    wt.update()
    rate = rate_choices[rate_i]
    rate_i = int(time.monotonic() / 5 % len(rate_choices))
    wt.wave_pos = (knobA.value / 65535) * num_waves
    wt.wave_lfo_range = (knobB.value / 65535) * num_waves
    wt.wave_lfo_rate = rate
    print("rate:%.2f wave_pos:%.1f wave_lfo_range:%.1f" % (rate, wt.wave_pos, wt.wave_lfo_range))
    time.sleep(0.05)
