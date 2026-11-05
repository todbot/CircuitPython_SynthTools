## pylint: disable=invalid-name, too-many-arguments, too-many-instance-attributes
# SPDX-FileCopyrightText: Copyright (c) 2023 Tod Kurt
# SPDX-License-Identifier: MIT
"""
``step_sequencer``
================================================================================

``StepSequencer`` is a note-based sequencer for musical events.

Part of synthtools.

"""

from adafruit_ticks import ticks_add, ticks_diff, ticks_ms


class StepSequencer:
    """
    StepSequencer contains a list of meloci events in list of steps.

    :param int step_count: how many for all the triggers
    :param int steps_per_beat: number of steps in a beat (1=quarter note, 2=8th note, 4=16th note)
    :param function on_func: function to call on note-on
    :param function off_func: function to call on note-off
    """

    def __init__(self, step_count, steps_per_beat, on_func=None, off_func=None):
        self.steps_per_beat = steps_per_beat  # 1 = 1/4 note, 2 = 8th note, 4 = 16th note
        self.step_count = step_count  # how big the sequence is
        self.i = 0  # where in the step sequence we currently are

        # our sequence, list of step "objects": ie. list (notenum, vel, gate, on)
        self.steps = [[0, 127, 0.5, True] for i in range(step_count)]

        self.on_func = on_func  # callback to invoke when 'note on' should be sent
        self.off_func = off_func  # callback to invoke when 'note off' should be sent
        self.gate_off_millis = 0  # when in the future our note off should occur
        self.held_note = None  # the current note playing
        self.transpose = 0
        self.playing = False  # is sequence running or not (but use .start()/.stop())
        self.external_clock = False  # owner calls trigger(), update() only releases gates
        self.catch_up_steps = 0  # how far behind to still play every step, late, not resync
        self.next_millis = 0
        self._frac_millis = 0.0  # step_millis's fraction, carried between steps

    @property
    def bpm(self):
        """Returns bpm, computed"""
        return 60_000 / self.step_millis / self.steps_per_beat

    @bpm.setter
    def bpm(self, bpm):
        """Sets the internal tempo. step_millis is time between steps"""
        self.step_millis = 60_000 / self.steps_per_beat / bpm
        # print("stepseq.set_bpm: %6.2f %d" % (self.step_millis, bpm) )

    def set_gates(self, gate):
        """Set all gates to a specified percentage 0-1"""
        for i in range(self.step_count):
            self.steps[i][2] = gate

    def start(self):
        """Start sequencer going"""
        self.next_millis = ticks_ms()
        self._frac_millis = 0.0
        self.playing = True

    def pause(self):
        """Pause sequencer where it is, turning off any currently-sounding note"""
        if self.held_note:
            self.off_func(*self.held_note)
            self.held_note = None
        self.playing = False

    def stop(self):
        """Stop sequencer and rewind, turning off any currently-sounding note"""
        self.pause()
        self.i = 0

    def trigger(self, now=None):
        """Play the current step and advance, for an owner keeping its own clock"""
        if now is None:
            now = ticks_ms()
        if self.i >= self.step_count:  # step_count shrank under us
            self.i = 0
        (note, vel, gate, on) = self.steps[self.i]  # get new note to play
        note += self.transpose  # adjust for transpose
        self.held_note = (note, vel, gate, on)  # save it for when we note_off it

        # trigger new note
        self.on_func(*self.held_note)  # held_note = (note,vel,gate,on)

        # prep for next step in sequence
        self.i = (self.i + 1) % self.step_count

        # int ticks: they wrap at 2**29, first ~65 s after power-on, and a
        # 30-bit float can't hold one that big to the ms
        self._frac_millis += self.step_millis
        step = int(self._frac_millis)
        self._frac_millis -= step
        self.next_millis = ticks_add(self.next_millis, step)
        # a stall put us too far behind
        if ticks_diff(self.next_millis, now) < -self.catch_up_steps * step:
            self.next_millis = ticks_add(now, step)
        # next note off is some percentage smaller
        gate = int(self.step_millis * self.held_note[2])
        self.gate_off_millis = ticks_add(now, gate)

    def update(self):
        """Update the sequencer. Call as frequently as possible"""
        if not self.playing:
            return

        now = ticks_ms()

        # trigger note-off after gate time
        if self.held_note and ticks_diff(now, self.gate_off_millis) >= 0:
            self.off_func(*self.held_note)
            self.held_note = None

        if not self.external_clock and ticks_diff(now, self.next_millis) >= 0:
            self.trigger(now)
