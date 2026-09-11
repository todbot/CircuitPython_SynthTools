# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# wavetable_synth.py -- polyphonic wavetable synth instrument, built on the
# Synth engine (synth.py) and the Wavetable waveform-buffer tool
# (wavetable.py).
#
# All sounding notes share self._wavetable.waveform by reference, so setting
# wave_pos morphs already-sounding notes live: the lerp writes into the one
# buffer synthio is reading from. O(1) in polyphony.

import gc

import synthio

from .synth import Synth
from .wavetable import Wavetable


class WavetableSynth(Synth):
    """Polyphonic wavetable synth: one Note per key, its waveform a
    position (wave_pos) lerped between two adjacent frames of a loaded
    wavetable WAV file (wave_file), through the shared Synth
    filter/envelope graph.

    All sounding notes share the Wavetable's waveform buffer by
    reference, so moving wave_pos morphs already-sounding notes live:
    the lerp writes into the one buffer synthio is reading from, O(1) in
    polyphony regardless of how many notes are held.

    An optional LFO can sweep the wavetable position from wave_pos up to
    wave_pos + wave_lfo_range. This affects all notes playing.

    Unlike every other modulation source in this library, this one cannot
    live in the synthio block graph (Note.waveform is a plain fixed
    buffer, not a block-driven parameter), so update() must be called
    from the main loop to actually move it.
    """

    # synthio's mix bus soft-limits above +-28000 and a full-scale wavetable
    # note is already ~0.5 FS, so undivided polyphony compresses chords into
    # that limiter. Scale each voice down; make the level back at
    # mixer.voice[0].level. Read per note-on, so it can be changed on the
    # class at any time (takes effect on the next note); like Synth.FILT_F_MAX.
    WT_HEADROOM = 0.5

    # Read at Wavetable construction (file change / wave_file setter), not per
    # note-on. True (default) preloads the whole file (~32 KB for a 64x256
    # table) so the wave-LFO sweep does zero file I/O; False reads each wave on
    # demand, for a table too large for RAM. Set on the class before building.
    WT_PRELOAD = True

    _PARAMS = Synth._PARAMS + (
        "wave_file",
        "wave_pos",
        "wave_lfo_range",
        "wave_lfo_rate",
    )

    # class attrs: base __init__ calls _recompile() before subclass setup
    _wavetable = None
    _wt_path = None
    _wave_lfo_mid = None

    def _recompile(self):
        super()._recompile()
        p = self.patch
        if p.wave_file != self._wt_path:  # heavy: only on file change
            # drop the old ~32 KB table before the new read: otherwise the peak
            # is 2x table, one contiguous block that can MemoryError on a
            # fragmented mid-session heap. A failed load then leaves
            # self._wavetable None (needs another wave_file write), which beats
            # silently keeping a stale table under a silent 2x-RAM spike.
            self._wavetable = None
            gc.collect()
            self._wavetable = Wavetable(p.wave_file, preload=self.WT_PRELOAD)
            self._wt_path = p.wave_file

        lrate = getattr(p, "wave_lfo_rate", 0)
        self._wave_lfo_range = getattr(p, "wave_lfo_range", 0)
        self._wave_pos = getattr(p, "wave_pos", 0)

        if self._wave_lfo_mid is None:
            wave_lfo = synthio.LFO(once=False, rate=lrate)
            # this is the min/max'd version of the wave_pos LFO
            self._wave_lfo_mid = synthio.Math(
                synthio.MathOperation.MID,
                wave_lfo,  # a
                0,  # b
                self.num_waves - 1,
            )  # c
            self.synthio.blocks.append(self._wave_lfo_mid)

        self._wave = self._wavetable.waveform  # cache ref to the waveform
        self.recalculate_wave_lfo()
        self.update()

    def _decompile(self):
        super()._decompile()
        self.patch.wave_file = self._wt_path
        self.patch.wave_pos = self._wave_pos
        self.patch.wave_lfo_range = self._wave_lfo_range
        self.patch.wave_lfo_rate = self._wave_lfo_mid.a.rate

    def _make_notes(self, midi_note, velocity):
        self._last_velocity = velocity

        # if self._wave_lfo_once and not self.voices:
        #    self._wave_lfo_mid.a.retrigger()

        f = synthio.midi_to_hz(midi_note)
        # fmt: off
        return (synthio.Note(f, waveform=self._wave, envelope=self._env,
                             amplitude=velocity / 127 * self.WT_HEADROOM,
                             filter=self._make_filter(),
                             bend=self._bend_cur),)
        # fmt: on

    def update(self):
        """Push the wave-position LFO's current value into the shared
        Wavetable buffer. Call as often as possible from the main loop.
        """
        pos = self._wave_lfo_mid.value
        self._wavetable.set_wave_pos(pos)

    def recalculate_wave_lfo(self):
        """Recompute wave_lfo scale & offset from pos and range"""
        lfo = self._wave_lfo_mid.a  # .a is where the LFO lives
        lscale = self._wave_lfo_range / 2
        loffset = self.wave_pos + self._wave_lfo_range - lscale
        lfo.scale = lscale
        lfo.offset = loffset

    @property
    def wave_pos(self):
        """wave_pos is also the floor of the wave-LFO sweep: while the
        sweep is active, the next update() tick will move away from
        whatever this setter writes."""
        return self._wave_pos  # lfo_mid.a.offset

    @wave_pos.setter
    def wave_pos(self, v):
        self._wave_pos = v
        self.recalculate_wave_lfo()

    @property
    def wave_lfo_range(self):
        """Range of wave position LFO, in float wave indexes"""
        return self._wave_lfo_range

    @wave_lfo_range.setter
    def wave_lfo_range(self, v):
        self._wave_lfo_range = v
        self.recalculate_wave_lfo()

    @property
    def wave_lfo_rate(self):
        """Speed of the wave-position LFO, in Hz."""
        return self._wave_lfo_mid.a.rate

    @wave_lfo_rate.setter
    def wave_lfo_rate(self, v):
        self._wave_lfo_mid.a.rate = v

    @property
    def wave_file(self):
        return self._wt_path

    @wave_file.setter
    def wave_file(self, v):
        if v != self._wt_path:  # reopens file; next note-on uses it
            self._wavetable = None  # free the old table first (see _recompile)
            gc.collect()
            self._wavetable = Wavetable(v, preload=self.WT_PRELOAD)
            self._wave = self._wavetable.waveform
            self._wt_path = v
            self._wavetable.set_wave_pos(self._wave_pos)

    # @property
    # def wave_lfo_shape(self):
    #     """ "triangle" or "saw", only distinguishable in repeat mode; see
    #     the class docstring."""
    #     return self._wave_lfo_shape

    # @wave_lfo_shape.setter
    # def wave_lfo_shape(self, v):
    #     self._wave_lfo_shape = _norm_wave_lfo_shape(v)  # pure dict-key selection, no rebuild

    # @property
    # def wave_lfo_once(self):
    #     """True: the sweep fires once per note-on (from silence) and
    #     holds. False: it runs continuously."""
    #     return self._wave_lfo_once

    # @wave_lfo_once.setter
    # def wave_lfo_once(self, v):
    #     self._wave_lfo_once = bool(v)  # pure dict-key selection, no rebuild

    # @property
    # def wave_lfo_vel(self):
    #     """0-1 sensitivity of the sweep's depth to note velocity. 0 =
    #     uniform depth; 1.0 = depth tracks velocity/127, the same shape as
    #     fenv_vel."""
    #     return self._wave_lfo_vel

    # @wave_lfo_vel.setter
    # def wave_lfo_vel(self, v):
    #     self._wave_lfo_vel = v
    #     #self._recompute_eff_max()

    @property
    def num_waves(self):
        """Frame count of the loaded wavetable; the natural upper bound
        for wave_pos_max, e.g. wt.wave_pos_max = wt.num_waves - 1."""
        return self._wavetable.num_waves
