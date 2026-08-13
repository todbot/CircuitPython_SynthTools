# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# subtractive.py - classic two-oscillator subtractive synth.
#
# Osc2 is a detuned copy of osc1; detune=1.0 collapses to a single osc.

import synthio

from .synth import Synth
from .waves import get_wave_2x, random_phase_wave


class SubtractiveSynth(Synth):
    """Classic two-oscillator subtractive synth: one waveform, an optional
    detuned second oscillator, through the shared Synth filter/envelope
    graph.

    ``detune=1.0`` (the default) collapses to a single oscillator, so an
    ordinary patch costs one Note per key; any other detune spends TWO
    Notes per key (see the polyphony-budget note in the project docs).
    Each oscillator gets its own random phase per note-on, and osc2 is
    scaled down (60% of osc1) so a detuned voice's peak amplitude does not
    exceed a single-oscillator one.
    """

    _PARAMS = Synth._PARAMS + ("wave", "detune")

    # class attrs: the base __init__ builds its graph before this subclass
    # has run any setup of its own
    _wave_name = "SAW"
    _detune = 1.0

    def _recompile(self):
        super()._recompile()
        self._wave_name = self.patch.wave
        self._detune = self.patch.detune
        get_wave_2x(self._wave_name)  # warm the cache; note-on only slices

    def _decompile(self):
        super()._decompile()
        self.patch.wave = self._wave_name
        self.patch.detune = self._detune

    def _make_notes(self, midi_note, velocity):
        f = synthio.midi_to_hz(midi_note)
        amp = velocity / 127
        detuned = self._detune and self._detune != 1.0
        # Each oscillator gets its OWN random start point in the wave's
        # cycle, rerolled every note-on -- see waves.random_phase_wave().
        # Rebalanced only when osc2 exists: undetuned (single-osc) patches
        # stay at full amp, unchanged. When osc2 is present, split so the
        # two sum to amp * 1.0 instead of amp * 1.6 -- the old worst case
        # (both oscillators in phase, still possible now that phase is
        # random) could exceed int16 range on its own, before the filter
        # even sees it. 0.625/0.375 keeps osc2 at 60% of osc1's level, same
        # blend as before, just scaled so the ceiling is 1.0 instead of 1.6.
        # fmt: off
        n1 = synthio.Note(f, waveform=random_phase_wave(self._wave_name),
                          envelope=self._env,
                          amplitude=amp * 0.625 if detuned else amp,
                          filter=self._make_filter(), bend=self._bend_cur)
        if detuned:
            n2 = synthio.Note(f * self._detune,
                              waveform=random_phase_wave(self._wave_name),
                              envelope=self._env, amplitude=amp * 0.375,
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
        get_wave_2x(v)  # O(1); warms the cache for the next note-on

    @property
    def detune(self):
        return self._detune

    @detune.setter
    def detune(self, v):
        # genuinely per-note (each osc2 has its own frequency), so this one
        # cannot be a shared block: O(polyphony).
        self._detune = v
        for notes in self.voices.values():
            if len(notes) > 1:
                notes[1].frequency = notes[0].frequency * v
