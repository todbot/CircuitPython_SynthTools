# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT

import time

from synth_setup import knobA
from synth_setup import synth as engine

from synthtools import Patch, WavetableSynth

wavetable_fname = "/wavetables/PLAITS02.WAV"  # from http://waveeditonline.com/

# fmt: off
patch1 = Patch(name="wavetable scan", synth_type="wavetable",
               wave_file=wavetable_fname, wave_pos=0,
               wave_lfo_rate=0.05, wave_lfo_shape="saw", wave_lfo_once=False)
# fmt: on

wt = WavetableSynth(engine, patch1)
wt.wave_pos_max = wt.num_waves - 1  # sweep across the whole wavetable

wt.note_on(48)

while True:
    # the wave-position LFO lives outside the synthio block graph; it has
    # to be pushed into the wavetable buffer by hand, as often as possible
    wt.update()
    wt.wave_lfo_rate = (knobA.value / 65535) * 0.25
    time.sleep(0.01)
