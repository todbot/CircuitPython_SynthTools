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

import synthio

from .synth import Synth
from .waves import ramp_wave, saw_wave
from .wavetable import Wavetable

WAVE_LFO_EPS = 0.01  # below one audibly distinct step of wavetable morph
WAVE_LFO_SHAPES = ("triangle", "saw")


def _norm_wave_lfo_shape(v):
    """Fold any case/unknown value to a valid _wave_lfos dict key, the
    same safe-fallback shape as Synth's FILTER_MODES.get(p.filt_type);
    a bad patch field must never KeyError _active_wave_lfo."""
    v = str(v).lower()
    return v if v in WAVE_LFO_SHAPES else "triangle"


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
    wave_pos_max (wave_lfo_shape "triangle"/"saw", wave_lfo_once for a
    one-shot sweep vs. a free-running one, wave_lfo_rate, and wave_lfo_vel
    to scale the sweep's depth by note velocity). wave_lfo_shape only
    matters in repeat mode: a one-shot sweep is a monotonic rise
    regardless of shape, so "triangle" and "saw" sound identical when
    wave_lfo_once is set. In "once" mode the sweep retriggers only when a
    note starts from silence, like vib_delay's fade-in: there is one
    shared wavetable buffer for the whole synth, so retriggering on every
    note-on would yank already-sounding chord notes' wave position back to
    the floor.

    Unlike every other modulation source in this library, this one cannot
    live in the synthio block graph (Note.waveform is a plain fixed
    buffer, not a block-driven parameter), so update() must be called
    from the main loop to actually move it.
    """

    _PARAMS = Synth._PARAMS + (
        "wave_pos",
        "wave_file",
        "wave_pos_max",
        "wave_lfo_rate",
        "wave_lfo_shape",
        "wave_lfo_once",
        "wave_lfo_vel",
    )

    # class attrs: base __init__ calls _recompile() before subclass setup
    _wavetable = None
    _wt_path = None
    _wave_pos = 0
    _wave_lfos = None  # dict {(shape, once): synthio.LFO}, built once
    _wave_lfo_shape = "triangle"
    _wave_lfo_once = False
    _wave_pos_max = 0
    _wave_lfo_vel = 0.0
    _last_velocity = 127
    _wave_pos_eff_max = 0
    _wave_pos_last_written = None

    def _recompile(self):
        super()._recompile()
        p = self.patch
        if p.wave_file != self._wt_path:  # heavy: only on file change
            self._wavetable = Wavetable(p.wave_file)
            self._wt_path = p.wave_file
        self._wave_pos = getattr(p, "wave_pos", 0)
        self._wavetable.set_wave_pos(self._wave_pos)
        self._wave = self._wavetable.waveform

        # Four fixed LFOs, one per (shape, once) combination, built once and
        # never replaced: synthio.LFO.waveform is read-only, so a shape/mode
        # change is a dict-key selection, never a rebuild. None is reachable
        # from a Note (waveform is a plain buffer, not a block), so all four
        # have to be rooted here or they never tick.
        #
        # "triangle" repeat needs no buffer: synthio's default (waveform=
        # None) is a bipolar -1..1 triangle, so scale/offset do the same
        # half-swing shift filt_lfo/vib_lfo use to land it in 0..1.
        #
        # "triangle" once does NOT get that treatment. Measured on hardware
        # (rp2040, CircuitPython 10.3.0-alpha.3), LFO(once=True) with the
        # default waveform rises to ~0.96, then falls all the way to -1.0 and
        # HOLDS THERE: it traces the whole bipolar triangle once and stops at
        # its last sample, the trough. So once=True uses ramp_wave() for both
        # shapes, measured to rise cleanly 0..1 and hold at the top.
        #
        # "saw" repeat has no default-waveform equivalent, the built-in shape
        # always being a triangle, so it needs saw_wave().
        #
        # Consequence: "triangle" and "saw" are IDENTICAL in once mode, both
        # the same monotonic rise holding at the top. Shape only matters in
        # repeat, where triangle goes back down and saw snaps to the floor.
        if self._wave_lfos is None:
            self._wave_lfos = {
                ("triangle", False): synthio.LFO(once=False, scale=0.5, offset=0.5),
                ("triangle", True): synthio.LFO(waveform=ramp_wave(), once=True),
                ("saw", False): synthio.LFO(waveform=saw_wave(), once=False),
                ("saw", True): synthio.LFO(waveform=ramp_wave(), once=True),
            }
            for lfo in self._wave_lfos.values():
                self.synthio.blocks.append(lfo)
        self._wave_pos_max = getattr(p, "wave_pos_max", self._wave_pos)
        self._wave_lfo_vel = getattr(p, "wave_lfo_vel", 0.0)
        self._wave_lfo_shape = _norm_wave_lfo_shape(getattr(p, "wave_lfo_shape", "triangle"))
        self._wave_lfo_once = bool(getattr(p, "wave_lfo_once", False))
        rate = getattr(p, "wave_lfo_rate", 0.5)
        for lfo in self._wave_lfos.values():  # keep every combo ready to switch to
            lfo.rate = rate
        self._wave_pos_last_written = None
        self._recompute_eff_max()

    def _decompile(self):
        super()._decompile()
        self.patch.wave_file = self._wt_path
        self.patch.wave_pos = self._wave_pos
        self.patch.wave_pos_max = self._wave_pos_max
        self.patch.wave_lfo_rate = self._active_wave_lfo.rate
        self.patch.wave_lfo_shape = self._wave_lfo_shape
        self.patch.wave_lfo_once = self._wave_lfo_once
        self.patch.wave_lfo_vel = self._wave_lfo_vel

    def _make_notes(self, midi_note, velocity):
        self._last_velocity = velocity
        self._recompute_eff_max()
        # Retrigger only when starting from silence, the same rule
        # Synth.note_on() applies to _vib_fade: there is one shared waveform
        # buffer for the whole synth, so retriggering on every note-on would
        # yank already-sounding chord notes' wave position back to the floor.
        if self._wave_lfo_once and not self.voices:
            self._active_wave_lfo.retrigger()
        f = synthio.midi_to_hz(midi_note)
        # fmt: off
        return (synthio.Note(f, waveform=self._wave, envelope=self._env,
                             amplitude=velocity / 127,
                             filter=self._make_filter(),
                             bend=self._bend_cur),)
        # fmt: on

    @property
    def _active_wave_lfo(self):
        return self._wave_lfos[(self._wave_lfo_shape, self._wave_lfo_once)]

    def _gain(self, velocity):
        """1.0 = full sweep depth. wave_lfo_vel scales toward velocity/127,
        the same shape as Synth._voice_fenv_gain()'s fenv_vel."""
        if not self._wave_lfo_vel:
            return 1.0
        return 1.0 - self._wave_lfo_vel + self._wave_lfo_vel * (velocity / 127.0)

    def _recompute_eff_max(self):
        """Last-note-wins sweep endpoint. There is exactly one shared
        waveform buffer for the whole synth, so unlike fenv_vel this
        cannot be a per-voice block: it's Python state, recomputed at
        every note-on and by any setter that could change the answer."""
        gain = self._gain(self._last_velocity)
        self._wave_pos_eff_max = self._wave_pos + (self._wave_pos_max - self._wave_pos) * gain
        # "off" is wave_pos_max <= wave_pos, not just ==: the sweep runs
        # wave_pos -> wave_pos_max, so a ceiling at or below the floor has no
        # sweep. <= rather than == also closes a footgun, since moving
        # wave_pos alone would otherwise flip on an INVERTED sweep the moment
        # it passed wave_pos_max rather than staying off.
        #
        # update()'s early-out never runs while this holds, so without this
        # settle, disabling the sweep would leave the wavetable stranded
        # wherever the LFO last left it. Guarded by the dedup field, so it
        # only fires on the actual transition.
        if self._wave_pos_max <= self._wave_pos and self._wave_pos_last_written != self._wave_pos:
            self._wavetable.set_wave_pos(self._wave_pos)
            self._wave_pos_last_written = self._wave_pos

    def update(self):
        """Push the wave-position LFO's current value into the shared
        Wavetable buffer. Call as often as possible from the main loop.

        Cheap no-op when wave_pos_max <= wave_pos (the default, and any
        patch that has never touched this feature): a synth that never
        touches this feature pays nothing whether update() is called every
        frame or never called at all. When active, a second guard skips
        Wavetable.set_wave_pos() (real WAV file reads plus a ulab lerp)
        unless the position moved by more than WAVE_LFO_EPS since the last
        write.
        """
        if self._wave_pos_max <= self._wave_pos:
            return
        t = self._active_wave_lfo.value
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        pos = self._wave_pos + (self._wave_pos_eff_max - self._wave_pos) * t
        last = self._wave_pos_last_written
        if last is not None and abs(pos - last) < WAVE_LFO_EPS:
            return
        self._wavetable.set_wave_pos(pos)
        self._wave_pos_last_written = pos

    @property
    def wave_pos(self):
        """wave_pos is also the floor of the wave-LFO sweep: while the
        sweep is active, the next update() tick will move away from
        whatever this setter writes."""
        return self._wave_pos

    @wave_pos.setter
    def wave_pos(self, v):
        self._wave_pos = v
        self._wavetable.set_wave_pos(v)  # in-place: morphs sounding notes
        self._wave_pos_last_written = None
        self._recompute_eff_max()

    @property
    def wave_file(self):
        return self._wt_path

    @wave_file.setter
    def wave_file(self, v):
        if v != self._wt_path:  # reopens file; next note-on uses it
            self._wavetable = Wavetable(v)
            self._wt_path = v
            self._wavetable.set_wave_pos(self._wave_pos)
            self._wave = self._wavetable.waveform
            self._wave_pos_last_written = None

    @property
    def wave_pos_max(self):
        """The ceiling of the wave-LFO sweep. At or below wave_pos the
        sweep is off; above it, the LFO sweeps wave_pos -> wave_pos_max."""
        return self._wave_pos_max

    @wave_pos_max.setter
    def wave_pos_max(self, v):
        self._wave_pos_max = v
        self._recompute_eff_max()

    @property
    def wave_lfo_rate(self):
        """Speed of the wave-position LFO, in Hz."""
        return self._active_wave_lfo.rate

    @wave_lfo_rate.setter
    def wave_lfo_rate(self, v):
        for lfo in self._wave_lfos.values():  # keep every combo ready to switch to
            lfo.rate = v

    @property
    def wave_lfo_shape(self):
        """ "triangle" or "saw", only distinguishable in repeat mode; see
        the class docstring."""
        return self._wave_lfo_shape

    @wave_lfo_shape.setter
    def wave_lfo_shape(self, v):
        self._wave_lfo_shape = _norm_wave_lfo_shape(v)  # pure dict-key selection, no rebuild

    @property
    def wave_lfo_once(self):
        """True: the sweep fires once per note-on (from silence) and
        holds. False: it runs continuously."""
        return self._wave_lfo_once

    @wave_lfo_once.setter
    def wave_lfo_once(self, v):
        self._wave_lfo_once = bool(v)  # pure dict-key selection, no rebuild

    @property
    def wave_lfo_vel(self):
        """0-1 sensitivity of the sweep's depth to note velocity. 0 =
        uniform depth; 1.0 = depth tracks velocity/127, the same shape as
        fenv_vel."""
        return self._wave_lfo_vel

    @wave_lfo_vel.setter
    def wave_lfo_vel(self, v):
        self._wave_lfo_vel = v
        self._recompute_eff_max()

    @property
    def num_waves(self):
        """Frame count of the loaded wavetable; the natural upper bound
        for wave_pos_max, e.g. wt.wave_pos_max = wt.num_waves - 1."""
        return self._wavetable.num_waves
