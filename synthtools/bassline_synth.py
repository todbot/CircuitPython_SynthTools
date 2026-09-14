# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# bassline_synth.py -- the squelchy acid bassline voice, after the Roland
# TB-303: monophonic, one oscillator, per-step slide and accent.
#
# Built straight on Synth with `mono = True`: the slide is Synth's own
# glide given a per-step time, and one-voice stealing comes with the switch.
# There is no monosynth base class; nothing was left for one to hold.
#
# --- the two things that make it a 303 --------------------------------
#
# 1. A DECAY-ONLY filter envelope. The cutoff jumps to its peak at note-on
#    and falls back while the key is still down. Synth's AHR envelope holds
#    at peak instead of falling, which looks like the wrong shape, but AHR
#    with a NEGATIVE amount is exactly this:
#
#        filt_f      the peak the sweep starts from
#        fenv_amount -envmod * filt_f, so the sweep runs DOWNWARD
#        fenv_attack the fall time (a decay, despite the name)
#
#    The shape buffer is 1-(1-t)^curve, fast-then-easing, which run downward
#    is the quick drop and long tail the 303 is known for. Everything there
#    is still a shared block, so it stays O(1) live. FILT_F_MIN earns its
#    keep: envmod = 1.0 aims the sweep at 0 Hz and the clamp catches it.
#
#    envmod being a FRACTION of filt_f rather than a number of Hz is the
#    303's own arrangement, and why the envelope tracks the cutoff knob.
#
# 2. ACCENT, which must not contaminate the patch. An accented step raises
#    cutoff, resonance, envelope depth and level, all shared blocks here, so
#    the obvious implementation writes filt_f and filt_q and then
#    save_patch() stores the accented values as knob positions.
#
#    So accent writes the SPARE INPUTS of blocks Synth already built, never
#    the ones Synth reads back:
#
#        cutoff     _filt_sum.c    sum3()'s unused third input
#        resonance  _filt_q_blk.b  scalar_block()'s unused second input
#
#    Both sit inside the graph the voice already reads, so an accent is
#    still one write and still reaches a sounding note, while filt_f and
#    filt_q read back clean. Only fenv_amount has no spare slot; it is
#    derived from envmod anyway, so _decompile() re-derives it on save.

import synthio

from .audio_fx import EffectsChain, set_drive, tracking_filter
from .blocks import clamp, sum3
from .synth import FILTER_MODES, Synth
from .waves import get_wave, ramp_wave

try:
    import audiodelays
    import audiofilters
except ImportError:  # not in every CircuitPython build
    audiodelays = None
    audiofilters = None


class BasslineSynth(Synth):
    """Monophonic acid bassline synth after the Roland TB-303: one
    oscillator, a decay-only filter envelope, and per-step slide and
    accent.

    The 303's own controls map on as:

    ==========  ====================================================
    303 knob    here
    ==========  ====================================================
    tuning      ``transpose`` (semitones)
    cutoff      ``filt_f``, the peak the filter sweep starts from
    resonance   ``filt_q``
    env mod     ``envmod``, sweep depth as a FRACTION of filt_f
    decay       ``decay``, seconds, both the filter fall and the amp
    accent      ``accent``, how much an accented step is boosted
    ==========  ====================================================

    Play it a step at a time with note_on_step(), which takes the 303's
    per-step slide and accent flags; note_on() is the MIDI-style front end
    and accents anything at or above ``accent_velocity``.

    A slide TIES the two steps into one note, as the original does: the
    pitch glides and both envelopes carry on, with nothing pressed or
    released. That only works while the previous step is still sounding,
    so a sequencer must skip its ``note_off()`` on a slid step; see
    note_on_step(). Waveform is one shared buffer with no random
    phase, unlike SubtractiveSynth: a monosynth has no second oscillator
    to beat against, so a note-on allocates no waveform at all.

    ``envmod`` is the source of truth for the filter envelope's depth.
    ``fenv_amount`` is derived from it and from ``filt_f``, so writing
    ``fenv_amount`` directly is overwritten by the next change to either.
    """

    # fmt: off
    _PARAMS = Synth._PARAMS + ("wave", "envmod", "decay", "amp_level",
                               "accent", "accent_cutoff", "accent_q",
                               "accent_sweep_decay", "accent_sweep_max",
                               "slide_time", "transpose",
                               # the four STRUCTURAL fx_* fields are
                               # deliberately absent: a set_param() from a
                               # MIDI CC would silently mute the chain,
                               # since nothing here can reach into the
                               # mixer and re-play() the new tail
                               "fx_filter_mix", "fx_drive", "fx_drive_mix",
                               "fx_delay_ms", "fx_delay_mix", "fx_delay_decay")
    # fmt: on

    #: Inherently monophonic; accent and glide are both shared state
    #: that assumes a single voice.
    mono = True

    #: note_on() accents at or above this velocity. The 303's sequencer had
    #: a per-step accent switch rather than a velocity; this is the MIDI
    #: stand-in for it, and note_on_step() bypasses it entirely.
    accent_velocity = 100

    #: The filter sweep's fall time on an ACCENTED step, whatever ``decay``
    #: says. On the original the envelope decay is pinned near 200 ms for an
    #: accent, and that fixed short fall is most of why accents read as
    #: pluckier rather than merely louder.
    ACCENT_FALL = 0.2

    #: Seconds the accent sweep takes to ramp in at FULL resonance, 0 at
    #: none. The lag is what turns an accent from a step into a swell.
    ACCENT_LAG = 0.04

    #: ``filt_q``'s useful range, per ``Synth.filt_q``. The accent sweep's
    #: depth is normalized against it: on the original the Resonance pot is
    #: dual-gang and its second half is what drives the sweep circuit.
    Q_MIN = 0.6
    Q_MAX = 6.0

    # class attrs: Synth.__init__ builds its graph, and calls _make_env(),
    # before this subclass has run any setup of its own
    _wave_name = "SAW"
    _transpose = 0
    _envmod = 0.5
    _amp_level = 0.8
    _accent = 0.5
    _accent_cutoff = 4000.0
    _accent_q = 0.15
    _accent_sweep_decay = 0.55
    _accent_sweep_max = 1.6
    _slide_time = 0.06  # the stock 303's slide is RC-fixed at roughly this
    _decay = 0.05  # mirror of fenv_attack; accent overwrites the live one
    _fall = None  # what _fenv.attack actually holds, so writes can be guarded
    _acc_hz = 0.0  # accent boost per unit of sweep; see _refresh_accent_depth
    _accent_on = False
    _accent_sweep = 0.0  # performance state: never saved, never in _PARAMS
    _env_accent = None
    _env_accent_level = None  # what _env_accent was built for; see _accent_env()
    _filter = None  # the shared Biquad; see _build_filter()
    _cutoff = None  # its stable frequency node

    # --- the owned effects chain: class attrs; see _build_fx() ----------
    FX_BUFFER_SIZE = 1024
    FX_MAX_DELAY_MS = 1000  # buffer sizing only, not a knob; see fx_delay_ms
    _fx_filter_stages = 0
    _fx_filter_mix = 1.0
    _fx_hpf_f = 0.0  # 0 = off, the only spelling of it; see the property
    _fx_distortion_on = False
    _fx_drive = 0.0
    _fx_drive_mix = 0.0
    _fx_echo_on = False
    _fx_delay_ms = 300.0
    _fx_delay_mix = 0.0
    _fx_delay_decay = 0.3
    _fx = None  # the owned EffectsChain, lazily built by _build_fx()
    _fx_stage = None  # tracking_filter()'s Filter, if fx_filter_stages > 0
    _fx_dist = None  # audiofilters.Distortion, if fx_distortion_on
    _fx_delay = None  # audiodelays.Echo, if fx_echo_on

    def __init__(self, synthesizer, patch=None):
        # --- the extra cutoff CV: ONE object, no Math at all --------------
        #
        #   _accent_lag = LFO(ramp, once=True)   ->  _filt_sum.c
        #       .scale  = the accent boost, so the ramp carries it in
        #       .offset = a DC term that is always there
        #
        # On the original, resonance routes the accent pulse through a lag
        # circuit that makes the filter sweep UP into the note: the "wow" of
        # the acid sound. That needs the accent to ramp, which a plain
        # number cannot do.
        #
        # An LFO is `waveform * scale + offset`, so its own two inputs give
        # both the ramped term and the static one, and the obvious
        # SUM(bias, PRODUCT(accent, lag)) spelling is two Math blocks that
        # buy nothing. They are not free: every block in the graph is
        # re-evaluated each render, and measured on rp2040 those two cost
        # ~290 us per note-on in stolen interpreter time alone. Same
        # scale/offset idiom as Synth's filt_lfo_amount.
        #
        # Built BEFORE super(), which runs _recompile() -> _refresh_accent()
        # and needs somewhere to put the boost already; it depends on
        # nothing Synth builds, so the ordering costs nothing.
        self._accent_lag = synthio.LFO(waveform=ramp_wave(), rate=1000.0, once=True)
        super().__init__(synthesizer, patch)
        # sum3's spare third input, so this rides inside _filt_base, which
        # Synth already rooted: nothing here needs rooting of its own, and
        # a nested LFO ticks.
        self._filt_sum.c = self._accent_lag
        # _env_accent has no other home: Synth.__init__ calls _make_env()
        # directly rather than _rebuild_env(), and a patch-less synth never
        # reaches _recompile() at all.
        self._rebuild_env()

    # --- patch <-> live state -------------------------------------------

    def _recompile(self):
        super()._recompile()
        p = self.patch
        self._wave_name = getattr(p, "wave", "SAW")
        self._transpose = getattr(p, "transpose", 0)
        self._envmod = getattr(p, "envmod", 0.5)
        self._amp_level = getattr(p, "amp_level", 0.8)
        self._accent = getattr(p, "accent", 0.5)
        self._accent_cutoff = getattr(p, "accent_cutoff", 4000.0)
        self._accent_q = getattr(p, "accent_q", 0.15)
        self._accent_sweep_decay = getattr(p, "accent_sweep_decay", 0.55)
        self._accent_sweep_max = getattr(p, "accent_sweep_max", 1.6)
        self._slide_time = getattr(p, "slide_time", 0.06)
        self._decay = p.fenv_attack  # super() already wrote it into the block
        self._fall = p.fenv_attack  # ...and that is what the block holds
        get_wave(self._wave_name)  # warm the cache; note-on only reads it
        self._accent_on = False
        self._accent_sweep = 0.0
        self._refresh_accent_depth()  # before _refresh_accent(), which reads it
        self._refresh_accent()  # also derives fenv_amount from envmod
        self._rebuild_env()

        # --- the owned effects chain -------------------------------------
        # Compare the four STRUCTURAL fields against what's already live
        # BEFORE overwriting them: only a real shape change should drop
        # self._fx. A patch load that leaves the fx shape alone must reach
        # the live effects like every other param here, not freeze them.
        new_stages = getattr(p, "fx_filter_stages", 0)
        # `or 0.0` so a patch written before this field existed, or one saying
        # None, compares equal to one saying 0: two spellings of "off" would
        # otherwise read as a shape change on every load and drop the chain.
        new_hpf_f = getattr(p, "fx_hpf_f", 0.0) or 0.0
        new_distortion_on = getattr(p, "fx_distortion_on", False)
        new_echo_on = getattr(p, "fx_echo_on", False)
        structural_changed = (
            new_stages != self._fx_filter_stages
            or new_hpf_f != self._fx_hpf_f
            or new_distortion_on != self._fx_distortion_on
            or new_echo_on != self._fx_echo_on
        )
        self._fx_filter_stages = new_stages
        self._fx_hpf_f = new_hpf_f
        self._fx_distortion_on = new_distortion_on
        self._fx_echo_on = new_echo_on
        self._fx_filter_mix = getattr(p, "fx_filter_mix", 1.0)
        self._fx_drive = getattr(p, "fx_drive", 0.0)
        self._fx_drive_mix = getattr(p, "fx_drive_mix", 0.0)
        self._fx_delay_ms = getattr(p, "fx_delay_ms", 300.0)
        self._fx_delay_mix = getattr(p, "fx_delay_mix", 0.0)
        self._fx_delay_decay = getattr(p, "fx_delay_decay", 0.3)
        if structural_changed:
            self._fx = None  # rebuilt lazily, next .fx/.output access
        self._push_fx_live()

    def _decompile(self):
        super()._decompile()
        p = self.patch
        p.wave = self._wave_name
        p.transpose = self._transpose
        p.envmod = self._envmod
        p.amp_level = self._amp_level
        p.accent = self._accent
        p.accent_cutoff = self._accent_cutoff
        p.accent_q = self._accent_q
        p.accent_sweep_decay = self._accent_sweep_decay
        p.accent_sweep_max = self._accent_sweep_max
        p.slide_time = self._slide_time
        # super() saved whatever the last step left in the shared blocks,
        # which on an accented step is the boosted depth and the shortened
        # fall. Both have a real knob behind them, so re-derive rather than
        # store what accent left there.
        p.fenv_amount = -self._envmod * self._filt_f_blk.a
        p.fenv_attack = self._decay
        p.fx_filter_stages = self._fx_filter_stages
        p.fx_filter_mix = self._fx_filter_mix
        p.fx_hpf_f = self._fx_hpf_f
        p.fx_distortion_on = self._fx_distortion_on
        p.fx_drive = self._fx_drive
        p.fx_drive_mix = self._fx_drive_mix
        p.fx_echo_on = self._fx_echo_on
        p.fx_delay_ms = self._fx_delay_ms
        p.fx_delay_mix = self._fx_delay_mix
        p.fx_delay_decay = self._fx_delay_decay

    # --- the shared filter ------------------------------------------------
    # Mono, so ONE Biquad and one cutoff node serve every note: built once
    # and re-aimed, not allocated per note the way poly forces Synth to.
    # Holding still is what lets audio_fx point extra stages at this cutoff
    # once and have them track forever.

    def _build_filter(self):
        """Create the shared cutoff node and Biquad, once."""
        if self._filt_mode is None:
            self._filter = None
            return
        if self._cutoff is None:
            # sum3's spare inputs are the envelope and velocity, written
            # per note by _voice_cutoff below. Rooted, so it keeps
            # evaluating between notes rather than freezing on the last.
            self._cutoff = clamp(sum3(self._filt_base), self.FILT_F_MIN, self.FILT_F_MAX)
            self.synthio.blocks.append(self._cutoff)
        if self._filter is None or self._filter.mode != self._filt_mode:
            # only on a filt_type change; _cutoff survives it, so anything
            # tracking the cutoff is undisturbed
            self._filter = synthio.Biquad(
                self._filt_mode, frequency=self._cutoff, Q=self._filt_q_blk
            )

    @property
    def filter(self):
        """The one Biquad every note plays through.

        Its ``frequency`` is a stable node carrying the whole cutoff bus (
        filt_f, the filter LFO, the envelope sweep, the accent), so a
        downstream stage can point at it once and follow all of it. That is
        all ``audio_fx.EffectsChain`` needs.
        """
        self._build_filter()
        return self._filter

    def _voice_cutoff(self, midi_note, velocity):
        """One voice, so one cutoff node: re-aim it instead of rebuilding.

        Both spare inputs are written on EVERY note, including with 0.0 when
        the term is off. One node is reused here, so leaving a slot alone
        would carry the previous note's envelope or tracking offset into a
        note pressed after the knob went to zero.
        """
        if self._filt_mode is None:
            return None
        self._build_filter()
        offsets = self._voice_offsets(midi_note, velocity)
        inner = self._cutoff.a  # the SUM inside the clamp
        inner.b = self._fenv_cur if self._fenv_cur is not None else 0.0
        inner.c = offsets if offsets is not None else 0.0
        return self._cutoff

    def _make_filter(self):
        return self.filter

    # --- the owned effects chain (optional) -------------------------------
    # A specialized EffectsChain, not the general-purpose one: fixed order
    # (filter -> distortion -> echo, the acid-bass signal flow), built from
    # the same tracking_filter()/set_drive() free functions. The three
    # fx_*_on/fx_filter_stages fields are STRUCTURAL, deciding what exists;
    # everything else is a LIVE write into whatever is already built.

    def _fx_cfg(self):
        s = self.synthio
        return {
            "sample_rate": s.sample_rate,
            "channel_count": s.channel_count,
            "buffer_size": self.FX_BUFFER_SIZE,
        }

    def _build_fx(self):
        """Build the owned chain from the current fx_* fields, once.

        Atomic: everything lands in locals and self._fx/_fx_stage/_fx_dist/
        _fx_delay are only assigned once every requested piece succeeds.
        Assigning self._fx as each piece is built and then raising partway
        (audiofilters present but audiodelays isn't, say) would leave
        self._fx non-None with an fx_echo_on that never got its Echo:
        later code would treat the chain as already built and never retry.
        """
        if self._fx is not None:
            return
        chain = EffectsChain(self)
        stage = dist = delay = None
        # No filter to track with filt_type=None: an ordinary silent no-op,
        # like _voice_cutoff() returning None. tracking_filter() raises
        # ValueError for external callers who don't already know why;
        # internally we do, so drop the tracking stages rather than let that
        # surface from an `output` property read. The high-pass tracks
        # nothing, so it survives a filterless voice on its own.
        want_stages = self._fx_filter_stages if self._filt_mode is not None else 0
        if want_stages or self._fx_hpf_f:
            stage = chain.add(
                tracking_filter(
                    self, stages=want_stages, mix=self._fx_filter_mix, hpf_f=self._fx_hpf_f
                )
            )
        if self._fx_distortion_on:
            if audiofilters is None:
                raise ImportError("audiofilters is not in this CircuitPython build")
            # fmt: off
            dist = chain.add(audiofilters.Distortion(
                mode=audiofilters.DistortionMode.LOFI, mix=self._fx_drive_mix,
                soft_clip=True, pre_gain=0, post_gain=0, **self._fx_cfg()))
            # fmt: on
            set_drive(dist, self._fx_drive)
        if self._fx_echo_on:
            if audiodelays is None:
                raise ImportError("audiodelays is not in this CircuitPython build")
            # fmt: off
            delay = chain.add(audiodelays.Echo(
                mix=self._fx_delay_mix, delay_ms=self._fx_delay_ms,
                max_delay_ms=self.FX_MAX_DELAY_MS, decay=self._fx_delay_decay,
                freq_shift=False, **self._fx_cfg()))
            # fmt: on
        self._fx, self._fx_stage, self._fx_dist, self._fx_delay = chain, stage, dist, delay

    def _push_fx_live(self):
        """Push the current fx_* values into whatever's already built.

        A no-op for anything not built yet: called by every live fx_*
        setter AND by _recompile(), so a patch load reaches a chain that's
        already sounding exactly like every other param in this class,
        even mid-transition after a structural change has invalidated
        self._fx but left the still-playing objects in place.
        """
        if self._fx_stage is not None:
            self._fx_stage.mix = self._fx_filter_mix
        if self._fx_dist is not None:
            set_drive(self._fx_dist, self._fx_drive)
            self._fx_dist.mix = self._fx_drive_mix
        if self._fx_delay is not None:
            self._fx_delay.delay_ms = self._fx_delay_ms
            self._fx_delay.mix = self._fx_delay_mix
            self._fx_delay.decay = self._fx_delay_decay

    @property
    def fx(self):
        """The owned effects chain, built the first time anything needs
        it. Add/insert/remove more effects on it if you want to extend
        past filter+distortion+echo: it's an ordinary ``EffectsChain``.
        """
        self._build_fx()
        return self._fx

    @property
    def output(self):
        """What a mixer voice should play: the synth itself, or the tail
        of ``fx`` if any ``fx_*`` field asked for an effect.

        A mixer voice's ``play()`` captures this object's identity at
        call time. Changing any STRUCTURAL field (``fx_filter_stages``,
        ``fx_hpf_f``, ``fx_distortion_on``, ``fx_echo_on``: directly, via
        ``set_param()``, or via ``load_patch()``) invalidates the owned
        chain, so re-fetch ``output`` and hand it to the mixer voice
        again afterward. The LIVE fx knobs (mix, drive, delay time) need
        no such thing: they reach whatever's already playing.
        """
        return self.fx.output

    # --- accent ----------------------------------------------------------

    def _refresh_accent_depth(self):
        """Recompute the accent boost per unit of sweep.

        Resonance sets how deep the sweep goes: the least obvious thing in
        the box, since the Resonance pot is dual-gang and its second half
        is the INPUT to the accent sweep circuit rather than something
        accent modulates.

        Cached because ``filt_q`` and ``accent_cutoff`` move on a knob
        turn, not per step, and this runs in the note-on path: measured on
        rp2040, computing it inline cost 128 us on EVERY step.
        """
        n = (self._filt_q_blk.a - self.Q_MIN) / (self.Q_MAX - self.Q_MIN)
        res = 0.0 if n < 0.0 else (1.0 if n > 1.0 else n)
        self._acc_hz = self._accent_cutoff * (0.35 + 0.65 * res)
        # ...and how long the sweep takes to arrive. Anti-clockwise the
        # accent is a direct pulse; clockwise it goes through a lag, and
        # that upward ramp into the note is the acid "wow". A rate, so it
        # is cheap, and it lands here rather than in _refresh_accent()
        # because only resonance moves it.
        self._accent_lag.rate = 1.0 / (0.001 + res * self.ACCENT_LAG)

    def _refresh_accent(self):
        """Push the current accent state into the shared blocks.

        Called on every note-on and whenever a knob it depends on moves, so
        an accented note that is still sounding tracks the knob too. Every
        write here is O(1) and lands on a spare input, so nothing Synth
        reads back is disturbed: see the module comment.

        This is in the note-on path, so it is written to touch as little as
        it can get away with: see _refresh_accent_depth() for the cached
        half, and the guard on the fall time below.
        """
        # The SWEEP, not the accent flag: charge left over from earlier
        # accents still reaches the un-accented steps after them, which is
        # the decay half of the staircase.
        sweep = self._accent_sweep
        boost = self._acc_hz * sweep
        # Accent raising resonance is the disputed direction: forum accounts
        # say it does, Whittle's circuit reading says resonance drives the
        # sweep instead. Kept small as a musical extra, defaulting low.
        self._filt_q_blk.b = self._accent_q * sweep
        # the 303 scales env mod by the ALREADY accented cutoff, so an
        # accented step sweeps a wider range as well as a higher one
        envmod = min(1.0, self._envmod + 0.25 * sweep)
        # The shortened fall is per-STEP, not swept: an accented step's
        # envelope decay is pinned short whatever the Decay knob says. This
        # is why `decay` reads back from self._decay rather than from the
        # block, which is holding ACCENT_FALL right now.
        #
        # Guarded because it only changes when accent toggles, while the
        # setter behind it rebuilds both envelope rates: 218 us a step on
        # rp2040, the single most expensive thing that was in here.
        fall = self.ACCENT_FALL if self._accent_on else self._decay
        if fall != self._fall:
            self._fall = fall
            self._fenv.attack = fall
        self._accent_lag.scale = boost  # the ramp carries it in
        self._fenv.amount = -envmod * (self._filt_f_blk.a + boost)

    def _strike_accent(self, accented):
        """One STEP's worth of accent: charge the sweep, push it out, and
        restart the lag.

        The accent circuit has MEMORY: it is an RC sweep whose capacitor
        does not discharge between steps, so consecutive accented steps
        stack into a rising staircase of cutoff peaks and the steps after
        them fade back rather than snapping. An earlier version latched at
        a constant while accented and dropped to nothing the moment a step
        was not, which is neither half of that.

        Decayed per STEP rather than per second because this class has no
        clock; the hardware's time constant is roughly 200-400 ms, so a
        tempo, if one is ever available here, is the better thing to decay
        against.

        Separate from _refresh_accent(), which knob setters also call: a
        knob turn must not re-run the swell under a sounding note. Inlined
        rather than split further because this is the note-on path.
        """
        self._accent_on = accented
        sweep = self._accent_sweep * self._accent_sweep_decay
        if accented:
            sweep = min(self._accent_sweep_max, sweep + self._accent)
        self._accent_sweep = sweep
        self._refresh_accent()
        if accented:
            self._accent_lag.retrigger()

    # --- real-time path ---------------------------------------------------

    def note_on_step(self, midi_note, slide=False, accent=False, velocity=127):
        """Play one sequencer step, with the 303's two per-step flags.

        ``slide`` TIES this step to the one still sounding: the pitch
        glides but nothing is pressed or released, so both envelopes keep
        running and a legato run stays legato. ``accent`` boosts cutoff,
        resonance, envelope depth and level for this step and every step
        after it, until an un-accented one puts them back, which is how
        the original behaves, the accent living in shared state rather
        than in the voice.

        **A tie needs the gate held.** It happens only while a note is
        still in ``voices``, so a caller that releases the previous step
        before playing this one gets the old press-and-glide instead. A
        sequencer wanting ties must skip ``note_off()`` when the next step
        slides.

        One thing a tie cannot do: change loudness. ``attack_level`` was
        baked into the ``synthio.Envelope`` at press, so an accented slid
        step moves the filter but not the level.
        """
        self._strike_accent(accent)  # BEFORE the press: the envelope depth
        # has to be non-zero already or make() builds no envelope node at all
        if slide and self.voices:
            self._tie_to(midi_note)
            return
        super().note_on(midi_note, velocity, glide=self._slide_time if slide else 0.0)

    def _tie_to(self, midi_note):
        """Retune the sounding voice instead of pressing a new one.

        Mono, so there is exactly one voice and one of everything keyed on
        it. Nothing is pressed and nothing is released; the Notes, their
        filter envelope and their amp envelope all carry on, which is the
        whole point of a tie.

        Aim the glide BEFORE retuning, and let nothing come between them.
        _aim_glide() reads the in-flight glide to rebase on it, then
        retriggers the ramp to the new interval; until the Note itself
        moves to the new pitch that interval is counted twice. Both happen
        inside one render block, so it is never heard, but a yield in
        between would be.
        """
        old = next(iter(self.voices))
        notes = self.voices.pop(old)
        self._aim_glide(midi_note, self._slide_time)
        f = synthio.midi_to_hz(midi_note + self._transpose)
        for n in notes:
            n.frequency = f
        self.voices[midi_note] = notes
        if old in self._fenvs:
            self._fenvs[midi_note] = self._fenvs.pop(old)
        if old in self._penvs:
            self._penvs[midi_note] = self._penvs.pop(old)

    def note_on(self, midi_note, velocity=127, glide=None):
        """MIDI-style note-on. Accents at or above ``accent_velocity``.

        A note-on is a step as far as the accent sweep is concerned, so
        this charges and decays it the same way note_on_step() does. It
        cannot double-count: note_on_step()'s own press goes to
        ``Synth.note_on``, not here.
        """
        self._strike_accent(velocity >= self.accent_velocity)
        super().note_on(midi_note, velocity, glide=glide)

    def note_off(self, midi_note):
        """Freeze a released note's bend before Synth.note_off() releases
        it, same reasoning as Synth's own note_off() freeze, but keyed on
        slide_time rather than glide_time.

        note_on_step() always passes an explicit per-note glide= override
        (self._slide_time or 0.0), so Synth.note_on()'s
        ``secs = self._glide_time if glide is None else glide`` never
        consults self._glide_time for this class -- it stays 0.0, so
        Synth.note_off()'s ``if self.mono and self._glide_time:`` guard never
        fires here. Without this, a released tail keeps a LIVE reference to
        the shared bend graph and the next slide's _aim_glide() drags it
        along for the length of its release, the exact bug that guard
        exists to prevent, just reached through the one path it doesn't
        check. See tests/test_mono.py.
        """
        if self.mono and self._slide_time and midi_note in self.voices:
            for n in self.voices[midi_note]:
                b = n.bend
                n.bend = getattr(b, "value", b)
        super().note_off(midi_note)

    def _make_notes(self, midi_note, velocity):
        f = synthio.midi_to_hz(midi_note + self._transpose)
        # No amplitude: the 303 is a fixed-level instrument and velocity
        # picks the accent instead, which arrives as attack_level.
        # fmt: off
        return (synthio.Note(f, waveform=get_wave(self._wave_name),
                             envelope=self._accent_env() if self._accent_on else self._env,
                             filter=self._make_filter(),
                             bend=self._bend_cur),)
        # fmt: on

    # --- amp envelope -----------------------------------------------------
    # Two cached Envelopes rather than one: synthio.Envelope is immutable, so
    # the accented level would otherwise mean a new one at every accent.

    def _env_for(self, level):
        a, d, s, r = self._amp_env
        # fmt: off
        return synthio.Envelope(attack_time=a, decay_time=d, sustain_level=s,
                                release_time=r, attack_level=level)
        # fmt: on

    def _make_env(self):
        return self._env_for(self._amp_level)

    def _accent_env(self):
        """The accented Envelope, rebuilt only when its level moved.

        The sweep drives loudness as well as cutoff, so the accented level
        changes as the staircase does; synthio.Envelope is immutable, so
        without the cache that is an allocation a step. One float compare
        instead.

        Called from _make_notes(), i.e. only where the result is actually
        read: an accented press. Doing it inside _refresh_accent() charged
        every un-accented step and every knob turn for it too.
        """
        lvl = min(1.0, self._amp_level + 0.5 * self._accent_sweep)
        if lvl != self._env_accent_level:
            self._env_accent = self._env_for(lvl)
            self._env_accent_level = lvl
        return self._env_accent

    def _rebuild_env(self):
        super()._rebuild_env()  # self._env, plus the push to sounding notes
        self._env_accent_level = None  # amp_env moved: the cache is stale

    # --- live parameters --------------------------------------------------

    @property
    def filt_f(self):
        return self._filt_f_blk.a

    @filt_f.setter
    def filt_f(self, v):
        # Overridden only to re-derive the envelope depth: envmod is a
        # fraction of the cutoff, so moving the cutoff moves the sweep.
        self._filt_f_blk.a = v
        self._refresh_accent()

    @property
    def filt_q(self):
        return self._filt_q_blk.a

    @filt_q.setter
    def filt_q(self, v):
        # Overridden only to refresh the cached accent depth: resonance is
        # what drives the accent sweep circuit, so moving it moves how deep
        # an accent goes. Caching that is what keeps it out of the note-on
        # path; see _refresh_accent_depth().
        self._filt_q_blk.a = v
        self._refresh_accent_depth()
        self._refresh_accent()

    @property
    def filt_type(self):
        return self._filt_type

    @filt_type.setter
    def filt_type(self, v):
        # Overridden to also invalidate the owned fx chain on a real mode
        # change. _build_filter() re-swaps the VOICE Biquad live, but
        # tracking_filter() copies `mode` into each owned stage as a plain
        # value, so left alone a filt_type change would leave the voice on
        # the new mode and the stages stuck on the old: wrong sound, no
        # exception.
        old_mode = self._filt_mode
        self._filt_type = v
        self._filt_mode = FILTER_MODES.get(v)
        if self._filt_mode != old_mode:
            self._fx = None

    @property
    def envmod(self):
        """Filter sweep depth, 0..1, as a fraction of ``filt_f``.

        0 = no sweep, 1.0 = sweep all the way down to the FILT_F_MIN clamp.
        """
        return self._envmod

    @envmod.setter
    def envmod(self, v):
        self._envmod = v
        self._refresh_accent()

    @property
    def decay(self):
        """Seconds for the filter sweep to fall. The 303's Decay knob.

        This drives the FILTER envelope only: ``amp_env`` (or
        ``decay_time``) is the amp's, and wants to be LONGER than this.
        An earlier version tied the two together, which sounds like one
        knob but makes envmod nearly inaudible: if the note fades out at
        the same rate the cutoff falls, the sweep is masked by the
        amplitude and the whole thing just reads as a pluck. Keep the amp
        alive underneath the sweep and the filter movement is obvious.

        It also has to be SHORTER than the gate, or the sweep is cut off
        partway and envmod does much less than its number suggests: see
        the filter-envelope notes in the project docs.

        An ACCENTED step ignores this and falls in ``ACCENT_FALL`` seconds
        instead, so this reads back from its own mirror rather than from
        the block, which is holding the accented value during such a note.
        """
        return self._decay

    @decay.setter
    def decay(self, v):
        self._decay = v
        self._refresh_accent()  # writes the block, accented value and all

    @property
    def accent(self):
        return self._accent

    @accent.setter
    def accent(self, v):
        self._accent = v
        self._refresh_accent()
        self._rebuild_env()  # the accented level changed with it

    @property
    def accent_cutoff(self):
        """Hz added to the cutoff by a full-strength accent."""
        return self._accent_cutoff

    @accent_cutoff.setter
    def accent_cutoff(self, v):
        self._accent_cutoff = v
        self._refresh_accent_depth()
        self._refresh_accent()

    @property
    def accent_q(self):
        """Resonance added by a full-strength accent.

        A deliberate deviation, defaulted low: circuit-level accounts have
        resonance DRIVING the accent sweep rather than accent raising
        resonance. Kept because it sounds good, not because it is faithful.
        """
        return self._accent_q

    @accent_q.setter
    def accent_q(self, v):
        self._accent_q = v
        self._refresh_accent()

    @property
    def accent_sweep_decay(self):
        """How much of the accent sweep survives one step, 0..1.

        The accent circuit's capacitor does not discharge between steps,
        which is what makes consecutive accents a rising staircase and the
        steps after them fade back instead of snapping. 0 would restore the
        old latch-and-drop behaviour; 1 would never let go.
        """
        return self._accent_sweep_decay

    @accent_sweep_decay.setter
    def accent_sweep_decay(self, v):
        self._accent_sweep_decay = v

    @property
    def accent_sweep_max(self):
        """Where the accent sweep saturates, in units of ``accent``, so a
        long run of accents stops climbing after a few steps."""
        return self._accent_sweep_max

    @accent_sweep_max.setter
    def accent_sweep_max(self, v):
        self._accent_sweep_max = v

    @property
    def amp_level(self):
        """Un-accented note level, 0..1 (synthio.Envelope.attack_level)."""
        return self._amp_level

    @amp_level.setter
    def amp_level(self, v):
        self._amp_level = v
        self._rebuild_env()

    @property
    def slide_time(self):
        """Seconds a slide step takes. Applied per step by note_on_step(),
        so it never writes glide_time."""
        return self._slide_time

    @slide_time.setter
    def slide_time(self, v):
        self._slide_time = v

    @property
    def transpose(self):
        return self._transpose

    @transpose.setter
    def transpose(self, v):
        self._transpose = v  # applies at the next note-on

    @property
    def wave(self):
        return self._wave_name

    @wave.setter
    def wave(self, v):
        self._wave_name = v
        get_wave(v)  # O(1); warms the cache for the next note-on

    # --- owned effects chain: the four STRUCTURAL switches ---------------
    # Changing any of these invalidates self._fx (rebuilt lazily, next
    # .fx/.output access) but leaves whatever is currently built alone,
    # since that is still what the mixer is playing. output's docstring
    # carries the resulting contract.

    @property
    def fx_filter_stages(self):
        """Extra 12 dB/octave Biquad stages cascaded after the voice's own
        filter, via ``tracking_filter()``. 0 = none (the default, costs
        nothing and never touches ``audiofilters``). Has no effect while
        ``filt_type`` is ``None``: there is no cutoff to track."""
        return self._fx_filter_stages

    @fx_filter_stages.setter
    def fx_filter_stages(self, v):
        self._fx_filter_stages = v
        self._fx = None

    @property
    def fx_hpf_f(self):
        """Corner of a fixed high-pass placed after the voice filter, in
        Hz; 0 = none (the default). ~80 is the stock TB-303, whose thin
        bass is entirely the small coupling capacitors between filter and
        VCA; lower or 0 is the Devil Fish "fat" variant.

        A plain number, never a block: it must NOT follow the cutoff
        sweep. It rides in the same ``audiofilters.Filter`` as
        ``fx_filter_stages``, so it costs no extra buffer, and it works
        with ``filt_type`` ``None``, having nothing to track.
        """
        return self._fx_hpf_f

    @fx_hpf_f.setter
    def fx_hpf_f(self, v):
        self._fx_hpf_f = v or 0.0  # one spelling of off, so loads compare equal
        self._fx = None

    @property
    def fx_distortion_on(self):
        """Whether a distortion stage exists at all. Separate from
        ``fx_drive_mix`` on purpose: even at mix 0 a ``Distortion`` effect
        costs a buffer and real CPU every block, so whether one *exists*
        has to be deliberate."""
        return self._fx_distortion_on

    @fx_distortion_on.setter
    def fx_distortion_on(self, v):
        self._fx_distortion_on = v
        self._fx = None

    @property
    def fx_echo_on(self):
        """Whether an echo stage exists at all; see ``fx_distortion_on``,
        same reasoning."""
        return self._fx_echo_on

    @fx_echo_on.setter
    def fx_echo_on(self, v):
        self._fx_echo_on = v
        self._fx = None

    # --- owned effects chain: the six LIVE knobs --------------------------
    # Each reaches whatever is already built via _push_fx_live(), and is a
    # no-op until the matching structural switch above turns the effect on.

    @property
    def fx_filter_mix(self):
        """Dry/wet for the extra filter stages, 1.0 = fully filtered."""
        return self._fx_filter_mix

    @fx_filter_mix.setter
    def fx_filter_mix(self, v):
        self._fx_filter_mix = v
        self._push_fx_live()

    @property
    def fx_drive(self):
        """Distortion amount, 0..1, via ``set_drive()`` (LOFI mode's own
        ``drive`` parameter does not behave as its name suggests)."""
        return self._fx_drive

    @fx_drive.setter
    def fx_drive(self, v):
        self._fx_drive = v
        self._push_fx_live()

    @property
    def fx_drive_mix(self):
        """Dry/wet for the distortion stage."""
        return self._fx_drive_mix

    @fx_drive_mix.setter
    def fx_drive_mix(self, v):
        self._fx_drive_mix = v
        self._push_fx_live()

    @property
    def fx_delay_ms(self):
        """Echo delay time in milliseconds."""
        return self._fx_delay_ms

    @fx_delay_ms.setter
    def fx_delay_ms(self, v):
        self._fx_delay_ms = v
        self._push_fx_live()

    @property
    def fx_delay_mix(self):
        """Dry/wet for the echo stage."""
        return self._fx_delay_mix

    @fx_delay_mix.setter
    def fx_delay_mix(self, v):
        self._fx_delay_mix = v
        self._push_fx_live()

    @property
    def fx_delay_decay(self):
        """Echo feedback, 0..1; how much each repeat carries into the
        next. Unrelated to ``decay``, the filter-envelope fall time."""
        return self._fx_delay_decay

    @fx_delay_decay.setter
    def fx_delay_decay(self, v):
        self._fx_delay_decay = v
        self._push_fx_live()
