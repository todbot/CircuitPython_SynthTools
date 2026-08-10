# subtractive.py - classic two-oscillator subtractive synth.
# Osc2 is a detuned copy of osc1; detune=1.0 collapses to a single osc.

import synthio

from .synth import Synth
from .waves import get_wave


class SubtractiveSynth(Synth):
    _PARAMS = Synth._PARAMS + ("wave", "detune")

    # class attrs: the base __init__ builds its graph before this subclass
    # has run any setup of its own
    _wave_name = "SAW"
    _detune = 1.0

    def _recompile(self):
        super()._recompile()
        self._wave_name = self.patch.wave
        self._detune = self.patch.detune
        self._wave = get_wave(self._wave_name)  # shared array

    def _decompile(self):
        super()._decompile()
        self.patch.wave = self._wave_name
        self.patch.detune = self._detune

    def _make_notes(self, midi_note, velocity):
        f = synthio.midi_to_hz(midi_note)
        amp = velocity / 127
        n1 = synthio.Note(f, waveform=self._wave, envelope=self._env,
                          amplitude=amp, filter=self._make_filter(),
                          bend=self._bend_cur)
        if self._detune and self._detune != 1.0:
            n2 = synthio.Note(f * self._detune, waveform=self._wave,
                              envelope=self._env, amplitude=amp * 0.6,
                              filter=self._make_filter(), bend=self._bend_cur)
            return (n1, n2)
        return (n1,)

    @property
    def wave(self):
        return self._wave_name

    @wave.setter
    def wave(self, v):
        self._wave_name = v
        self._wave = get_wave(v)    # O(1); next note-on uses it

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
