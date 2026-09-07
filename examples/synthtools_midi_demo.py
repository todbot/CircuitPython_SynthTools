# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthtools_midi_demo.py -- play a SubtractiveSynth from USB (and UART) MIDI
#
# Notes come from note on/off, the pitch wheel bends, and ten common CCs
# drive ten live parameters. Edit CC_MAP below to remap them.
#
# Libraries needed:  circup install tmidi synthtools
#
# UART (DIN/TRS) MIDI is optional; set USE_UART_MIDI False if you have no
# MIDI jack wired up. Pins are the pico_test_synth ones: GP17 in, GP16 out.
#
# Two things to know about the CCs:
#
# - The amp-envelope CCs (72, 73, 75) rebuild the synthio.Envelope object,
#   so they only take effect on the NEXT note-on.
#   Everything else is a shared-block write and moves notes already sounding.
# - Polyphony: synthio allows 24 notes and this patch has detune=1.0, so one
#   Note per key. Give the patch a detune and every key costs TWO, which puts
#   a held 8-note chord (plus whatever is still releasing) over the ceiling.

import board
import tmidi
import usb_midi
from synth_setup import synth as engine

from synthtools import Patch, SubtractiveSynth

MIDI_CHANNEL = None  # None = omni, else 0-15
BEND_RANGE = 2 / 12  # pitch wheel range, in octaves (2 semitones)

USE_UART_MIDI = True
UART_RX_PIN = board.GP17
UART_TX_PIN = board.GP16

# --- CC -> parameter map -------------------------------------------------
# cc_number: (param_name, value_at_cc_0, value_at_cc_127)
# Any name in synth._PARAMS works; values scale linearly between the two.
# fmt: off
CC_MAP = {
    1:  ("vib_depth",     0.0,   0.05),   # mod wheel -> vibrato depth
    71: ("filt_q",        0.6,    6.0),   # resonance; see Synth.filt_q
    72: ("release_time",  0.01,  3.0),    # amp envelope  (next note-on)
    73: ("attack_time",   0.0,   2.0),    # amp envelope  (next note-on)
    74: ("filt_f",        100.0, 8000.0), # brightness / cutoff, Hz
    75: ("sustain_level", 0.0,   1.0),    # amp envelope  (next note-on)
    76: ("vib_rate",      0.1,   12.0),   # vibrato speed, Hz
    77: ("fenv_amount",   0.0,   6000.0), # filter envelope depth, Hz
    78: ("fenv_attack",   0.005, 1.0),    # filter envelope rise, sec
    79: ("fenv_release",  0.005, 2.0),    # filter envelope fall, sec
}
# fmt: on

# --- the synth -----------------------------------------------------------
# fmt: off
patch = Patch(name="midi lead", wave="SAW", detune=1.0,
              filt_type="LPF", filt_f=1200, filt_q=1.2,
              amp_env=[0.02, 0.15, 0.7, 0.4],
              vib_rate=5.5, vib_depth=0.0,
              fenv_amount=2500, fenv_attack=0.05, fenv_release=0.35,
              filt_vel=800)
# fmt: on

synth = SubtractiveSynth(engine, patch)

# Catch a typo in CC_MAP now, at startup, rather than as a KeyError out of
# set_param() in the middle of playing.
for name, _, _ in CC_MAP.values():
    if name not in synth._PARAMS:
        raise ValueError("CC_MAP: no such parameter '%s'" % name)

# --- MIDI inputs ---------------------------------------------------------
midi_ins = [tmidi.MIDI(midi_in=usb_midi.ports[0])]

if USE_UART_MIDI:
    import busio

    # timeout must be short:
    uart = busio.UART(rx=UART_RX_PIN, tx=UART_TX_PIN, baudrate=31250, timeout=0.001)
    midi_ins.append(tmidi.MIDI(midi_in=uart))


def handle_midi(msg):
    if MIDI_CHANNEL is not None and msg.channel != MIDI_CHANNEL:
        return

    if msg.type == tmidi.NOTE_ON and msg.velocity:
        synth.note_on(msg.note, msg.velocity)

    elif msg.type in (tmidi.NOTE_OFF, tmidi.NOTE_ON):
        synth.note_off(msg.note)  # note-on at velocity 0 is a note-off

    elif msg.type == tmidi.PITCH_BEND:
        synth.pitch_bend(msg.pitch_bend / 8192 * BEND_RANGE)

    elif msg.type == tmidi.CC:
        if msg.data0 in CC_MAP:
            name, lo, hi = CC_MAP[msg.data0]
            synth.set_param(name, lo + (hi - lo) * msg.data1 / 127)
            print("cc %d: %s = %.4f" % (msg.data0, name, getattr(synth, name)))
        elif msg.data0 in (120, 123):  # all sound off / all notes off
            synth.all_notes_off()


chan_str = "any" if MIDI_CHANNEL is None else str(MIDI_CHANNEL + 1)
print("synthtools midi demo: listening on midi channel", chan_str)

while True:
    for midi in midi_ins:
        if msg := midi.receive():
            handle_midi(msg)
