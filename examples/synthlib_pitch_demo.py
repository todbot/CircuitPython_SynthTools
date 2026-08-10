# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthlib_pitch_demo.py -- synthlib's pitch modulation, audibly.
#
# Copy flat onto CIRCUITPY beside synth_setup.py and the synthlib/ package,
# then either rename it code.py or, from the serial REPL:
#
#     import synthlib_pitch_demo
#
# Everything that reaches note.bend, one parameter at a time, printing what
# it just changed. Companion to synthlib_fenv_demo.py.
#
# --- bend units --------------------------------------------------------
# 1.0 = ONE OCTAVE. So:
#     0.0833 = 1 semitone      0.01 = 12 cents      0.005 = 6 cents
# Musically, vibrato lives down at 0.005-0.02 and pitch envelopes want 0.03
# up to 1.0. The vibrato sections below run ~3x deeper than that on purpose:
# at a tasteful depth you cannot tell vib_delay is doing anything, because
# fading from nothing up to barely-anything is imperceptible.
#
# --- two kinds of note, and why ----------------------------------------
# Vibrato and vib_delay only read on SUSTAINED notes: a 1.5s fade-in cannot
# show itself on a 0.3s note, and at 5Hz you need most of a second just to
# hear the wobble as a wobble. Pitch envelopes are the opposite -- they are
# attack gestures, so they want short repeated notes.
# Hence hold() and play() below. Using one for the other's job is the
# fastest way to conclude a working parameter does nothing.
#
# --- the 30ms floor ----------------------------------------------------
# synthio updates blocks every 256 samples, ~5.8ms at 44.1kHz. A bend time
# under ~0.03s is only about five steps: you hear a click, not a bend.

import time

from synth_setup import synth as engine
from synthlib import Patch, SubtractiveSynth

patch = Patch(
    name="bender",
    wave="SAW",
    # ONE oscillator on purpose. Detune makes two oscillators beat against
    # each other, and that beating muddies exactly the small pitch movement
    # this demo is about.
    detune=1.0,
    # Filter open and static -- fenv_amount 0 -- so nothing here is the
    # filter moving. This demo is only about pitch.
    filt_type="LPF",
    filt_f=2600,
    filt_q=0.9,
    fenv_amount=0,
    # Vibrato: a shared LFO on note.bend. All three default to "off".
    vib_rate=5.0,
    vib_depth=0.0,
    vib_delay=0.0,
    # Pitch envelope: bends INTO the note from penv_amount to true pitch
    # over penv_time, then on note-off drifts OUT to penv_out_amount.
    # Both amounts default to 0 = off, and a voice with both off costs
    # nothing -- it reuses the shared bend node.
    penv_amount=0.0,
    penv_time=0.10,
    penv_out_amount=0.0,
    penv_out_time=0.20,
    # sustain high so held notes ring while vibrato does its thing
    amp_env=[0.01, 0.08, 0.75, 0.25],
)

synth = SubtractiveSynth(engine, patch)

# --- the short-note riff, for pitch-envelope gestures -------------------
# lifetime = gate + amp release = 0.28 + 0.25 = 0.53s against a 0.45s beat,
# so ~1.2 voices overlap. Keep it near 1: several voices at different
# points in the same gesture average into mush.
riff = (48, 55, 60, 55, 51, 58, 63, 58)
BEAT = 0.45
GATE = 0.62


def play(bars, label, velocity=110):
    """Short repeated notes -- for attack gestures."""
    print(label)
    for _ in range(bars):
        for note in riff:
            synth.note_on(note, velocity=velocity)
            time.sleep(BEAT * GATE)
            synth.note_off(note)
            time.sleep(BEAT * (1.0 - GATE))


def hold(label, secs=3.0, note=52, velocity=110):
    """One sustained note -- for vibrato, which needs time to be heard.

    Starts from silence every time, which matters: the vibrato fade ramp
    retriggers on note_on only when no notes are held.
    """
    print(label)
    synth.all_notes_off()
    time.sleep(0.25)
    synth.note_on(note, velocity=velocity)
    time.sleep(secs)
    synth.note_off(note)
    time.sleep(0.45)


while True:
    print()
    print("=== vibrato ===")

    # Depths here are deliberately WIDE. A tasteful 0.012 (~14 cents) is
    # what you would actually play, but it is too subtle to demonstrate
    # anything -- and it makes vib_delay look broken, because fading from
    # nothing up to barely-anything is imperceptible. Everything below is
    # exaggerated so the parameter is unmistakable; dial it back by ~3x for
    # real use.

    # 1. reference point: no pitch modulation at all
    synth.vib_depth = 0.0
    hold("vib_depth=0        -- dead straight, no movement")

    # 2. obvious vibrato. 0.04 is ~48 cents either side, half a semitone
    synth.vib_depth = 0.04
    hold("vib_depth=0.04     -- obvious vibrato at 5Hz (~48 cents)")

    # 3. rate only. Same depth, nearly twice the speed
    synth.vib_rate = 9.0
    hold("vib_rate=9         -- same depth, much faster")
    synth.vib_rate = 5.0

    # 4. depth only. 0.10 is ~120 cents -- a whole semitone each way
    synth.vib_depth = 0.10
    hold("vib_depth=0.10     -- a semitone each way, deliberately seasick")

    # 5. THE DELAY, as an A/B at a depth you cannot miss. Vibrato fades in
    #    over vib_delay seconds instead of arriving fully formed -- what a
    #    singer or a string player does.
    #
    #    The fade is a rate on a SHARED ramp, retriggered by note_on only
    #    when playing starts from silence, so adding a note to a held chord
    #    will not duck everyone's vibrato back to zero. hold() always
    #    starts from silence, so each of these retriggers.
    synth.vib_depth = 0.06
    synth.vib_delay = 0.0
    hold("vib_delay=0        -- A: vibrato present from the first instant",
         secs=2.5)
    synth.vib_delay = 2.0
    hold("vib_delay=2.0      -- B: dead straight for 2s, THEN it swells in",
         secs=5.0)

    # 6. and off again. Everything after this is the pitch ENVELOPE, which
    #    is also pitch movement -- so the vibrato has to be gone or the two
    #    are impossible to tell apart.
    synth.vib_delay = 0.0
    synth.vib_depth = 0.0
    print("vibrato OFF        -- everything below is the pitch envelope")
    time.sleep(1.0)

    print()
    print("=== pitch envelope: bending INTO the note ===")

    # 7. off, for comparison against what follows
    synth.penv_amount = 0.0
    play(1, "penv_amount=0      -- notes start exactly on pitch")

    # 8. plucked-string sharpness: a struck string starts slightly sharp
    #    and settles. 0.03 is ~36 cents, and 0.08s is ~14 block updates --
    #    fast, but comfortably above the ~0.03s click threshold.
    synth.penv_amount = 0.03
    synth.penv_time = 0.08
    play(1, "penv=+0.03 / 0.08s -- struck-string sharpness, settles quickly")

    # 9. negative = start FLAT and bend UP into pitch. Half an octave is a
    #    horn player scooping into the note, or a slide guitar.
    synth.penv_amount = -0.5
    synth.penv_time = 0.15
    play(1, "penv=-0.50 / 0.15s -- scoops UP into pitch from a fifth below")

    # 10. a full octave falling fast is not a bend any more, it is a drum.
    synth.penv_amount = 1.0
    synth.penv_time = 0.05
    play(1, "penv=+1.00 / 0.05s -- octave drop: reads as a tom, not a pitch")
    synth.penv_amount = 0.0
    synth.penv_time = 0.10

    print()
    print("=== pitch envelope: bending OUT on note-off ===")

    # 11. the release half. Needs the amp release to outlast penv_out_time
    #     or the voice is freed mid-bend and the gesture is cut short --
    #     the same trap fenv_release has.
    synth.release_time = 0.5
    synth.penv_out_amount = -0.4
    synth.penv_out_time = 0.35
    play(1, "penv_out=-0.40     -- sags away downward as each note releases")

    # 12. upward on release instead
    synth.penv_out_amount = 0.35
    play(1, "penv_out=+0.35     -- lifts away upward instead")
    synth.penv_out_amount = 0.0
    synth.release_time = 0.25

    print()
    print("=== everything at once, plus the wheel ===")

    # 13. all three pitch modulations summing on one bend graph
    synth.vib_depth = 0.05
    synth.vib_delay = 0.8
    synth.penv_amount = -0.25
    synth.penv_time = 0.12
    synth.penv_out_amount = -0.3
    synth.release_time = 0.5
    play(1, "vib + penv in + penv out -- all three on one bend graph")
    #     NOTE these are short notes, so the 0.8s vibrato fade barely gets
    #     going before each one ends. That is the point, not a fault:
    #     vib_delay is a sustained-note parameter.

    # 14. pitch_bend() is performance state, not patch state: one write
    #     into the shared block, so it moves every sounding voice at once.
    #     0.15 is about 180 cents, so nearly two semitones each way.
    print("pitch_bend sweep   -- the wheel, on top of everything else")
    synth.note_on(52, velocity=110)
    STEPS = 80
    for i in range(STEPS):
        p = 4.0 * i / STEPS          # 0 -> 4
        if p < 1.0:                  # up to +1
            b = p
        elif p < 3.0:                # +1 down through 0 to -1
            b = 2.0 - p
        else:                        # -1 back to 0
            b = p - 4.0
        synth.pitch_bend(0.15 * b)
        time.sleep(0.03)
    synth.pitch_bend(0.0)
    synth.note_off(52)
    time.sleep(0.6)

    synth.vib_depth = 0.0
    synth.vib_delay = 0.0
    synth.penv_amount = 0.0
    synth.penv_out_amount = 0.0
    synth.release_time = 0.25

    # Nothing above touched `patch`. To keep the current sound:
    #   synth.save_patch().save("/bender.json")   # needs storage.remount()
