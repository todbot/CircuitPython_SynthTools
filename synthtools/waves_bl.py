# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# waves_bl.py -- band-limited SAW_BL/SQU_BL tables, one per octave.
#
# synthio's oscillator is a plain truncating table lookup, so every harmonic
# a table holds above Nyquist folds back as an inharmonic alias: a naive
# SAW at A4 and 22050 Hz carries junk only ~16 dB under its harmonics. A
# *_BL name holds one additive table per octave instead, each with only the
# harmonics that stay under Nyquist at the top of its octave plus
# BL_MARGIN semitones. The table is picked at note-on, so pitch moved
# further after press (wheel, glide) can still alias, and the lowest note
# of each octave loses its top harmonics (to ~5 kHz at 22050).
#
# Kept out of waves.py so a synth that never plays a *_BL name doesn't
# load it; waves.py imports it on the first one.

import ulab.numpy as np

#: band-limited table length; truncation noise falls ~6 dB per doubling
BL_SIZE = 512
#: semitones of upward bend a band-limited table absorbs before aliasing
BL_MARGIN = 2
# A band-limited saw/square rings ~18% past its own peak (Gibbs), so the
# tables are scaled down by that to keep the ringing inside `volume`.
_GIBBS = 1.18

_BL_ODD = {"SAW_BL": False, "SQU_BL": True}  # name -> odd harmonics only
_bl_cache = {}  # (name, size, sample_rate) -> 128-tuple: midi note -> 2x table


def _bl_kmax(octave, sample_rate, size):
    top_hz = 440.0 * 2 ** ((octave * 12 + 11 + BL_MARGIN - 69) / 12)
    return max(1, min(size // 2 - 1, int(sample_rate / 2 / top_hz)))


def _build_bl(odd, sample_rate, size, volume):
    kmaxes = [_bl_kmax(octave, sample_rate, size) for octave in range(11)]
    # each octave's table is a partial sum of the same series, so one running
    # sum, snapshotted at each kmax, builds the whole set
    theta = np.linspace(0, 2 * np.pi, num=size, endpoint=False)
    scale = volume / _GIBBS * (4 if odd else 2) / np.pi
    acc = np.zeros(size)
    by_kmax = {}
    k = 0
    for kmax in sorted(set(kmaxes)):
        while k < kmax:
            k += 1
            if not (odd and k % 2 == 0):
                acc += np.sin(theta * k) * (1 / k)
        f = acc * scale
        # a square's lone fundamental is 4/pi tall, taller than any ringing.
        # Both series are odd-symmetric, so min(f) is -max(f).
        peak = max(f)
        if peak > volume:
            f = f * (volume / peak)
        w = np.array(f, dtype=np.int16)
        by_kmax[kmax] = np.concatenate((w, w))
    return tuple(by_kmax[kmaxes[n // 12]] for n in range(128))


def get_wave_bl(name, sample_rate, size=BL_SIZE, volume=28000):
    """Band-limited tables for ``name`` (``SAW_BL`` or ``SQU_BL``) at
    ``sample_rate``, as a 128-tuple indexed by midi note. Each entry is two
    cycles long, like get_wave_2x(), and notes in one octave share one.

    Built once and cached, but the first call is slow: measured on an rp2040
    at 250 MHz, ~1 s for ``SAW_BL`` and 0.5-0.8 s for ``SQU_BL`` (the higher
    figure with a chord sounding), so warm it at patch load, never at
    note-on. Costs ``2 * 2 * size`` bytes per distinct table: measured
    19.4 KB of heap per shape at 512 samples and 22050 Hz."""
    key = (name, size, sample_rate)
    tables = _bl_cache.get(key)
    if tables is None:
        tables = _build_bl(_BL_ODD[name], sample_rate, size, volume)
        _bl_cache[key] = tables
    return tables
