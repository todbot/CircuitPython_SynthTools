## pylint: disable=invalid-name,too-many-arguments,multiple-statements
# SPDX-FileCopyrightText: Copyright (c) 2023 Tod Kurt
# SPDX-License-Identifier: MIT
"""
``trig_sequencer``
================================================================================

``TrigSequencer`` is a trigger-based (drum) sequencer for rhythmic events.

Part of synthtools.

"""

from adafruit_ticks import ticks_add, ticks_diff, ticks_ms


class TrigSequencer:
    """
    TrigSequencer contains a list of on/off event triggers in list of steps.

    :param int trig_count: how many triggers to keep track of
    :param int step_count: how many for all the triggers
    :param int steps_per_beat: number of steps in a beat (1=quarter note, 2=8th note, 4=16th note)
    :param function on_func: function to call on trigger start
    :param function off_func: function to call on trigger end (unused)
    """

    def __init__(self, trig_count, step_count, steps_per_beat, on_func=None, off_func=None):
        self.trig_count = trig_count
        self.step_count = step_count
        self.steps_per_beat = steps_per_beat
        self.on_func = on_func
        self.off_func = off_func
        self.trigs = [[0 for t in range(step_count)] for i in range(trig_count)]
        self.i = 0  # where in the step sequence we currently are
        self.playing = False
        self.drum_map = [0] * trig_count
        self.step_millis = 0  # real value once bpm is set; update()/start() need it to exist
        self.next_millis = 0
        self._frac_millis = 0.0  # step_millis's fraction, carried between steps

    @property
    def bpm(self):
        return 60_000 / self.step_millis / self.steps_per_beat

    @bpm.setter
    def bpm(self, bpm):
        """Sets the internal tempo. step_millis is time between steps"""
        self.step_millis = 60_000 / self.steps_per_beat / bpm

    def start(self):
        """Start sequencer going"""
        self.next_millis = ticks_ms()
        self._frac_millis = 0.0
        self.playing = True

    def stop(self):
        """Stop sequencer"""
        self.playing = False
        self.i = 0

    def set_drum_map(self, drum_map):
        self.drum_map = drum_map

    def set_pattern(self, pattern):
        for i in range(len(pattern)):
            self.trigs[i][:] = pattern[i]  # copy elements, no new list alloc

    def update(self):
        """Update the sequencer. Call as frequently as possible"""
        if not self.playing:
            return

        now = ticks_ms()

        if ticks_diff(now, self.next_millis) >= 0:  # time to play
            for t in range(self.trig_count):
                if self.trigs[t][self.i] == 1:
                    self.on_func(t, self.drum_map[t])

            # prep for next step in sequence
            self.i = (self.i + 1) % self.step_count
            # int ticks: they wrap at 2**29, first ~65 s after power-on, and a
            # 30-bit float can't hold one that big to the ms
            self._frac_millis += self.step_millis
            step = int(self._frac_millis)
            self._frac_millis -= step
            self.next_millis = ticks_add(self.next_millis, step)
            if ticks_diff(self.next_millis, now) < 0:  # a stall put us a whole step behind
                self.next_millis = ticks_add(now, step)
