# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# waves.py -- waveform name -> ulab int16 array, built once, cached forever.
#
# All notes share these arrays by reference: zero per-note allocation.

import random

import ulab.numpy as np

# ======================================================================
# Zone 1: oscillator waveforms. Formula and hand-drawn builders,
# dispatched and cached by name.
# ======================================================================

_cache = {}  # (name, size) -> np.array

# --- formula builders --------------------------------------------------


def _saw(size, vol):
    return np.linspace(vol, -vol, num=size, dtype=np.int16)


def _squ(size, vol):
    h = size // 2
    return np.concatenate(
        (np.ones(h, dtype=np.int16) * vol, np.ones(size - h, dtype=np.int16) * -vol)
    )


def _sin(size, vol):
    return np.array(
        np.sin(np.linspace(0, 2 * np.pi, num=size, endpoint=False)) * vol, dtype=np.int16
    )


def _tri(size, vol):
    h = size // 2
    return np.concatenate(
        (
            np.linspace(-vol, vol, num=h, dtype=np.int16),
            np.linspace(vol, -vol, num=size - h, dtype=np.int16),
        )
    )


def _nze(size, vol):
    return np.array([random.randint(-vol, vol) for _ in range(size)], dtype=np.int16)


# --- hand-drawn "analog" waveforms, ported from the Mozzi Arduino synth
# library's tables/ (saw_analogue512_int8.h, triangle_analogue512_int8.h,
# square_analogue512_int8.h, smoothsquare8192_int8.h). Each is fixed sampled
# data drawn by hand in Audacity, so there is no recipe to regenerate them;
# only the sample data itself can be shrunk. Each native table below was
# block-averaged offline (real numpy, not on device) from the raw int8
# samples, DC-corrected, peak-normalized to +-127, and phase-rotated to
# start where the other builders here start (peak-first for the saws,
# trough-first for the triangle, plateau-first for the squares), then had
# its own first sample appended as a cyclic sentinel so _resample_table()'s
# wraparound never needs a special case.
#
# Stored as bytes, one per sample, offset by +128 since bytes are unsigned.
# A .mpy keeps its constants in RAM for as long as the module is loaded, so
# a text form, or a tuple parsed from one, costs several bytes a sample.


def _resample_table(table, size, vol, peak=127):
    """Lerp a small native ``table`` (N+1 offset bytes, table[-1] ==
    table[0]) up to ``size`` samples, scaled from its own +-127-ish native
    range to +-vol. Plain Python scalar loop, not vectorized ulab ops: the
    MicroPython ulab fallback (tests/stubs/ulab/numpy.py) supports only
    int/slice indexing, so there is no fancy-indexing gather to lean on
    here; same shape as _nze() above."""
    n = len(table) - 1
    scale = vol / peak
    out = []
    for k in range(size):
        pos = (k / size) * n
        i = int(pos)
        frac = pos - i
        a = table[i] - 128
        b = table[i + 1] - 128
        out.append(int(round((a * (1.0 - frac) + b * frac) * scale)))
    return np.array(out, dtype=np.int16)


# saw_analogue512_int8.h: 512 raw int8 samples -> N=128 native, round-trip
# RMS error 5.1% of peak at size=256.
_ASAW_TABLE = (
    b"\xf0\xe7\xe9\xe5\xe4\xe1\xe1\xde\xdd\xda\xd9\xd6\xd5\xd2\xd1\xcf\xce\xcb\xca\xc7\xc6\xc4"
    b"\xc3\xc0\xbf\xbd\xbb\xb9\xb8\xb5\xb4\xb2\xb1\xae\xad\xab\xaa\xa7\xa6\xa3\xa2\xa0\x9f\x9d"
    b"\x9c\x99\x98\x96\x95\x92\x91\x8f\x8e\x8c\x8b\x88\x87\x85\x84\x82\x81\x7f\x7d\x7b\x7a\x78"
    b"\x77\x75\x74\x71\x71\x6e\x6d\x6b\x6a\x68\x67\x65\x64\x62\x61\x5f\x5e\x5c\x5b\x59\x58\x56"
    b"\x55\x53\x52\x50\x4f\x4d\x4c\x4a\x4a\x47\x47\x44\x44\x42\x41\x3f\x3e\x3d\x3c\x39\x39\x37"
    b"\x36\x34\x34\x32\x31\x2f\x2e\x2c\x2c\x29\x29\x27\x27\x24\x25\x20\x37\xd1\xf0"
)


def _asaw(size, vol):
    return _resample_table(_ASAW_TABLE, size, vol)


# triangle_analogue512_int8.h: 512 raw int8 samples -> N=64 native,
# round-trip RMS error 2.6% of peak at size=256.
_ATRI_TABLE = (
    b"\x16\x1b\x21\x27\x2c\x32\x39\x3f\x46\x4c\x53\x5a\x61\x68\x6f\x76\x7e\x85\x8d\x95\x9d\xa5"
    b"\xad\xb5\xbe\xc7\xce\xd7\xe0\xe9\xf2\xfb\xfd\xf4\xeb\xe2\xd9\xd0\xc9\xc0\xb7\xaf\xa7\x9f"
    b"\x97\x8f\x87\x80\x78\x71\x69\x62\x5b\x55\x4e\x47\x41\x3a\x34\x2e\x28\x22\x1d\x17\x16"
)


def _atri(size, vol):
    return _resample_table(_ATRI_TABLE, size, vol)


# square_analogue512_int8.h: 512 raw int8 samples -> N=128 native,
# round-trip RMS error 7.5% of peak at size=256.
_ASQU_TABLE = (
    b"\xeb\xe8\xee\xe9\xed\xea\xed\xea\xed\xea\xed\xea\xed\xeb\xec\xeb\xec\xeb\xec\xeb\xec\xeb"
    b"\xec\xeb\xec\xeb\xec\xeb\xec\xeb\xec\xeb\xec\xeb\xec\xeb\xec\xeb\xec\xeb\xec\xeb\xec\xeb"
    b"\xec\xeb\xec\xeb\xec\xeb\xed\xea\xed\xea\xed\xea\xed\xea\xee\xe8\xef\xe6\xf7\xa6\x16\x17"
    b"\x13\x16\x13\x16\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15"
    b"\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15\x14\x15"
    b"\x14\x15\x14\x15\x14\x15\x14\x15\x13\x15\x13\x16\x13\x16\x12\x19\x0e\x4d\xeb"
)


def _asqu(size, vol):
    return _resample_table(_ASQU_TABLE, size, vol)


# smoothsquare8192_int8.h: 8192 raw int8 samples -> N=256 native,
# round-trip RMS error 2.4% of peak at size=256. DC-centering an asymmetric
# hand-drawn wave means the two plateaus don't land at equal +-magnitude
# after normalizing to +-127 (one side is ~117 here). Inaudible, and
# expected for any non-zero-mean source.
_SSQU_TABLE = (
    b"\x7b\x7b\x7b\x7b\x7b\x7b\x7b\x7b\x7c\x7e\x81\x85\x8a\x91\x9b\xa6\xb4\xc3\xd3\xe4\xf3\xf5"
    b"\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf1\xe8\xe0\xd9\xd5\xd3\xd3\xd5\xd8"
    b"\xdd\xe2\xe8\xee\xf4\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf2\xf1\xef"
    b"\xee\xee\xee\xee\xef\xf0\xf2\xf3\xf4\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5"
    b"\xf5\xf5\xf5\xf4\xf4\xf4\xf4\xf4\xf4\xf4\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5"
    b"\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf5\xf3"
    b"\xf1\xed\xe7\xdd\xd1\xc0\xac\x93\x77\x58\x37\x14\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01"
    b"\x01\x01\x01\x01\x02\x10\x23\x31\x3c\x43\x45\x44\x3f\x38\x2e\x22\x16\x0b\x02\x01\x01\x01"
    b"\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x04\x08\x0c\x0e\x0f\x0f\x0f\x0e\x0c\x0a\x07\x04"
    b"\x02\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x02\x03\x03\x04\x04\x04\x04"
    b"\x03\x03\x02\x02\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01"
    b"\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x7b"
)


def _ssqu(size, vol):
    return _resample_table(_SSQU_TABLE, size, vol)


# --- dispatch + cached API ----------------------------------------------

_builders = {
    "SAW": _saw,  # plain formula sawtooth
    "SQU": _squ,  # plain formula square
    "SIN": _sin,  # plain formula sine
    "TRI": _tri,  # plain formula triangle
    "NZE": _nze,  # white noise, resampled fresh every call
    "ASAW": _asaw,  # Mozzi hand-drawn "analog" saw, wobbly decay
    "ATRI": _atri,  # Mozzi hand-drawn "analog" triangle
    "ASQU": _asqu,  # Mozzi hand-drawn "analog" square, rippled plateaus
    "SSQU": _ssqu,  # Mozzi hand-drawn square, soft rounded corners
}


def get_wave(name, size=256, volume=28000):
    """Return a cached int16 waveform array for ``name``. Builds on first use."""
    key = (name, size)
    w = _cache.get(key)
    if w is None:
        w = _builders[name](size, volume)
        _cache[key] = w
    return w


def wave_names():
    return list(_builders.keys())


def fill_pm_wave(buf, ratio, index, volume=28000):
    """Classic 2-operator phase-modulation carrier, written IN PLACE:

        sin(theta + index * sin(ratio * theta))    theta in [0, 2*pi)

    ``ratio`` MUST be a non-negative integer: the modulator has to complete
    a whole number of cycles per carrier cycle, or ``buf[-1]`` won't match
    ``buf[0]`` and every note buzzes at the loop point. ``index`` is the
    modulation depth in radians (0 = plain sine, 1-3 = classic FM, 5+ =
    harsh); it does not need clamping since the outer sin() stays in
    [-1, 1] regardless of depth.

    A ``size``-sample table can only represent up to ``size // 2`` harmonics,
    and phase modulation spreads energy out to roughly ``ratio * (index+1)``
    harmonics: past that the table is aliased before the note is ever
    played, so keep ratio and index modest for a small buffer.

    Written in place so every voice sharing this buffer (see fm_synth.py)
    morphs the instant a knob changes, the same idiom as fill_env_rise()."""
    n = len(buf)
    theta = np.linspace(0, 2 * np.pi, num=n, endpoint=False)
    mod = np.sin(theta * ratio) * index
    buf[:] = np.array(np.sin(theta + mod) * volume, dtype=np.int16)


_2x_cache = {}  # (name, size) -> np.array, two cycles of get_wave() back to back


def get_wave_2x(name, size=256, volume=28000):
    """Two cycles of get_wave(name), concatenated. Built once and cached,
    like get_wave() itself: not a per-voice or per-note cost. This is the
    shared source buffer random_phase_wave() slices from: doubling the
    length means any offset in [0, size) has a full cycle available without
    having to wrap around the end. get_wave() then returns a view of its
    first cycle, so the two share one buffer."""
    key = (name, size)
    w = _2x_cache.get(key)
    if w is None:
        base = get_wave(name, size, volume)
        w = np.concatenate((base, base))
        _2x_cache[key] = w
        _cache[key] = w[:size]
    return w


# --- band-limited tables ------------------------------------------------
#
# synthio's oscillator is a plain truncating table lookup, so every harmonic
# a table holds above Nyquist folds back as an inharmonic alias: a naive
# SAW at A4 and 22050 Hz carries junk only ~16 dB under its harmonics. A
# *_BL name holds one additive table per octave instead, each with only the
# harmonics that stay under Nyquist at the top of its octave plus
# BL_MARGIN semitones. The table is picked at note-on, so pitch moved
# further after press (wheel, glide) can still alias, and the lowest note
# of each octave loses its top harmonics (to ~5 kHz at 22050).

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


def warm_wave(name, sample_rate):
    """Build whatever random_phase_wave() slices ``name`` from, so the
    note-on path never has to."""
    if name in _BL_ODD:
        get_wave_bl(name, sample_rate)
    else:
        get_wave_2x(name)


def random_phase_wave(name, size=256, volume=28000, midi_note=None, sample_rate=None):
    """One cycle of ``name``, starting at a random point in its cycle.

    Unlike get_wave()/get_wave_2x(), this is NOT cached: every call slices
    a fresh ``size``-sample window out of the shared 2x buffer at a random
    offset, so the returned array differs call to call. That makes it a
    per-note-on cost: one array copy, the same tier as building a fresh
    synthio.Note or Biquad at press time, not a per-sample one. Call it once
    per oscillator per note-on, not from a hot path.

    A band-limited name needs ``midi_note`` and ``sample_rate`` to pick its
    table from get_wave_bl(), and is ``BL_SIZE`` long whatever ``size``
    says."""
    if name in _BL_ODD:
        wave2x = get_wave_bl(name, sample_rate)[min(int(midi_note), 127)]
    else:
        wave2x = get_wave_2x(name, size, volume)
    size = len(wave2x) // 2
    start = random.randint(0, size - 1)
    return wave2x[start : start + size]


# ======================================================================
# Zone 2: position-LFO shapes. One-shot/repeat arrays used as a POSITION
# (envelopes, vibrato fade-in, glide, wave-position sweeps), not as an
# oscillator's audio waveform. Two read-only cached fixed shapes
# (ramp_wave, saw_wave) plus one mutable, curve-shaped buffer system
# (env_buffer/fill_env_rise) for the AHR envelope.
#
# A synthio.LFO with once=True runs its waveform once and then holds the
# final sample forever, so a buffer holding nothing but a rise 0 -> peak
# already IS attack-then-hold. No plateau needs writing after the rise; the
# LFO supplies one for as long as the key is down. Release re-runs the same
# rise through a CONSTRAINED_LERP with swapped endpoints, see
# ahr_envelope.py.
# ======================================================================

ENV_SIZE = 64
ENV_PEAK = 32767

# --- read-only cached fixed shapes --------------------------------------

_ramp = None


def ramp_wave():
    """A cached 0 -> peak ramp, for one-shot LFOs used as a POSITION.

    Two samples is all it takes: synthio interpolates between waveform
    entries, so (0, ENV_PEAK) with once=True is a clean linear ramp that
    holds at the top; the tutorial's idiom for fade-ins and bends.

    Note this is NOT interchangeable with LFO(waveform=None): the default
    waveform is a zero-centred triangle that would come back down again.
    A ramp has to be spelled out.

    Read-only and shared by every user, unlike the envelope shape buffers,
    which are per-instance because they get rewritten in place."""
    global _ramp
    if _ramp is None:
        _ramp = np.array((0, ENV_PEAK), dtype=np.int16)
    return _ramp


_saw_lfo = None


def saw_wave():
    """A cached 0 -> peak ramp across ENV_SIZE samples, for a wave-position
    LFO's "saw" shape in repeat mode.

    Per the synthio tutorial, LFO interpolates the wrap from the last
    sample back to the first, so a short buffer (ramp_wave()'s 2 samples,
    say) loops as a TRIANGLE (up then back down across the wrap), not a
    saw. The wrap has to be a small fraction of the cycle instead, which
    needs enough samples that the rise dominates: with ENV_SIZE points the
    wrap is one interpolation step, 1/ENV_SIZE of the cycle.

    once=True doesn't need this (ramp_wave() alone already gives a clean
    ramp that holds at the top) so this is repeat-mode only."""
    global _saw_lfo
    if _saw_lfo is None:
        _saw_lfo = np.linspace(0, ENV_PEAK, num=ENV_SIZE, dtype=np.int16)
    return _saw_lfo


# --- mutable, curve-shaped buffer (the AHR envelope's rise) -------------


def env_buffer():
    """A writable buffer for an AHR envelope shape."""
    return np.zeros(ENV_SIZE, dtype=np.int16)


def _curve_ramp(start, stop, n, curve):
    """Normalized ramp start -> stop over n points, raised to the integer
    power ``curve``. Repeated multiply rather than ``**``: elementwise float
    multiply is already proven on ulab, ``**`` is not.

    For start/stop in [0,1] the result stays in [0,1], so scaling by
    ENV_PEAK cannot leave int16 range. Call it descending (1.0 -> 0) to get
    (1-t)^curve; ulab has no negative strides, so a descending linspace is
    the way to reverse a ramp, never a [::-1] slice.

    Allocates one array per multiply, so curve > 1 costs curve-1 extra
    temporaries. Fine for a patch load or a switch, not for a knob path."""
    t = np.linspace(start, stop, num=n)
    y = t
    for _ in range(curve - 1):
        y = y * t
    return y


def _clamp_curve(curve):
    curve = int(curve)
    return 1 if curve < 1 else curve


def fill_env_rise(buf, curve=1):
    """Rise 0 -> ENV_PEAK across the WHOLE buffer, shaped 1 - (1-t)^curve.

    ``curve`` is an integer exponent: 1 = linear, 2+ = increasingly
    fast-start, easing into the peak. That shape is chosen for what it does
    at the OTHER end. The release reruns this same buffer through a
    CONSTRAINED_LERP with swapped endpoints, i.e. ``V * (1 - s(t))``, so

        s(t) = 1 - (1-t)^curve   =>   release = V * (1-t)^curve

    which is the conventional decay: quick initial drop, long tail. The
    obvious alternative, s(t) = t^curve, makes the release
    ``V * (1 - t^curve)``: still at 75% of its value halfway through at
    curve=2, hanging near the top and then falling off a cliff. A mirrored
    attack, not a decay.

    NOTE this is a deliberate divergence from the synthio tutorial, whose
    PRODUCT(lerp, lerp, 1) is t^2, the shape described above. The tutorial
    keeps attack and release shapes independent, so it can afford t^2 for the
    rise; sharing one buffer means the release gets the casting vote.

    There is deliberately no hold segment and no second, falling buffer:
      - the hold is what ``once=True`` already does after the last sample
        (measured on device: a one-shot LFO reads 0.9999 at both 0.5s and
        1.5s after a 0.2s rise), so writing a plateau here would only shorten
        the rise and force the release rate to compensate for it;
      - a second buffer is unreachable mid-note anyway, because
        synthio.LFO.waveform is read-only.

    Written IN PLACE, so every voice sharing this array morphs live."""
    curve = _clamp_curve(curve)
    n = len(buf)
    if curve == 1:
        # 1 - (1-t)^1 is just t, so take the integer linspace directly:
        # bit-identical to a plain linear ramp and one float array cheaper
        buf[:] = np.linspace(0, ENV_PEAK, num=n, dtype=np.int16)
    else:
        # `* -ENV_PEAK + ENV_PEAK`, NOT `ENV_PEAK - arr`: the pure-Python
        # ulab fallback implements __sub__ but not __rsub__, so
        # scalar-minus-array raises TypeError on the MicroPython tier.
        # Endpoints stay exact for any curve because linspace pins its last
        # element: (1-t) is exactly 1.0 at index 0 and 0.0 at the end.
        buf[:] = np.array(_curve_ramp(1.0, 0.0, n, curve) * (-ENV_PEAK) + ENV_PEAK, dtype=np.int16)
