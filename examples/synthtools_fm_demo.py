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

# `wave` only sounds while FM is off (fm_index == 0): the baked FM table is
# always a sine carrier, so there's no "wave" to pick while FM is on. Every
# 16 notes this demo drops fm_index to 0 for a 16-note break and steps
# through this list, so you hear the plain-oscillator fallback too.
break_waves = ("SIN", "SAW", "SQU", "ASAW")
wave_i = 0

melody = (60, 64, 67, 72, 67, 64)
i = 0
while True:
    note = melody[i % len(melody)]
    synth.note_on(note, velocity=120)
    time.sleep(0.28)
    synth.note_off(note)
    time.sleep(0.03)
    i += 1

    # 32-note cycle: 16 notes of FM bell, 16 notes of plain oscillator.
    segment = i % 32
    if segment == 16:
        synth.fm_index = 0.0  # FM off; wave takes over for this break
        synth.wave = break_waves[wave_i % len(break_waves)]
        wave_i += 1
    elif segment < 16:
        # live FM: each write rewrites the shared PM table in place, reaching
        # every voice using it, O(1) in polyphony. fm_ratio must stay an
        # integer -- non-integer ratios buzz at the waveform's loop point.
        # fm_index was left at 0 by the break above, so the toggle below
        # also turns FM back on again at segment 0.
        if i % 16 == 0:
            synth.fm_ratio = 1 if synth.fm_ratio >= 3 else synth.fm_ratio + 1
        if i % 8 == 0:
            synth.fm_index = 2.0 if synth.fm_index == 0.5 else 0.5

    # `wave` is only what's actually sounding while FM is off -- once FM
    # turns back on, `synth.wave` still reads back the last break's name
    # even though it's no longer in use, so don't print it as if it were.
    if synth.fm_index:
        print("FM bell  fm_ratio: %d  fm_index: %.1f" % (synth.fm_ratio, synth.fm_index))
    else:
        print("plain osc  wave: %s" % synth.wave)
