# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthtools_wavetable_simple.py -- one held note, its waveform swept
# across the whole wavetable by the wave-position LFO.
#
#   knobA  sweep rate (0 .. 0.25 Hz)
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

from synth_setup import knobA
from synth_setup import synth as engine

from synthtools import Patch, WavetableSynth

# fmt: off
patch = Patch(name="wavetable scan", synth_type="wavetable",
              wave_file="/wavetables/PLAITS02.WAV", wave_pos=0,
              wave_lfo_rate=0.05, wave_lfo_shape="saw", wave_lfo_once=False)
# fmt: on

wt = WavetableSynth(engine, patch)
wt.wave_pos_max = wt.num_waves - 1  # sweep the whole table

wt.note_on(48)

while True:
    wt.update()
    wt.wave_lfo_rate = (knobA.value / 65535) * 0.25
    time.sleep(0.01)
