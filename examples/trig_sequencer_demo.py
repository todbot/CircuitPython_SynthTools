# SPDX-FileCopyrightText: Copyright (c) 2025 Tod Kurt
# SPDX-License-Identifier: MIT

# adding this can help with timing, if you need it
import microcontroller

microcontroller.cpu.frequency = 200_000_000

import time

import audiocore
import audiomixer
from synth_setup import BUFFER_SIZE, SAMPLE_RATE, audio

from synthtools.trig_sequencer import TrigSequencer

bpm = 120
trig_count = 4
step_count = 16
steps_per_beat = 4  # 2 = 8th note, 4 = 16th note

drum_pattern1 = (
    (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1),  # bass drum
    (0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0),  # snare
    (1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0),  # hi hat
    (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1),  # hi hat open
)

drum_map = (36, 48, 72, 0, 0, 0, 0, 0)  # could be midi notes
drum_map = (  # or anything else your callback wants
    audiocore.WaveFile("/wavs/kit0_909/00_909kick4.wav"),
    audiocore.WaveFile("/wavs/kit0_909/01_909snare2.wav"),
    audiocore.WaveFile("/wavs/kit0_909/02_909hatclosed2a.wav"),
    audiocore.WaveFile("/wavs/kit0_909/03_909hatopen5.wav"),
)


def trig_on(trig_num, wav):
    mixer.voice[trig_num].play(wav, loop=False)
    print("trig_on:    %d" % (trig_num))


def trig_off(trig_num, wav):
    print("  trig_off: %3d" % trig_num, wav)


mixer = audiomixer.Mixer(
    voice_count=trig_count,
    channel_count=1,
    sample_rate=SAMPLE_RATE,
    buffer_size=BUFFER_SIZE,
)
audio.play(mixer)

seq = TrigSequencer(trig_count, step_count, steps_per_beat, on_func=trig_on, off_func=trig_off)
seq.bpm = bpm
seq.set_pattern(drum_pattern1)
seq.set_drum_map(drum_map)
seq.start()

print("step_millis:", seq.step_millis, "bpm:", seq.bpm)
print("pattern:", seq.trigs)

while True:
    seq.update()
    time.sleep(0.0001)
