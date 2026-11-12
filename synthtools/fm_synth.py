# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# fm_synth.py -- a two-operator phase-modulation synth voice, built on the
# Synth engine (synth.py).
#
# Why NOT an audio-rate modulator on note.bend, the obvious design:
#
#   note.bend = SUM(shared_bend_graph, fm_lfo)
#   fm_lfo    = LFO(waveform=modulator_wave, rate=carrier_hz * fm_ratio,
#                    scale=fm_index)
#
# synthio's Math/LFO blocks recompute their VALUE only once every 256
# samples, 172 Hz at 44.1 kHz, so any modulator above ~86 Hz aliases. Middle
# C at fm_ratio=1 puts the modulator at 261.6 Hz, which zero-order-hold
# folds down to 89 Hz; one semitone up drags that alias to 105 Hz, so a 6%
# pitch change swings the perceived modulation rate 17% the WRONG way. This
# mechanism cannot render real FM sidebands.
#
# What is built instead: a baked-in phase-modulation carrier. Classic
# 2-operator FM/PM is
#
#   sin(2*pi*t + index * sin(2*pi*ratio*t))
#
# which is periodic in ONE carrier cycle whenever ratio is an integer, so it
# pre-renders into an ordinary single-cycle table, the same kind of buffer
# waves.py builds for SAW/SIN/TRI. The sidebands are already IN the waveform
# before the note plays, so there is no block-rate ceiling to hit. It is
# essentially a wavetable. The buffer is shared and rewritten in place, so
# turning fm_ratio or fm_index reaches every sounding voice in one write.
#
# Caveats:
#
# - fm_ratio MUST be an integer, or the modulator's phase lands somewhere
#   other than a multiple of 2*pi and the table buzzes at its loop point.
# - Sine carrier, sine modulator only. Phase-distorting an arbitrary carrier
#   table (Casio CZ style) needs fancy-indexed gather, which the MicroPython
#   ulab fallback this project tests against does not implement.
# - fm_index is RADIANS: 0 = off, 1-3 = classic FM, 5+ = harsh.
# - No continuous mid-note sweep. Turning a knob rewrites the shared table,
#   which voices pick up over their next few samples rather than as a smooth
#   glide. Sweep filt_f/fenv_amount for continuous movement.
# - Not band-limited past the table: 256 samples carries at most 128
#   harmonics, and PM energy spreads to roughly ratio * (index + 1), so a
#   high ratio/index pair is aliased before the note plays. Keep both modest.
# - No feedback operator: it reads its own output, a cycle no pre-rendered
#   table can express. audiofilters.Distortion after the voice gets some
#   wavefolding.

import synthio
import ulab.numpy as np

from .synth import Synth
from .waves import random_phase_wave, warm_wave

#: single-cycle size of the baked PM carrier table
FM_WAVE_SIZE = 256


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

    Written in place so every voice sharing this buffer morphs the instant
    a knob changes, the same idiom as fill_env_rise()."""
    n = len(buf)
    theta = np.linspace(0, 2 * np.pi, num=n, endpoint=False)
    mod = np.sin(theta * ratio) * index
    buf[:] = np.array(np.sin(theta + mod) * volume, dtype=np.int16)


class FMSynth(Synth):
    """A two-operator phase-modulation voice: a carrier waveform pre-rendered
    from ``sin(theta + index * sin(ratio * theta))``, through the shared
    ``Synth`` filter/envelope graph.

    Patch fields, on top of the shared ``Synth`` ones:

        fm_ratio  modulator cycles per carrier cycle; MUST be a
                  non-negative integer (see the module docstring for why)
        fm_index  PM depth in radians; 0 = off, uses the plain ``wave``
                  oscillator instead, at the ordinary Synth voice cost

    ``fm_ratio`` and ``fm_index`` share ONE table, rewritten in place on
    every change, so one write reaches every sounding voice using it,
    regardless of polyphony, the same idiom ``fill_env_rise()`` uses for the
    filter/pitch envelope shape.
    """

    # Same mix-bus limiter as SubtractiveSynth.HEADROOM: make the level back
    # at mixer.voice[0].level. Read per note-on.
    HEADROOM = 0.5

    _PARAMS = Synth._PARAMS + ("wave", "fm_ratio", "fm_index")

    # class attrs: base __init__ builds its graph before this subclass has run
    # any setup of its own, so a patch-less FMSynth(engine) still plays
    _wave_name = "SAW"
    _fm_ratio = 1
    _fm_index = 0.0

    def __init__(self, synthesizer, patch=None):
        # The shared PM table is created HERE, before super().__init__()
        # runs its load_patch() -> _recompile(): it must exist by then, and
        # must never be replaced, since sounding voices reference it.
        self._pm_wave = np.zeros(FM_WAVE_SIZE, dtype=np.int16)
        super().__init__(synthesizer, patch)

    def _recompile(self):
        super()._recompile()
        p = self.patch
        self._wave_name = p.wave
        warm_wave(self._wave_name, self.synthio.sample_rate)  # note-on only slices
        self._fm_ratio = max(0, int(round(p.fm_ratio)))
        self._fm_index = p.fm_index
        fill_pm_wave(self._pm_wave, self._fm_ratio, self._fm_index)

    def _decompile(self):
        super()._decompile()
        p = self.patch
        p.wave = self._wave_name
        p.fm_ratio = self._fm_ratio
        p.fm_index = self._fm_index

    def _make_notes(self, midi_note, velocity):
        f = synthio.midi_to_hz(midi_note)
        if self._fm_index:
            waveform = self._pm_wave  # shared table: no random phase, see above
        else:
            waveform = random_phase_wave(
                self._wave_name, midi_note=midi_note, sample_rate=self.synthio.sample_rate
            )
        # fmt: off
        return (synthio.Note(f, waveform=waveform,
                             envelope=self._env, amplitude=velocity / 127 * self.HEADROOM,
                             filter=self._make_filter(), bend=self._bend_cur),)
        # fmt: on

    # --- live parameters ------------------------------------------------
    # fm_ratio and fm_index each rewrite the ONE shared PM table in place,
    # reaching every sounding voice using it with no per-voice node to find.

    @property
    def wave(self):
        return self._wave_name

    @wave.setter
    def wave(self, v):
        self._wave_name = v
        warm_wave(v, self.synthio.sample_rate)  # warms the cache for the next note-on

    @property
    def fm_ratio(self):
        return self._fm_ratio

    @fm_ratio.setter
    def fm_ratio(self, v):
        self._fm_ratio = max(0, int(round(v)))
        fill_pm_wave(self._pm_wave, self._fm_ratio, self._fm_index)

    @property
    def fm_index(self):
        return self._fm_index

    @fm_index.setter
    def fm_index(self, v):
        self._fm_index = v
        fill_pm_wave(self._pm_wave, self._fm_ratio, self._fm_index)
