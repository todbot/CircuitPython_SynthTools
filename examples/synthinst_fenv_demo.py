# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthinst_fenv_demo.py -- the synth_tools AHR filter envelope, audibly.
#
# Copy flat onto CIRCUITPY beside synth_setup.py and the synth_tools/ package,
# then either rename it code.py or, from the serial REPL:
#
#     import synthinst_fenv_demo
#
# It plays one bass riff over and over, changing a single filter-envelope
# parameter every few bars and printing what it just changed, so you can
# hear each one on its own.

import time

from synth_setup import synth as engine
from synth_tools import Patch, SubtractiveSynth

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
    # 0.05s, not 0.02s. synthio updates blocks every 256 samples (~5.8ms at
    # 44.1kHz), so a 0.02s attack is barely THREE steps -- you hear a click,
    # not a sweep. Anything you want to hear as movement needs to span a few
    # dozen updates.
    fenv_attack=0.05,
    fenv_release=0.22,
    fenv_curve=1,
    # A cyclic LFO on the same cutoff, summed alongside the envelope.
    # 0 amount = off.
    filt_lfo_rate=0.4,
    filt_lfo_amount=0,
    # Velocity: both default to 0, meaning "velocity changes nothing".
    # filt_vel is signed -- negative means hard playing closes the filter.
    filt_vel=0,
    fenv_vel=0.0,
    # The amp release must OUTLAST fenv_release, because the filter envelope
    # only runs while the note is alive -- a short amp release silently cuts
    # the sweep short. But not by much: a long amp tail piles voices on top
    # of each other, and four overlapping sweeps at different points average
    # out into a constant brightness. 0.22 against fenv_release 0.22 keeps
    # roughly one voice sounding at a time.
    amp_env=[0.005, 0.06, 0.6, 0.22],
)

synth = SubtractiveSynth(engine, patch)

riff = (36, 36, 48, 36, 43, 36, 46, 36)

# Slow, and with a long gate. Two reasons, both of which make or break whether
# any of this is audible:
#   1. AHR holds at PEAK for as long as the key is down, so the only movement
#      during the loud part of a note is the attack. The note has to be long
#      enough to contain it -- a 0.10s note cannot show off a 0.25s attack, it
#      just sounds duller because the sweep never finishes.
#   2. note lifetime / BEAT = how many voices overlap. At BEAT 0.16 with a 0.5s
#      amp release that was 3.7 voices, each at a different point in its sweep,
#      which averages to a wash. Here it is ~1.1.
BEAT = 0.45
GATE = 0.62          # fraction of the beat the key is held down


def play(bars, label, velocity=110):
    """Play the riff `bars` times so a change has time to sink in."""
    print(label)
    for _ in range(bars):
        for step, note in enumerate(riff):
            # every fourth note softer, so velocity settings are audible
            vel = velocity if step % 4 else max(10, velocity - 70)
            synth.note_on(note, velocity=vel)
            time.sleep(BEAT * GATE)
            synth.note_off(note)
            time.sleep(BEAT * (1.0 - GATE))


while True:
    # 1. the envelope switched off: flat, dull, no movement at all
    synth.fenv_amount = 0
    play(1, "fenv_amount=0     -- envelope off, static filter")

    # 2. switched on: the classic filter pluck
    synth.fenv_amount = 4000
    play(1, "fenv_amount=4000  -- sweeps 350 -> 4350 Hz and back")

    # 3. slower attack: the sweep becomes a swell rather than a pluck. This
    #    only reads because the key is held 0.28s -- longer than the attack.
    #    Ask for a 0.25s swell on a 0.10s note and you just get a duller note.
    synth.fenv_attack = 0.25
    play(1, "fenv_attack=0.25  -- slow rise, a swell not a pluck")
    synth.fenv_attack = 0.05

    # 4. longer release: the tail rings on after the key is up. The amp
    #    release has to be raised WITH it -- the filter envelope stops dead
    #    when the voice is freed, so a 0.45s sweep under a 0.22s amp release
    #    is silently truncated to 0.22s and sounds like nothing changed.
    synth.release_time = 0.5
    synth.fenv_release = 0.45
    play(1, "fenv_release=0.45 -- long tail (amp release raised to match)")
    synth.fenv_release = 0.22
    synth.release_time = 0.22

    # 5. curve: 1 is a straight line up and down. 2 is the analog feel --
    #    the rise snaps up and eases into the peak, and the release drops
    #    fast then tails off (15% of its height by halfway, vs 50% linear).
    synth.fenv_curve = 2
    play(1, "fenv_curve=2      -- snappy rise, decaying tail on release")
    synth.fenv_curve = 3
    play(1, "fenv_curve=3      -- more so: nearly a pluck")
    synth.fenv_curve = 1

    # 6. the cyclic LFO: the fourth modulation on the same cutoff. It SUMS
    #    with the envelope, which is exactly why it needs its own moment --
    #    with fenv_amount at 4000 the cutoff sits at 4-5kHz, and a 900Hz
    #    wobble up there is 0.39 of an octave on a 65Hz saw that has almost
    #    no energy left above 4kHz. Inaudible, despite being a big number.
    #    Hz span is not audible span; octaves are, and only where there are
    #    harmonics to remove.
    #
    #    So: envelope off, and put the LFO somewhere it can be heard. The
    #    LFO is ADDITIVE -- filt_f is the floor and it opens 0..amount
    #    upward, it does not swing either side of filt_f. So to get a wide
    #    sweep, put the floor LOW and let the amount do the work.
    #    Note the rate too: 0.4Hz is a 2.5s cycle, slower than one note, so
    #    it drifts across the phrase instead of wobbling within a note.
    synth.fenv_amount = 0
    synth.filt_f = 120
    synth.filt_lfo_amount = 1800     # 120..1920 Hz -- 4 octaves
    synth.filt_lfo_rate = 3.0        # ~1.5 cycles per note
    play(1, "filt_lfo 1800 @ 3Hz -- envelope off, LFO alone: 120..1920 Hz")

    #    ...and now both at once, with the envelope kept small enough that
    #    the LFO still reads on top of it. It reads less at the envelope's
    #    peak than between notes -- that is the additive Hz bus being
    #    honest, not a bug: the same Hz depth is fewer octaves higher up.
    synth.filt_f = 250
    synth.fenv_amount = 200
    synth.filt_lfo_amount = 1800
    synth.filt_lfo_rate = 5.0
    play(1, "filt_lfo + fenv     -- the two summing on one cutoff")
    synth.filt_lfo_amount = 0
    synth.filt_lfo_rate = 0.4
    synth.filt_f = 350
    synth.fenv_amount = 4000

    # 7. velocity opens the cutoff itself. Turning it on from 0 only affects
    #    NEW notes (at 0 no per-voice node is built at all), but once a voice
    #    has one, the knob keeps reaching it.
    synth.filt_vel = 2500
    play(1, "filt_vel=2500     -- soft notes darker (every 4th is soft)")
    synth.filt_vel = -2500
    play(1, "filt_vel=-2500    -- inverted: hard notes darker")
    synth.filt_vel = 0

    # 8. velocity scales how far the envelope sweeps
    synth.fenv_vel = 1.0
    play(1, "fenv_vel=1.0      -- soft notes sweep less far")
    synth.fenv_vel = 0.0

    # Nothing above was written to `patch`. To keep the current sound:
    #   synth.save_patch().save("/squelch.json")   # needs storage.remount()
