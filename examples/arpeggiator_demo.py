# SPDX-FileCopyrightText: Copyright (c) 2025 Tod Kurt
# SPDX-License-Identifier: MIT

import time

import synthio
from arpeggiator import Arpeggiator, pattern_names, patterns
from synth_setup import keys, knobA, knobB, synth

note = None  # note that was pressed during note_on, if any


# called by arp on note-on
def note_on(midi_note):
    global note
    # print("note on  %d %.2f" % (midi_note, time.monotonic()))
    gate_time = arp.step_millis * arp.gate / 1000
    amp_env = synthio.Envelope(attack_time=0.0, release_time=gate_time)
    note = synthio.Note(synthio.midi_to_hz(midi_note), envelope=amp_env)
    synth.press(note)


# called by arp on note-off
def note_off(midi_note):
    # print("     off %d %.2f" % (midi_note, time.monotonic()))
    if note:
        synth.release(note)


arp = Arpeggiator(120, note_on, note_off)
octaves = 1
arp.set_bpm(120, 4)  # 120 bpm of 16th notes
arp.start()

last_print_time = 0

while True:
    arp.update()

    root_note = 24 + int(36 * knobA.value / 65535)

    patt_i = int((len(patterns) - 1) * knobB.value / 65535)

    arp.notes = [root_note + n for n in patterns[patt_i]]

    if key := keys.events.get():
        if key.pressed:
            octaves = (octaves + 1) % 4
            arp.steps = 1 + octaves  # steps must be 1+

    if time.monotonic() - last_print_time > 0.5:
        last_print_time = time.monotonic()
        print("note=%d oct=%d pattern='%s'" % (root_note, octaves, pattern_names[patt_i]))
