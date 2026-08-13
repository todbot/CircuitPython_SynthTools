# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT

import time
from synth_setup import synth as engine
from synthtools import Patch, SubtractiveSynth

# --- a patch, and a synth to put it on -----------------------------------
patch1 = Patch(name="fat bass", wave="ASAW", detune=1.004,
               filt_type="LPF", filt_f=800, filt_q=1.4,
               amp_env=[0.01, 0.1, 0.8, 0.4],
               vib_rate=5.5, vib_depth=0.0,
               # AHR filter envelope: cutoff swings 800 -> 3800 Hz and back
               fenv_amount=3000, fenv_attack=0.02, fenv_release=0.30,
               # a slow cyclic wobble on top of it (0 = off)
               filt_lfo_rate=0.4, filt_lfo_amount=0.3)

synth = SubtractiveSynth(engine, patch1)

# JSON round-trip 
patch_json = patch1.to_json()
print("patch as json:", patch_json)
patch1 = Patch.from_json(patch_json)

# --- play: arpeggio with a live filter sweep -----------------------------
arp = (36, 39, 43, 48)
i = 0
sweep = 0
while True:
    synth.note_on(arp[i % len(arp)], velocity=110)
    time.sleep(0.11)
    synth.note_off(arp[i % len(arp)])
    time.sleep(0.02)
    i += 1

    # live filter sweep: one write into a shared block, O(1) in polyphony.
    # deadband it -- a jittery pot otherwise writes on every single frame.
    sweep = (sweep + 7) % 100
    new_f = 100 + 30 * sweep
    if abs(new_f - synth.filt_f) > 5:
        synth.filt_f = new_f

    if i % 32 == 0:  # flip waveforms now and then
        synth.wave = "ASQU" if synth.wave == "ASAW" else "ASAW"

    print("filt_f: %5d  wave: %s" % (synth.filt_f, synth.wave))
    
    # all O(1), all reach sounding voices:
    #   synth.vib_depth = 0.006        # ~10 cents of vibrato
    #   synth.fenv_amount = 2000       # filter envelope depth in Hz
    #   synth.fenv_attack = 0.01       # a rate write, cheap on a knob
    #   synth.filt_lfo_amount = 600    # cyclic cutoff wobble, Hz
    #   synth.filt_vel = -1500         # hard playing CLOSES the filter
    #   synth.pitch_bend(0.05)

