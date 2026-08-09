# wavetable.py - wavetable synth reading Serum-style single-cycle WAV
# wavetables (16-bit mono, waves of `size` samples back to back).
# Requires the adafruit_wave library.
#
# All sounding notes share self._wavetable.waveform by reference, so
# setting wave_pos morphs already-sounding notes live -- the lerp writes
# into the one buffer synthio is reading from. O(1) in polyphony.

import synthio
import ulab.numpy as np
import adafruit_wave

from .synth import Synth


class Wavetable:
    """Reads one wave (or a lerp between two adjacent waves) out of a
    wavetable WAV file into a fixed, reusable buffer."""

    def __init__(self, filepath, size=256):
        self.w = adafruit_wave.open(filepath)
        if self.w.getsampwidth() != 2 or self.w.getnchannels() != 1:
            raise ValueError("16-bit mono WAV required")
        self.size = size
        self.num_waves = self.w.getnframes() // size
        self.waveform = np.zeros(size, dtype=np.int16)  # the shared buffer

    def _read_wave(self, i):
        self.w.setpos(i * self.size)
        return np.frombuffer(self.w.readframes(self.size), dtype=np.int16)

    def set_wave_pos(self, pos):
        """pos is fractional: 3.25 = 25% between wave 3 and wave 4."""
        n = self.num_waves
        if n < 2:                       # single-wave file: nothing to blend
            self.waveform[:] = self._read_wave(0)
            return
        if pos < 0:
            pos = 0.0
        elif pos > n - 1:
            pos = n - 1.0
        i = int(pos)
        if i > n - 2:                   # at the very top, blend the last pair
            i = n - 2
        frac = pos - i

        wave_a = self._read_wave(i)
        if frac <= 0.0:                 # exact wave: skip the read and the math
            self.waveform[:] = wave_a
            return
        wave_b = self._read_wave(i + 1)

        # Convex combination, evaluated in float. Do NOT write this as the
        # usual  wave_a + frac * (wave_b - wave_a)  -- that subtraction is
        # performed in int16 and wraps whenever the two samples straddle
        # zero at high amplitude (32000 - -32000 = 64000 -> +1536), which
        # then pushes the result past 32767 and raises
        #   OverflowError: value must fit in 2 byte(s)
        # on the store back into the int16 buffer. Multiplying by the float
        # weights first promotes to float, and since frac is in [0,1] the
        # result is bounded by the two inputs, so it always fits.
        self.waveform[:] = np.array(wave_a * (1.0 - frac) + wave_b * frac,
                                    dtype=np.int16)


class WavetableSynth(Synth):
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
        return (synthio.Note(f, waveform=self._wave, envelope=self._env,
                             amplitude=velocity / 127,
                             filter=self._make_filter(), bend=self._bend),)

    @property
    def wave_pos(self):
        return self._wave_pos

    @wave_pos.setter
    def wave_pos(self, v):
        self._wave_pos = v
        self._wavetable.set_wave_pos(v)   # in-place: morphs sounding notes

    @property
    def wave_file(self):
        return self._wt_path

    @wave_file.setter
    def wave_file(self, v):
        if v != self._wt_path:            # reopens file; next note-on uses it
            self._wavetable = Wavetable(v)
            self._wt_path = v
            self._wavetable.set_wave_pos(self._wave_pos)
            self._wave = self._wavetable.waveform
