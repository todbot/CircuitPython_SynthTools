# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT

import time

from synth_setup import synth as engine

from synthtools import FMSynth, Patch

# --- a classic FM patch: a bright, bell-ish DX-style tone ------------------
# fm_ratio is modulator cycles per carrier cycle -- MUST be an integer, or
# the baked waveform buzzes at its loop point (see fm_synth.py). fm_index is
# PM depth in radians: 0 = plain sine, 1-3 = classic FM, 5+ = harsh.
# fmt: off
patch1 = Patch(name="fm bell", synth_type="fm", wave="SIN",
               fm_ratio=2, fm_index=1.0,
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

    # live FM: each write rewrites the shared PM table in place, reaching
    # every voice using it, O(1) in polyphony. fm_ratio must stay an
    # integer -- non-integer ratios buzz at the waveform's loop point.
    if i % 16 == 0:
        synth.fm_ratio = 1 if synth.fm_ratio >= 3 else synth.fm_ratio + 1
    if i % 8 == 0:
        synth.fm_index = 2.0 if synth.fm_index == 0.5 else 0.5

    print("fm_ratio: %d  fm_index: %.1f  wave: %s" % (synth.fm_ratio, synth.fm_index, synth.wave))
