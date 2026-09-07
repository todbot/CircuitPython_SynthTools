# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Minimal synthio stub: enough to exercise block identity, sharing, param
routing and the AHR envelope wiring. No DSP."""


def _v(x):
    """Resolve a BlockInput-ish thing to a float."""
    return x.value if hasattr(x, "value") else float(x)


class FilterMode:
    LOW_PASS = "LOW_PASS"
    HIGH_PASS = "HIGH_PASS"
    BAND_PASS = "BAND_PASS"
    NOTCH = "NOTCH"


class MathOperation:
    """Only the operations synthtools' engine actually uses. Definitions are
    copied from the real synthio docs so the arithmetic matches the device."""
    SUM = "SUM"                            # a+b+c
    PRODUCT = "PRODUCT"                    # a*b*c
    LERP = "LERP"                          # a*(1-c) + b*c
    CONSTRAINED_LERP = "CONSTRAINED_LERP"  # ...with c clamped to 0..1
    MID = "MID"                            # the middle of the three inputs


class Math:
    # real synthio defaults c to 1.0, not 0.0; PRODUCT(a, b) has to be a*b
    def __init__(self, operation, a=0.0, b=0.0, c=1.0):
        self.operation = operation
        self.a, self.b, self.c = a, b, c

    @property
    def value(self):
        a, b, c = _v(self.a), _v(self.b), _v(self.c)
        if self.operation == "SUM":
            return a + b + c
        if self.operation == "PRODUCT":
            return a * b * c
        if self.operation == "LERP":
            return a * (1.0 - c) + b * c
        if self.operation == "CONSTRAINED_LERP":
            t = min(max(c, 0.0), 1.0)
            return a * (1.0 - t) + b * t
        if self.operation == "MID":
            return sorted((a, b, c))[1]
        raise ValueError(self.operation)


class LFO:
    def __init__(self, waveform=None, rate=1.0, scale=1.0, offset=0.0,
                 once=False, phase_offset=0.0):
        self._waveform = waveform
        self.rate = rate
        self.scale = scale
        self.offset = offset
        self.once = once
        self.phase_offset = phase_offset
        self.phase = 0.0          # stub: 0..1 through the waveform
        self.retriggered = 0

    @property
    def waveform(self):
        """Deliberately READ-ONLY, matching real synthio.

        On CircuitPython 10.3.0-alpha.4 (rp2350), `lfo.waveform = arr` raises
        AttributeError. An earlier engine design swapped buffers here to do
        its release and crashed at every note-off on hardware, while an
        earlier version of this stub, which allowed the assignment, passed
        happily. A stub that is more permissive than the platform is worse
        than no stub, so this one refuses too.
        """
        return self._waveform

    def retrigger(self):
        self.phase = 0.0
        self.retriggered += 1

    def _sample(self):
        w = self.waveform
        if w is None or len(w) == 0:
            # Real synthio uses a zero-centred triangle when waveform is
            # None: 0 -> +1 -> 0 -> -1 -> 0. Returning a flat 0.0 here (as
            # this stub used to) makes every default-waveform LFO look dead
            # and silently defeats any test of scale/offset arithmetic.
            p = self.phase % 1.0
            if p < 0.25:
                return p * 4.0
            if p < 0.75:
                return 2.0 - p * 4.0
            return p * 4.0 - 4.0
        i = int(self.phase * (len(w) - 1))
        return w[i] / 32767.0

    @property
    def value(self):
        return self._sample() * _v(self.scale) + _v(self.offset)


class Envelope:
    def __init__(self, attack_time=0.0, decay_time=0.0, sustain_level=1.0,
                 release_time=0.0, attack_level=1.0):
        self.attack_time = attack_time
        self.decay_time = decay_time
        self.sustain_level = sustain_level
        self.release_time = release_time
        self.attack_level = attack_level


class Biquad:
    def __init__(self, mode, frequency=1000.0, Q=1.0):
        self.mode = mode
        self.frequency = frequency
        self.Q = Q


class Note:
    def __init__(self, frequency, waveform=None, envelope=None, filter=None,
                 amplitude=1.0, bend=0.0, panning=0.0):
        self.frequency = frequency
        self.waveform = waveform
        self.envelope = envelope
        self.filter = filter
        self.amplitude = amplitude
        self.bend = bend
        self.panning = panning


class Synthesizer:
    def __init__(self, sample_rate=44100, channel_count=1):
        self.sample_rate = sample_rate
        self.channel_count = channel_count
        self.blocks = []
        self.pressed = []

    def press(self, notes):
        if isinstance(notes, (tuple, list)):
            self.pressed.extend(notes)
        else:
            self.pressed.append(notes)

    def release(self, notes):
        if not isinstance(notes, (tuple, list)):
            notes = (notes,)
        for n in notes:
            if n in self.pressed:
                self.pressed.remove(n)


def midi_to_hz(n):
    return 440.0 * (2.0 ** ((n - 69) / 12.0))
