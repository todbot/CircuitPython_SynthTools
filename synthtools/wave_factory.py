# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# wave_factory.py -- `Waves`, a string-keyed waveform factory with a few
# extra conveniences (WAV loading, LFO shape helpers) for building
# instruments interactively. Nothing in synthtools imports it, and it is
# kept out of waves.py so the synths don't pay for its bytecode.
#
# `Waves.make_waveform()` delegates to `get_wave()` for the waveform types
# they share, rather than generating them a second way.
#
# adafruit_wave is imported lazily, inside Waves.wav()/wav_info() only: it
# isn't available under plain CPython (no pip package here).

import ulab.numpy as np

from .waves import ENV_PEAK, get_wave

_NAME_ALIASES = {
    "SIN": "SIN",
    "SINE": "SIN",
    "SQU": "SQU",
    "SQUARE": "SQU",
    "SAW": "SAW",
    "TRI": "TRI",
    "TRIANGLE": "TRI",
    "NZE": "NZE",
    "NOISE": "NZE",
    "ASAW": "ASAW",
    "ANALOG_SAW": "ASAW",
    "ATRI": "ATRI",
    "ANALOG_TRI": "ATRI",
    "ASQU": "ASQU",
    "ANALOG_SQU": "ASQU",
    "SSQU": "SSQU",
    "SMOOTH_SQU": "SSQU",
}


class Waves:
    """
    Generate waveforms for either oscillator or LFO use.
    By default, size is 256, volume is max +-32767
    """

    waveform_types = ("SIN", "SQU", "SAW", "TRI", "SIL", "NZE", "ASAW", "ATRI", "ASQU", "SSQU")

    # --- factory + basic oscillator waveforms (delegate to get_wave) ---

    @staticmethod
    def make_waveform(waveid, size=256, volume=32767):
        """Return a waveform by string name, one of ``waveform_types``.

        Delegates to ``get_wave()`` for the types it also builds, rather than
        generating them a second way; SIL has no ``get_wave`` equivalent and
        stays local.
        """
        waveid = waveid.upper()
        if waveid in ("SIL", "SILENCE"):
            return Waves.silence(size)
        canonical = _NAME_ALIASES.get(waveid)
        if canonical is None:
            print("unknown wave type", waveid)
            return None
        return get_wave(canonical, size, volume)

    @staticmethod
    def sine(size, volume):
        """Sine waveform"""
        return get_wave("SIN", size, volume)

    @staticmethod
    def square(size, volume):
        """Square waveform"""
        return get_wave("SQU", size, volume)

    @staticmethod
    def triangle(size, min_vol, max_vol):
        """Triangle waveform. ``get_wave``'s TRI is symmetric about 0, so this
        only delegates when min_vol/max_vol are the usual +-volume pair."""
        if min_vol == -max_vol:
            return get_wave("TRI", size, max_vol)
        return np.concatenate(
            (
                np.linspace(min_vol, max_vol, num=size // 2, dtype=np.int16),
                np.linspace(max_vol, min_vol, num=size // 2, dtype=np.int16),
            )
        )

    @staticmethod
    def saw(size, volume):
        """Saw (aka Ramp) waveform"""
        return Waves.saw_down(size, volume)

    @staticmethod
    def saw_down(size, volume):
        """Saw waveform from max to min"""
        return get_wave("SAW", size, volume)

    @staticmethod
    def saw_up(size, volume):
        """Saw waveform from min to max"""
        return np.linspace(-volume, volume, num=size, dtype=np.int16)

    @staticmethod
    def silence(size):
        """All zeros waveform"""
        return np.zeros(size, dtype=np.int16)

    @staticmethod
    def noise(size, volume):
        """White noise waveform (from random.randint)"""
        return get_wave("NZE", size, volume)

    @staticmethod
    def from_list(vals):
        """Waveform from a list of values, useful for LFOs"""
        return np.array([int(v) for v in vals], dtype=np.int16)

    # --- LFO / position shapes -------------------------------------------

    @staticmethod
    def lfo_ramp_up_pos():
        """Simple two-element ramp-up waveform for synthio.LFO (which does
        interpolation). A fresh array, NOT ramp_wave()'s cached one: that
        one is shared (by _vib_fade, _glide_pos, and the wavetable-LFO
        once=True shapes) and its own docstring says so; aliasing it here
        would let an interactive caller mutate it and silently break every
        synth using it."""
        return np.array((0, ENV_PEAK), dtype=np.int16)

    @staticmethod
    def lfo_ramp_down_pos():
        """Simple two-element ramp-down waveform for synthio.LFO (which does interpolation)"""
        return np.array((32767, 0), dtype=np.int16)

    @staticmethod
    def lfo_triangle_pos():
        """Simple three-element triangle waveform for synthio.LFO (which does
        interpolation). Looped, a two-sample ramp plays as this same
        triangle, since the LFO interpolates its wrap from the last sample
        back to the first."""
        return np.array((0, 32767, 0), dtype=np.int16)

    @staticmethod
    def lfo_triangle():
        """Simple four-element triangle waveform for synthio.LFO (which does interpolation)"""
        return np.array((0, 32767, 0, -32767), dtype=np.int16)

    # --- WAV file I/O ------------------------------------------------------

    @staticmethod
    def wav(filepath, size=256, pos=0):
        """Create a waveform from a WAV file using adafruit_wave"""
        import adafruit_wave

        with adafruit_wave.open(filepath) as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                raise ValueError("unsupported format")
            n = size
            w.setpos(pos)
            return np.frombuffer(w.readframes(n), dtype=np.int16)

    @staticmethod
    def wav_info(filepath):
        """return (nframes,nchannels,sampwidth) from a WAV filename"""
        import adafruit_wave

        with adafruit_wave.open(filepath) as w:
            return (w.getnframes(), w.getnchannels(), w.getsampwidth())
