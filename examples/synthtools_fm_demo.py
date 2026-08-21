# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT

import time

from synth_setup import synth as engine

from synthtools import FMSynth, Patch

# --- a classic FM patch: a bright, bell-ish DX-style tone ------------------
# fm_index is FM depth in bend units (octaves): 1.0 means the modulator
# swings the carrier pitch by a factor of 2 up and 2 down each cycle.
# fmt: off
patch1 = Patch(name="fm bell", synth_type="fm", wave="SIN",
               fm_wave="SIN", fm_ratio=2.0, fm_index=1.0,
               filt_type="LPF", filt_f=7000, filt_q=0.3,
               amp_env=[0.001, 1.0, 0.0, 0.8],
               fenv_amount=0, fenv_attack=0.01, fenv_release=0.3)
# fmt: on

synth = FMSynth(engine, patch1)

melody = (60, 64, 67, 72, 67, 64)
i = 0
while True:
    note = melody[i % len(melody)]
    synth.note_on(note, velocity=120)
    time.sleep(0.28)
    synth.note_off(note)
    time.sleep(0.03)
    i += 1

    # live FM: both are one write into a shared block, O(1) in polyphony.
    # fm_ratio is the modulator/carrier frequency ratio; integer ratios
    # give the steel-drum harmonic stacks, non-integer ones get inharmonic.
    if i % 16 == 0:
        synth.fm_ratio = 1.0 if synth.fm_ratio >= 2.0 else synth.fm_ratio + 1.0
    if i % 8 == 0:
        synth.fm_index = 2.0 if synth.fm_index == 0.5 else 0.5

    print(
        "fm_ratio: %3.1f  fm_index: %.1f  wave: %s  fm_wave: %s"
        % (synth.fm_ratio, synth.fm_index, synth.wave, synth.fm_wave)
    )
