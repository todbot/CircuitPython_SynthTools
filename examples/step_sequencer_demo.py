# SPDX-FileCopyrightText: Copyright (c) 2025 Tod Kurt
# SPDX-License-Identifier: MIT
#
import time

import synthio
import ulab.numpy as np
from step_sequencer import StepSequencer
from synth_setup import keys, knobA, knobB, synth

bpm = 120
gate_length = 0.3  #  percent 0-1
steps_per_beat = 4  # 1 = 1/4 note, 2 = 1/8th note, 4 = 1/16th note, 8 = 1/32nd note
# sequence to play
pattern_steps = (0, 0, 0, 0, -2, -2, -4, -4, 3, 3, 5, 5, 7, 7, 12, 12)
pattern_steps = (0, 0, 0, 0, 2, 2, -4, -4, 0, 0, 5, 5, 7, 7, 12, 12)
root_note = 36
button_mode = 0  # 0 = normal, 1=octave up, 2=no filtenv, 3=no filtenv + oct up

wave_ramp_down = np.array((32767, 0), dtype=np.int16)
wave_exp_down = np.array(32767 * np.linspace(1, 0, num=128) ** 2, dtype=np.int16)

note = None  # the note on from note_on() to be note_off()'d


def note_on(midi_note, vel, gate, on):
    global note
    # print("note_on", midi_note, vel, gate)
    if note:
        note_off(midi_note, 0, 0, 1)
    release_time = 1.5 * seq.step_millis * gate / 1000
    amp_env = synthio.Envelope(attack_time=0.0, release_time=release_time)
    filt_env = synthio.LFO(
        rate=1 / release_time,
        once=True,
        scale=5000,
        offset=0,
        # waveform=wave_exp_down)
        waveform=wave_ramp_down,
    )
    filt_env = 5000 if button_mode in (2, 3) else filt_env
    filt = synthio.Biquad(synthio.FilterMode.LOW_PASS, frequency=filt_env, Q=1.8)
    note = synthio.Note(synthio.midi_to_hz(midi_note), envelope=amp_env, filter=filt)
    synth.press(note)


def note_off(midi_note, vel, gate, on):
    global note
    # print("note_off", midi_note)
    if note:
        synth.release(note)
        note = None


seq = StepSequencer(16, steps_per_beat, note_on, note_off)
seq.bpm = bpm

# convert our pattern to a sequence for the sequencer
for i in range(len(pattern_steps)):
    seq.steps[i][0] = root_note + pattern_steps[i]
    seq.steps[i][2] = 0.25
    print("note:", root_note + pattern_steps[i])

print("seq.steps:", seq.steps)
seq.start()

last_time = time.monotonic()
while True:
    seq.update()
    if key := keys.events.get():
        if key.pressed:
            button_mode = (button_mode + 1) % 4
            seq.transpose = 12 if button_mode in (1, 3) else 0

    if time.monotonic() - last_time > 0.1:
        last_time = time.monotonic()
        # change sequence speed wtih knobA
        seq.bpm = int(20 + (knobA.value / 65535) * 200)  # 20 - 220
        gatelen = knobB.value / 65535
        seq.set_gates(gatelen)
        print(
            "mode:%d bpm: %3d gate_millis: %.1f" % (button_mode, seq.bpm, seq.step_millis * gatelen)
        )
