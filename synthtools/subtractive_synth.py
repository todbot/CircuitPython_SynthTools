# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# subtractive.py -- classic two-oscillator subtractive synth.
#
# Osc2 is a detuned copy of osc1; detune=1.0 collapses to a single osc.

import math

import synthio

from .synth import Synth
from .waves import random_phase_wave, warm_wave


def _semis_above(ratio):
    """Semitones a frequency ratio sits above unison, 0 for ratios <= 1."""
    return round(12 * math.log(ratio) / math.log(2)) if ratio > 1.0 else 0


class SubtractiveSynth(Synth):
    """Classic two-oscillator subtractive synth: one waveform, an optional
    detuned second oscillator, through the shared Synth filter/envelope
    graph.

    ``detune=1.0`` collapses to a single oscillator, one Note per key; any
    other detune, the ``Patch`` default of 1.001 included, spends TWO Notes
    per key (see the polyphony-budget note in the project docs).
    Each oscillator gets its own random phase per note-on. A detuned voice
    runs both oscillators at 0.666 of the single-osc level (by ear), so it
    peaks at 1.33x a single-osc one; ``HEADROOM`` absorbs that.
    """

    # synthio's mix bus soft-limits above +-28000, and one full-amplitude
    # note already peaks at ~14000, so two keys reach the limiter. Make the
    # level back at mixer.voice[0].level. Read per note-on, like
    # WavetableSynth.WT_HEADROOM.
    HEADROOM = 0.5

    _PARAMS = Synth._PARAMS + ("wave", "detune")

    # class attrs: the base __init__ builds its graph before this subclass
    # has run any setup of its own
    _wave_name = "SAW"
    _detune = 1.0
    _detune_semis = 0

    def _recompile(self):
        super()._recompile()
        self._wave_name = self.patch.wave
        self._detune = self.patch.detune
        self._detune_semis = _semis_above(self._detune)
        warm_wave(self._wave_name, self.synthio.sample_rate)  # note-on only slices

    def _decompile(self):
        super()._decompile()
        self.patch.wave = self._wave_name
        self.patch.detune = self._detune

    def _make_notes(self, midi_note, velocity):
        f = synthio.midi_to_hz(midi_note)
        sr = self.synthio.sample_rate
        amp = velocity / 127 * self.HEADROOM
        detuned = self._detune and self._detune != 1.0
        # Each oscillator gets its OWN random start point in the wave's
        # cycle, rerolled every note-on; see waves.random_phase_wave().
        # Osc2 picks a band-limited table for its own pitch, not osc1's:
        # a detune of 1.5 is a fifth, past what the table's margin covers.
        # fmt: off
        n1 = synthio.Note(f, waveform=random_phase_wave(self._wave_name, midi_note=midi_note,
                                                        sample_rate=sr),
                          envelope=self._env,
                          amplitude=amp * 0.666 if detuned else amp,
                          filter=self._make_filter(), bend=self._bend_cur)
        if detuned:
            n2 = synthio.Note(f * self._detune,
                              waveform=random_phase_wave(self._wave_name,
                                                         midi_note=midi_note + self._detune_semis,
                                                         sample_rate=sr),
                              envelope=self._env, amplitude=amp * 0.666,
                              filter=self._make_filter(), bend=self._bend_cur)
            return (n1, n2)
        return (n1,)
        # fmt: on

    @property
    def wave(self):
        return self._wave_name

    @wave.setter
    def wave(self, v):
        self._wave_name = v
        warm_wave(v, self.synthio.sample_rate)  # warms the cache for the next note-on

    @property
    def detune(self):
        return self._detune

    @detune.setter
    def detune(self, v):
        # genuinely per-note (each osc2 has its own frequency), so this one
        # cannot be a shared block: O(polyphony).
        self._detune = v
        self._detune_semis = _semis_above(v)
        for notes in self.voices.values():
            if len(notes) > 1:
                notes[1].frequency = notes[0].frequency * v
