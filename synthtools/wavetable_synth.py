# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# wavetable_synth.py - polyphonic wavetable synth instrument, built on the
# Synth engine (synth.py) and the Wavetable waveform-buffer tool
# (wavetable.py).
#
# All sounding notes share self._wavetable.waveform by reference, so
# setting wave_pos morphs already-sounding notes live -- the lerp writes
# into the one buffer synthio is reading from. O(1) in polyphony.

import synthio

from .synth import Synth
from .wavetable import Wavetable


class WavetableSynth(Synth):
    """Polyphonic wavetable synth: one Note per key, its waveform a
    position (wave_pos) lerped between two adjacent frames of a loaded
    wavetable WAV file (wave_file), through the shared Synth
    filter/envelope graph.

    All sounding notes share the Wavetable's waveform buffer by
    reference, so moving wave_pos morphs already-sounding notes live --
    the lerp writes into the one buffer synthio is reading from, O(1) in
    polyphony regardless of how many notes are held.
    """

    _PARAMS = Synth._PARAMS + ("wave_pos", "wave_file")

    # class attrs: base __init__ calls _recompile() before subclass setup
    _wavetable = None
    _wt_path = None
    _wave_pos = 0

    def _recompile(self):
        super()._recompile()
        p = self.patch
        if p.wave_file != self._wt_path:  # heavy: only on file change
            self._wavetable = Wavetable(p.wave_file)
            self._wt_path = p.wave_file
        self._wave_pos = getattr(p, "wave_pos", 0)
        self._wavetable.set_wave_pos(self._wave_pos)
        self._wave = self._wavetable.waveform

    def _decompile(self):
        super()._decompile()
        self.patch.wave_file = self._wt_path
        self.patch.wave_pos = self._wave_pos

    def _make_notes(self, midi_note, velocity):
        f = synthio.midi_to_hz(midi_note)
        # fmt: off
        return (synthio.Note(f, waveform=self._wave, envelope=self._env,
                             amplitude=velocity / 127,
                             filter=self._make_filter(),
                             bend=self._bend_cur),)
        # fmt: on

    @property
    def wave_pos(self):
        return self._wave_pos

    @wave_pos.setter
    def wave_pos(self, v):
        self._wave_pos = v
        self._wavetable.set_wave_pos(v)  # in-place: morphs sounding notes

    @property
    def wave_file(self):
        return self._wt_path

    @wave_file.setter
    def wave_file(self, v):
        if v != self._wt_path:  # reopens file; next note-on uses it
            self._wavetable = Wavetable(v)
            self._wt_path = v
            self._wavetable.set_wave_pos(self._wave_pos)
            self._wave = self._wavetable.waveform
