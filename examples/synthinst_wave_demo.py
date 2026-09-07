# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthinst_wave_demo.py -- play waves from waves.py, back to back,
# each played as a short arpeggio with and without oscillator detune.
#
# Copy flat onto CIRCUITPY beside synth_setup.py and the synthtools/
# package (plus arpeggiator.py, also copied flat), then either rename it
# code.py or, from the serial REPL:
#
#     import synthinst_wave_demo
#
# filt_type=None (no filter at all) on purpose: this demo is about
# telling the OSCILLATOR waveforms apart, and a filter would flatten
# exactly the harmonic differences (especially the two hand-drawn "analog"
# waves vs. the plain formula ones) that are the point of listening.
#
# The arpeggio itself never stops: only `synth.wave` and `synth.detune`
# change underneath it. Both are live properties
# (see SubtractiveSynth.wave/.detune in subtractive_synth.py) that only
# take effect on the arpeggiator's NEXT note-on, so the swap is always
# clean: no click mid-note.

import time

from arpeggiator import Arpeggiator
from synth_setup import synth as engine

from synthtools import Patch, SubtractiveSynth
from synthtools.waves import wave_names

DURATION = 3.0  # seconds per wave
# DETUNE = 1.01  # ~17 cents: clearly audible in a 3s clip, still musical
DETUNE = 1.004

patch = Patch(
    name="wavedemo",
    wave="SAW",
    detune=1.0,
    filt_type=None,
    # Short and percussive: the arpeggio's own gate timing decides note
    # length, this just needs to get out of the way between notes.
    amp_env=[0.01, 0.0, 1.0, 0.2],  # a time, d time, sustain level, release time
)

synth = SubtractiveSynth(engine, patch)

# root, major third, fifth, octave, one bar of a plain major arpeggio
root_note = 48  # C3
arp_notes = [root_note, root_note + 4, root_note + 7, root_note + 12, root_note + 7]


def note_on(midi_note):
    synth.note_on(midi_note, velocity=100)


def note_off(midi_note):
    synth.note_off(midi_note)


arp = Arpeggiator(120, note_on, note_off)
arp.set_bpm(120, 4)  # 10bpm 16th notes, ~9 cycles of the 4-note pattern per DURATION
arp.notes = arp_notes
arp.start()

# wave_names = wave_names()
wave_names = ("SAW", "ASAW", "SQU", "ASQU", "SSQU")

while True:
    synth.detune = 1.0
    for wave_name in wave_names:
        synth.wave = wave_name
        print("%-5s" % (wave_name))
        t0 = time.monotonic()
        while time.monotonic() - t0 < DURATION:
            arp.update()

    synth.detune = DETUNE
    for wave_name in wave_names:
        synth.wave = wave_name
        print("%-5s detune" % (wave_name))
        t0 = time.monotonic()
        while time.monotonic() - t0 < DURATION:
            arp.update()
