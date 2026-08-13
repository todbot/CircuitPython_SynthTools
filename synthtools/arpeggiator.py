## pylint: disable=invalid-name
# SPDX-FileCopyrightText: Copyright (c) 2023 Tod Kurt
# SPDX-License-Identifier: MIT
"""
``arpeggiator``
================================================================================

``Arpeggiator`` is a melodic arpeggiator / sequencer for musical events

Part of synthtools.

"""

import time

try:
    from supervisor import ticks_ms
except ImportError:

    def ticks_ms():
        """stand-in for supervisor.ticks_ms"""
        return time.monotonic_ns() // 1_000_000


patterns = (
    (0, 4, 7, 12),
    (0, 3, 7, 10),
    (0, 3, 6, 3),
    (0, 5, 7, 12),
    (0, 12, 0, -12),
    (0, -12, -12, 0),
    (0, 0, 0, 0),
)

pattern_names = (
    "major",
    "minor7",
    "diminished",
    "suspend4",
    "octaves",
    "octaves2",
    "root",
)


class Arpeggiator:
    """Poll-based arpeggiator: call update() as often as possible.

    Holds a stack of notes added with add_note()/del_note() and steps
    through them at ``step_millis`` (derived from ``rate`` and bpm, set via
    set_bpm()), firing ``on_func``/``off_func`` at each gated step. ``rate`` is
    in notes-per-beat: 1 = quarter notes, 2 = eighths, 4 = sixteenths.
    """

    def __init__(self, rate, on_func=None, off_func=None):
        self.rate = rate  # 1 = 1/4 note, 2 = 1/8th note, 4 = 16th note
        self.set_bpm(120, rate)
        self.oct_distance = 12  # distance between repeats  (Ableton nomenclature)
        self.oct_range = 1  # max number of self.distance to do (Ableton nomenclature)
        self.octave = 0  # which arp step we're on, this is confusing with above
        self.on_func = on_func
        self.off_func = off_func
        self.notes = []  # the list of notes currently pressed
        self.transpose = 0
        self.i = 0  # where in the notes list
        self.gate = 0.5
        self.on = False
        self.held_note = None
        self.next_millis = 0
        self.held_millis = 0

    def set_bpm(self, bpm, rate=None):
        """Set BPM and optionally rate"""
        self.bpm = bpm
        self.rate = rate
        self.step_millis = 60_000 / self.rate / self.bpm

    def add_note(self, note):
        """Add a note to the arpeggio"""
        if note not in self.notes:
            self.notes.append(note)

    def del_note(self, note):
        """Remove a note from the arpeggio"""
        if note in self.notes:
            self.notes.remove(note)
            if self.i >= len(self.notes):
                self.i = 0

    def start(self):
        """Start the arpeggiator running"""
        self.next_millis = ticks_ms()
        self.on = True

    def stop(self):
        """Stop the arpeggiator, note_offs any held notes"""
        self.on = False
        self.off_func(self.held_note)  # turn off any held note

    def update(self):
        """Update the arpeggiator. Call as frequently as possible"""

        if not self.on:
            return
        now = ticks_ms()

        # trigger note-off after gate time
        if self.held_note and now - self.held_millis > 0:
            self.off_func(self.held_note)
            self.held_note = None

        # trigger note-on on if time to do so
        delta_millis = now - self.next_millis
        if delta_millis >= 0 and len(self.notes) > 0:  # time for new note
            note = self.notes[self.i] + self.oct_distance * self.octave
            # print("\t\t\t\t\t", "delta:",delta_millis)

            # trigger new note
            self.on_func(note)
            self.held_note = note  # save for note-off

            # set up when note off and next note happens
            self.held_millis = now + (self.step_millis * self.gate)
            self.next_millis = now + self.step_millis - delta_millis // 2

            # go to next note
            self.i = (self.i + 1) % len(self.notes)
            if self.i == 0:
                self.octave = (self.octave + 1) % self.oct_range
