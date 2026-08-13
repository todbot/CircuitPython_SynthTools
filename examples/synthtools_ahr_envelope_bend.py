# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# ahr_envelope_bend_demo.py -- AHREnvelope wired straight to Note.bend, with
# nothing else from synthtools in the way: just synthio.Synthesizer and
# synthio.Note. No Patch, no SubtractiveSynth.
#
# Copy flat onto CIRCUITPY beside synth_setup.py and the synthtools/
# package, then either rename it code.py or, from the serial REPL:
#
#     import ahr_envelope_bend_demo
#
# --- what AHREnvelope.make() hands you -----------------------------------
# One call builds a small per-voice graph:
#
#   pos = LFO(waveform = shared shape, rate = shared attack rate, once=True)
#   env = Math(CONSTRAINED_LERP, amount, 0.0, pos)     <- this is `bend` below
#
# `bend` is a live block, so wiring it straight into Note(bend=bend) is the
# whole hookup -- no synth.blocks.append() needed, because the block is
# reachable through the sounding Note itself (see CLAUDE.md's "anything not
# reachable from a sounding Note" rule; that rule is about SHARED nodes
# nothing points at yet, and this one is pointed at from the moment it's
# built).
#
# --- bend units ------------------------------------------------------------
# 1.0 = ONE OCTAVE, so amount=0.5 below is half an octave (6 semitones).
#
# --- why falling=True --------------------------------------------------
# falling=True makes make() return CONSTRAINED_LERP(amount, 0.0, pos): the
# note starts `amount` away from true pitch and eases DOWN to 0 over
# `attack` seconds -- a "scoop" into pitch, the classic slide/horn attack.
# start_release() then re-aims the SAME position LFO on to release_amount,
# so if you let go of the key mid-attack the fall picks up from wherever the
# bend actually got to -- it does not jump anywhere first.
#
# --- why release_amount is nonzero --------------------------------------
# release_amount=0.0 would make start_release() a no-op here: by the time a
# held note releases, the attack has already finished at bend=0.0, so a
# lerp from 0.0 to 0.0 moves nothing. -0.3 gives the release something to
# do -- the pitch sags down as the note dies, the way synthinst_pitch_demo's
# penv_out_amount does at the SubtractiveSynth level.
#
# --- why the Note gets its own envelope ---------------------------------
# The AHR envelope only ticks while its Note is alive (CLAUDE.md's "three
# reasons a filter envelope is inaudible", #3 applies here too), so the AHR
# release has to fit inside the amp envelope's release or the voice is
# freed mid-bend. An explicit envelope on the Note keeps that relationship
# visible here instead of depending on whatever synth_setup.py happens to
# set globally.

import time

import synthio

from synth_setup import synth
from synthtools.ahr_envelope import AHREnvelope

penv = AHREnvelope(
    attack=0.7,  # seconds to ease from `amount` down to true pitch
    release=0.35,  # seconds to sag on to release_amount after note-off
    amount=0.5,  # half-octave sharp
    curve=2,  # curved, not linear -- fast off the start, easing into 0
    falling=True,  # amount -> 0 on press, 0 -> release_amount on release
    release_amount=-0.3,  # sag ~4 semitones flat as the note dies
)

NOTE = 45  # A2
note_env = synthio.Envelope(attack_time=0.01, release_time=0.8, sustain_level=0.8)


def sample(bend, seconds):
    """Print bend.value a few times a second -- this is what turns the
    demo from a wiring snippet into something you can watch happen."""
    steps = max(int(seconds / 0.05), 1)
    for _ in range(steps):
        print("  bend = %+.3f" % bend.value)
        time.sleep(0.05)


while True:
    # One call per press: make() is a per-voice factory, so a new Note
    # gets its own position LFO and its own CONSTRAINED_LERP -- polyphony
    # is fine here even though penv itself is a single shared instance.
    bend = penv.make()
    note = synthio.Note(synthio.midi_to_hz(NOTE), bend=bend, envelope=note_env)

    print("press  -- bend eases into set pitch")
    synth.press(note)
    sample(bend, 0.7)

    print("release -- bend eases out of set pitch")
    penv.start_release(bend)
    synth.release(note)
    sample(bend, 0.7)

    # toggle
    penv.amount *= -1
    penv.release_amount *= -1
