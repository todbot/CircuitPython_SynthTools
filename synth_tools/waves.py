# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# waves.py - waveform name -> ulab int16 array, built once, cached forever.
#
# All notes share these arrays by reference: zero per-note allocation.
#
# Also holds `Waves`, a string-keyed factory with a few extra conveniences
# (WAV loading, LFO shape helpers) for building instruments interactively.
# `Waves.make_waveform()` delegates to `get_wave()` for the waveform types
# they share, rather than generating them a second way.
#
# adafruit_wave is imported lazily, inside Waves.wav()/wav_info() only: it
# isn't available under plain CPython (no pip package here), and everything
# else in this module -- including the CPython test tier -- must not require
# it just to build a waveform buffer.

import random
import ulab.numpy as np

_cache = {}  # (name, size) -> np.array


def _saw(size, vol):
    return np.linspace(vol, -vol, num=size, dtype=np.int16)


def _squ(size, vol):
    h = size // 2
    return np.concatenate((np.ones(h, dtype=np.int16) * vol,
                           np.ones(size - h, dtype=np.int16) * -vol))


def _sin(size, vol):
    return np.array(
        np.sin(np.linspace(0, 2 * np.pi, num=size, endpoint=False)) * vol,
        dtype=np.int16)


def _tri(size, vol):
    h = size // 2
    return np.concatenate((np.linspace(-vol, vol, num=h, dtype=np.int16),
                           np.linspace(vol, -vol, num=size - h, dtype=np.int16)))


def _nze(size, vol):
    return np.array([random.randint(-vol, vol) for _ in range(size)],
                    dtype=np.int16)


_builders = {
    "SAW": _saw,
    "SQU": _squ,
    "SIN": _sin,
    "TRI": _tri,
    "NZE": _nze,
}


def get_wave(name, size=256, volume=28000):
    """Return a cached int16 waveform array for `name`. Builds on first use."""
    key = (name, size)
    w = _cache.get(key)
    if w is None:
        w = _builders[name](size, volume)
        _cache[key] = w
    return w


def wave_names():
    return list(_builders.keys())


_rot_cache = {}  # (name, size) -> np.array, half-buffer-rotated copy of get_wave()


def get_wave_rotated(name, size=256, volume=28000):
    """Same waveform as get_wave(), phase-shifted 180 -- i.e. the second
    half of the buffer first, then the first half. For a detuned second
    oscillator that would otherwise start in phase with the first: they
    read the same buffer from sample 0 at note-on, so the two are in phase
    at the exact moment amplitude is highest (the attack), which is when
    their summed peak is most likely to exceed int16 range. Starting osc2
    at the opposite point in the cycle maximizes separation at that moment.
    Built once and cached, like get_wave() -- not a per-voice or per-note
    cost."""
    key = (name, size)
    w = _rot_cache.get(key)
    if w is None:
        base = get_wave(name, size, volume)
        half = size // 2
        w = np.concatenate((base[half:], base[:half]))
        _rot_cache[key] = w
    return w


# --- envelope shapes for one-shot LFOs -------------------------------
# A synthio.LFO with once=True runs its waveform once and then holds the
# final sample forever. So a buffer holding nothing but a rise 0 -> peak
# already IS attack-then-hold: there is no need to write a plateau after
# the rise, because the LFO supplies one for free and for as long as the
# key is down. Release re-runs the same rise through a CONSTRAINED_LERP
# with swapped endpoints -- see ahr_envelope.py.

ENV_SIZE = 64
ENV_PEAK = 32767


def env_buffer():
    """A writable buffer for an AHR envelope shape."""
    return np.zeros(ENV_SIZE, dtype=np.int16)


_ramp = None


def ramp_wave():
    """A cached 0 -> peak ramp, for one-shot LFOs used as a POSITION.

    Two samples is all it takes: synthio interpolates between waveform
    entries, so (0, ENV_PEAK) with once=True is a clean linear ramp that
    holds at the top -- the tutorial's idiom for fade-ins and bends.

    Note this is NOT interchangeable with LFO(waveform=None): the default
    waveform is a zero-centred triangle that would come back down again.
    A ramp has to be spelled out.

    Read-only and shared by every user, unlike the envelope shape buffers,
    which are per-instance because they get rewritten in place."""
    global _ramp
    if _ramp is None:
        _ramp = np.array((0, ENV_PEAK), dtype=np.int16)
    return _ramp


def _curve_ramp(start, stop, n, curve):
    """Normalized ramp start -> stop over n points, raised to the integer
    power `curve`. Repeated multiply rather than `**`: elementwise float
    multiply is already proven on ulab, `**` is not.

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

    `curve` is an integer exponent: 1 = linear, 2+ = increasingly
    fast-start, easing into the peak. That shape is chosen for what it does
    at the OTHER end. The release reruns this same buffer through a
    CONSTRAINED_LERP with swapped endpoints, i.e. `V * (1 - s(t))`, so

        s(t) = 1 - (1-t)^curve   =>   release = V * (1-t)^curve

    which is the conventional decay: quick initial drop, long tail. The
    obvious alternative, s(t) = t^curve, makes the release `V * (1 - t^curve)`
    -- still at 75% of its value halfway through at curve=2, hanging near the
    top and then falling off a cliff. A mirrored attack, not a decay.

    NOTE this is a deliberate divergence from the synthio tutorial, whose
    PRODUCT(lerp, lerp, 1) is t^2, the shape described above. The tutorial
    keeps attack and release shapes independent, so it can afford t^2 for the
    rise; sharing one buffer means the release gets the casting vote.

    There is deliberately no hold segment and no second, falling buffer:
      - the hold is what `once=True` already does after the last sample
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
        # Array-times-scalar and array-plus-scalar are both fine.
        # Endpoints stay exact for any curve because linspace pins its last
        # element: (1-t) is exactly 1.0 at index 0 and exactly 0.0 at the end.
        buf[:] = np.array(
            _curve_ramp(1.0, 0.0, n, curve) * (-ENV_PEAK) + ENV_PEAK,
            dtype=np.int16)


# --- Waves: string-keyed factory + WAV loading, for interactive use ---

_NAME_ALIASES = {
    "SIN": "SIN", "SINE": "SIN",
    "SQU": "SQU", "SQUARE": "SQU",
    "SAW": "SAW",
    "TRI": "TRI", "TRIANGLE": "TRI",
    "NZE": "NZE", "NOISE": "NZE",
}


class Waves:
    """
    Generate waveforms for either oscillator or LFO use.
    By default, size is 256, volume is max +-32767
    """

    waveform_types = ("SIN", "SQU", "SAW", "TRI", "SIL", "NZE")

    @staticmethod
    def make_waveform(waveid, size=256, volume=32767):
        """Return a waveform by string name, one of `waveform_types`.

        Delegates to `get_wave()` for the types it also builds, rather than
        generating them a second way; SIL has no `get_wave` equivalent and
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
        """Triangle waveform. `get_wave`'s TRI is symmetric about 0, so this
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

    @staticmethod
    def lfo_ramp_up_pos():
        """Simple two-element ramp-up waveform for synthio.LFO (which does interpolation)"""
        return np.array((0, 32767), dtype=np.int16)

    @staticmethod
    def lfo_ramp_down_pos():
        """Simple two-element row-downwaveform for synthio.LFO (which does interpolation)"""
        return np.array((32767, 0), dtype=np.int16)

    @staticmethod
    def lfo_triangle_pos():
        """Simple three-element triangle waveform for synthio.LFO (which does interpolation)"""
        return np.array((0, 32767, 0), dtype=np.int16)

    @staticmethod
    def lfo_triangle():
        """Simple four-element triangle waveform for synthio.LFO (which does interpolation)"""
        return np.array((0, 32767, 0, -32767), dtype=np.int16)

    @staticmethod
    def from_ar_times(attack_time=1, release_time=1):
        """
        Generate a fake Attack/Release 'Envelope' using an LFO waveform.
        This is a dumb way of doing it, but since we cannot get .value()
        out of Envelope, we have to fake it with an LFO.
        """
        a10 = int(attack_time * 10)
        r10 = int(release_time * 10)
        a = [i * 65535 // a10 - 32767 for i in range(a10)]
        r = [32767 - i * 65535 // r10 for i in range(r10)]
        return Waves.from_list(a + [32767] + r)

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
