# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthlib_fenv_demo.py -- the synthlib AHR filter envelope, audibly.
#
# Copy flat onto CIRCUITPY beside synth_setup.py and the synthlib/ package,
# then either rename it code.py or, from the serial REPL:
#
#     import synthlib_fenv_demo
#
# It plays one bass riff over and over, changing a single filter-envelope
# parameter every few bars and printing what it just changed, so you can
# hear each one on its own.

import time

from synth_setup import synth as engine
from synthlib import Patch, SubtractiveSynth

# --- a patch built around the filter envelope ---------------------------
patch = Patch(
    name="squelch",
    wave="SAW",
    detune=1.004,
    # A filter has to exist before an envelope can sweep it. filt_f is the
    # resting cutoff, i.e. the FLOOR the envelope rises from and falls back
    # to -- keep it low and let the envelope supply the brightness.
    filt_type="LPF",
    filt_f=350,
    filt_q=1.6,
    # The envelope itself. fenv_amount is Hz ABOVE filt_f, and it defaults
    # to 0, which switches the envelope off entirely -- it is the one field
    # you cannot leave out.
    fenv_amount=4000,
    fenv_attack=0.02,
    fenv_release=0.30,
    fenv_curve=1,
    # A cyclic LFO on the same cutoff, summed alongside the envelope.
    # 0 amount = off.
    filt_lfo_rate=0.4,
    filt_lfo_amount=0,
    # Velocity: both default to 0, meaning "velocity changes nothing".
    # filt_vel is signed -- negative means hard playing closes the filter.
    filt_vel=0,
    fenv_vel=0.0,
    # NOTE the amp release (0.5) outlasts fenv_release (0.30). The filter
    # envelope only runs while the note is alive, so a short amp release
    # silently cuts the sweep short.
    amp_env=[0.005, 0.08, 0.7, 0.5],
)

synth = SubtractiveSynth(engine, patch)

riff = (36, 36, 48, 36, 43, 36, 46, 36)
BEAT = 0.16


def play(bars, label, velocity=110):
    """Play the riff `bars` times so a change has time to sink in."""
    print(label)
    for _ in range(bars):
        for step, note in enumerate(riff):
            # every fourth note softer, so velocity settings are audible
            vel = velocity if step % 4 else max(20, velocity - 70)
            synth.note_on(note, velocity=vel)
            time.sleep(BEAT * 0.6)
            synth.note_off(note)
            time.sleep(BEAT * 0.4)


while True:
    # 1. the envelope switched off: flat, dull, no movement at all
    synth.fenv_amount = 0
    play(2, "fenv_amount=0     -- envelope off, static filter")

    # 2. switched on: the classic filter pluck
    synth.fenv_amount = 4000
    play(2, "fenv_amount=4000  -- sweeps 350 -> 4350 Hz and back")

    # 3. slower attack: the sweep becomes a swell rather than a click
    synth.fenv_attack = 0.25
    play(2, "fenv_attack=0.25  -- slow rise, a swell not a pluck")
    synth.fenv_attack = 0.02

    # 4. longer release: the tail rings on after the key is up
    synth.fenv_release = 0.45
    play(2, "fenv_release=0.45 -- long tail (amp release caps this at 0.5)")
    synth.fenv_release = 0.30

    # 5. curve: 1 is linear, 2 starts slow and finishes fast
    synth.fenv_curve = 2
    play(2, "fenv_curve=2      -- squared rise, slower off the mark")
    synth.fenv_curve = 1

    # 6. the cyclic LFO: the fourth modulation on the same cutoff, summed
    #    with the envelope rather than replacing it
    synth.filt_lfo_amount = 900
    play(2, "filt_lfo_amount=900 -- slow wobble underneath the envelope")
    synth.filt_lfo_amount = 0

    # 7. velocity opens the cutoff itself. Turning it on from 0 only affects
    #    NEW notes (at 0 no per-voice node is built at all), but once a voice
    #    has one, the knob keeps reaching it.
    synth.filt_vel = 2500
    play(2, "filt_vel=2500     -- soft notes darker (every 4th is soft)")
    synth.filt_vel = -2500
    play(2, "filt_vel=-2500    -- inverted: hard notes darker")
    synth.filt_vel = 0

    # 8. velocity scales how far the envelope sweeps
    synth.fenv_vel = 1.0
    play(2, "fenv_vel=1.0      -- soft notes sweep less far")
    synth.fenv_vel = 0.0

    # Nothing above was written to `patch`. To keep the current sound:
    #   synth.save_patch().save("/squelch.json")   # needs storage.remount()
