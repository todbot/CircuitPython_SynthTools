# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# Play scales and diatonic chords with synthtools.harmony.
#
# A Scale is a root note plus a set of semitone offsets; index it by
# degree and it wraps with octave shifts, so `scale.degree(i)` maps a row
# of 8 pads straight onto any scale. `scale.chord(degree, shape)` stacks
# the chord in-key, so the quality follows the mode for free: the triad
# on degree 0 of a major scale is major, on degree 1 it is minor.
#
# It prints every note and chord it plays, so it also reads as a plain
# console demo with the mixer down.

import time

from synth_setup import synth as engine

from synthtools import Patch, SubtractiveSynth
from synthtools.harmony import DIATONIC_SHAPE_NAMES, Scale, note_name

# fmt: off
patch = Patch(name="harmony demo", wave="TRI",
              amp_env=[0.01, 0.15, 0.5, 0.25],
              filt_type="LPF", filt_f=2600, filt_q=0.7)
# fmt: on
synth = SubtractiveSynth(engine, patch)

# (key note, scale name) -- MIDI 48 is C3
PROGRESSION = (
    (48, "major"),
    (45, "minor"),
    (50, "dorian"),
    (43, "mixolydian"),
    (48, "major_pentatonic"),
)
CHORD_SHAPES = ("triad", "7th", "9th", "spread")
# roman numeral for the degree the chord is built on
DEGREES = ((0, "I"), (3, "IV"), (4, "V"), (5, "vi"))


def play(notes, secs):
    for n in notes:
        synth.note_on(n, velocity=100)
    time.sleep(secs)
    for n in notes:
        synth.note_off(n)
    time.sleep(0.06)


while True:
    for root, scale_name in PROGRESSION:
        scale = Scale(root=root, name=scale_name)
        print("\n--- %s %s ---" % (note_name(root, with_octave=False), scale.name))

        # walk the scale, one note per pad
        line = " ".join(note_name(scale.degree(i)) for i in range(scale.size + 1))
        print("scale:", line)
        for i in range(scale.size + 1):
            play([scale.degree(i)], 0.16)
        time.sleep(0.3)

        # diatonic chords on a few degrees, through a few voicings
        for degree, roman in DEGREES:
            for shape in CHORD_SHAPES:
                notes = scale.chord(degree, shape)
                print("  %-3s %-6s %s" % (roman, shape, [note_name(n) for n in notes]))
                play(notes, 0.4)
            time.sleep(0.15)

    print("\n(all %d DIATONIC_SHAPES: %s)" % (len(DIATONIC_SHAPE_NAMES), DIATONIC_SHAPE_NAMES))
