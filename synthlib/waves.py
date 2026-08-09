# waves.py - waveform name -> ulab int16 array, built once, cached forever.
# All notes share these arrays by reference: zero per-note allocation.

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


def _curve_ramp(start, stop, n, curve):
    """Normalized ramp start -> stop over n points, raised to the integer
    power `curve`. Repeated multiply rather than `**`: elementwise float
    multiply is already proven on ulab, `**` is not.

    For start/stop in [0,1] the result stays in [0,1], so scaling by
    ENV_PEAK cannot leave int16 range.

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
    """Rise 0 -> ENV_PEAK across the WHOLE buffer.

    `curve` is an integer exponent on the rise: 1 = linear, 2 = squared,
    which starts slow and finishes fast -- the shape the synthio tutorial's
    PRODUCT(lerp, lerp, 1) produces and calls "exponential". 3+ is steeper.

    There is deliberately no hold segment and no falling variant:
      - the hold is what `once=True` already does after the last sample, so
        writing a plateau here would only shorten the rise and force the
        release rate to compensate for it;
      - the fall re-runs this same shape through a CONSTRAINED_LERP with
        swapped endpoints, and a second buffer would be unreachable anyway
        because synthio.LFO.waveform is read-only.

    Written IN PLACE, so every voice sharing this array morphs live."""
    curve = _clamp_curve(curve)
    n = len(buf)
    if curve == 1:
        # integer linspace direct: bit-identical to a plain linear ramp and
        # one float array cheaper
        buf[:] = np.linspace(0, ENV_PEAK, num=n, dtype=np.int16)
    else:
        buf[:] = np.array(_curve_ramp(0, 1.0, n, curve) * ENV_PEAK,
                          dtype=np.int16)
