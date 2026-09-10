# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# wavetable.py -- reads Serum-style single-cycle WAV wavetables (16-bit mono,
# waves of `size` samples back to back) into a reusable waveform buffer.
# Requires the adafruit_wave library.
#
# This is the tool: a waveform-buffer helper for use as a synthio.Note's
# `waveform`. For the polyphonic synth instrument built on top of it, see
# wavetable_synth.py.

import adafruit_wave
import ulab.numpy as np


class Wavetable:
    """Reads one wave (or a lerp between two adjacent waves) out of a
    wavetable WAV file into a fixed, reusable buffer.

    ``preload=True`` (default) reads the whole file once at construction and
    closes it, so ``set_wave_pos()`` never touches the filesystem again, at a
    RAM cost of ``num_waves * size * 2`` bytes (~32 KB for a 64-frame
    256-sample table). ``preload=False`` keeps the file open and reads each
    wave on demand, for a table too large to hold in RAM.
    """

    def __init__(self, filepath, size=256, preload=True):
        w = adafruit_wave.open(filepath)
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError("16-bit mono WAV required")
        self.size = size
        self.num_waves = w.getnframes() // size
        self.waveform = np.zeros(size, dtype=np.int16)  # the shared buffer
        self._fa = np.zeros(size)  # float scratch: wave a
        self._fd = np.zeros(size)  # float scratch: wave b - wave a
        self._i = -1  # lower index of the pair now held in _fa/_fd
        if preload:
            w.setpos(0)
            self._raw = w.readframes(self.num_waves * size)  # _table views this
            self._table = np.frombuffer(self._raw, dtype=np.int16)
            w.close()
            self.w = None
        else:
            self._table = None
            self.w = w

    def _read_wave(self, i):
        """Wave ``i`` as an int16 array. A view either way; consume it in the
        same statement, since the preload=False bytes are a temporary."""
        if self._table is not None:
            return self._table[i * self.size : (i + 1) * self.size]
        self.w.setpos(i * self.size)
        return np.frombuffer(self.w.readframes(self.size), dtype=np.int16)

    def set_wave_pos(self, pos):
        """pos is fractional: 3.25 = 25% between wave 3 and wave 4."""
        n = self.num_waves
        if n < 2:  # single-wave file: nothing to blend
            self.waveform[:] = self._read_wave(0)
            return
        if pos < 0:
            pos = 0.0
        elif pos > n - 1:
            pos = n - 1.0
        i = int(pos)
        if i > n - 2:  # at the very top, blend the last pair
            i = n - 2
        frac = pos - i

        if frac <= 0.0:  # exact wave: int16 straight in, scratch untouched
            self.waveform[:] = self._read_wave(i)
            return

        if i != self._i:  # crossed into a new pair: refresh a and b - a
            self._i = i
            self._fa[:] = self._read_wave(i)
            self._fd[:] = self._read_wave(i + 1)
            self._fd -= self._fa

        # a + frac*(b - a). (b - a) is cached in float across frac-only calls,
        # never int16 -- in int16 it wraps when two samples straddle zero at
        # high amplitude (32000 - -32000 -> +1536) and OverflowErrors on the
        # store back. Two size-length float temps land here (the product and
        # ulab's int16<-float slice conversion); a preallocated accumulator
        # doesn't help, since `x[:] = y` allocates its own temp too. Still
        # ~2 KB/call, down from ~6.5 KB + two file reads.
        acc = self._fd * frac
        acc += self._fa
        self.waveform[:] = acc
