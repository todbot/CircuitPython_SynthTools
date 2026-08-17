# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# bassline_synth.py - the squelchy acid bassline voice, after the Roland
# TB-303: monophonic, one oscillator, per-step slide and accent.
#
# Built straight on Synth with `mono = True`: the slide is Synth's own
# glide given a per-step time, and the one-voice stealing comes with the
# switch. There is no monosynth base class -- there turned out to be
# nothing left for one to hold.
#
# NOTE a slide here glides the pitch but still RETRIGGERS the envelopes.
# A real 303 holds the gate high across a slide so the two steps tie into
# one note; doing that means retuning the sounding voice in place instead
# of re-pressing it, which is a chunk of machinery this does not have yet.
# The synth this was ported from behaves the same way (its note_on_step
# carries a "FIXME also do appropriate other actions for slide").
#
# --- the two things that make it a 303 --------------------------------
#
# 1. A DECAY-ONLY filter envelope. The cutoff jumps to its peak at
#    note-on and falls back while the key is still down. Synth's AHR
#    envelope holds at peak instead of falling, which looks like the wrong
#    shape entirely -- but AHR with a NEGATIVE amount is exactly this:
#
#        filt_f      the peak the sweep starts from
#        fenv_amount -envmod * filt_f, so the sweep runs DOWNWARD
#        fenv_attack the fall time (a decay, despite the name)
#
#    The shape buffer is 1-(1-t)^curve, fast-then-easing, which run
#    downward is the quick drop and long tail the 303 is known for. No new
#    envelope class, and every one of those is still a shared block, so
#    the whole thing stays O(1) live. FILT_F_MIN earns its keep here:
#    envmod = 1.0 aims the sweep at 0 Hz and the clamp catches it.
#
#    envmod being a FRACTION of filt_f rather than a number of Hz is the
#    303's own arrangement, and it is why the envelope tracks the cutoff
#    knob: turning cutoff up makes the sweep proportionally bigger.
#
# 2. ACCENT, which must not contaminate the patch. On an accented step a
#    303 raises the cutoff, the resonance, the envelope depth and the
#    level -- and those are all shared blocks here, so the obvious
#    implementation writes filt_f and filt_q and then save_patch() stores
#    the accented values as if they were the knob positions.
#
#    So accent writes the SPARE INPUTS of blocks Synth already built,
#    never the ones Synth reads back:
#
#        cutoff     _filt_sum.c    sum3()'s unused third input
#        resonance  _filt_q_blk.b  scalar_block()'s unused second input
#
#    Both are inside the graph the voice already reads, so an accent is
#    still one write and still reaches a sounding note; and filt_f and
#    filt_q read back clean, because Synth reads .a of each. Only
#    fenv_amount has no spare slot -- it is derived from envmod anyway, so
#    _decompile() re-derives the un-accented value on save.

import synthio

from .audio_fx import EffectsChain, set_drive, tracking_filter
from .blocks import clamp, product, sum3
from .synth import FILTER_MODES, Synth
from .waves import get_wave

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
    cutoff      ``filt_f`` -- the peak the filter sweep starts from
    resonance   ``filt_q``
    env mod     ``envmod`` -- sweep depth as a FRACTION of filt_f
    decay       ``decay`` -- seconds, both the filter fall and the amp
    accent      ``accent`` -- how much an accented step is boosted
    ==========  ====================================================

    Play it a step at a time with note_on_step(), which takes the 303's
    per-step slide and accent flags; note_on() is the MIDI-style front end
    and accents anything at or above ``accent_velocity``.

    A slide glides the pitch into the step but still retriggers the
    envelopes; a real 303 ties the two steps into one note instead. See
    the module comment. Waveform is one shared buffer with no random
    phase, unlike SubtractiveSynth: a monosynth has no second oscillator
    to beat against, so a note-on allocates no waveform at all.

    ``envmod`` is the source of truth for the filter envelope's depth.
    ``fenv_amount`` is derived from it and from ``filt_f``, so writing
    ``fenv_amount`` directly is overwritten by the next change to either.
    """

    # fmt: off
    _PARAMS = Synth._PARAMS + ("wave", "envmod", "decay", "amp_level",
                               "accent", "accent_cutoff", "accent_q",
                               "slide_time", "transpose",
                               # the three STRUCTURAL fx_* fields
                               # (fx_filter_stages, fx_distortion_on,
                               # fx_echo_on) are deliberately absent: a
                               # set_param() from a MIDI CC would silently
                               # mute the fx chain, since nothing here can
                               # reach into the mixer and re-play() the
                               # new tail. See the "effects chain" section.
                               "fx_filter_mix", "fx_drive", "fx_drive_mix",
                               "fx_delay_ms", "fx_delay_mix", "fx_delay_decay")
    # fmt: on

    #: Inherently monophonic -- accent and glide are both shared state
    #: that assumes a single voice.
    mono = True

    #: note_on() accents at or above this velocity. The 303's sequencer had
    #: a per-step accent switch rather than a velocity; this is the MIDI
    #: stand-in for it, and note_on_step() bypasses it entirely.
    accent_velocity = 100

    # class attrs: Synth.__init__ builds its graph, and calls _make_env(),
    # before this subclass has run any setup of its own
    _wave_name = "SAW"
    _transpose = 0
    _envmod = 0.5
    _amp_level = 0.8
    _accent = 0.5
    _accent_cutoff = 4000.0
    _accent_q = 0.6
    _slide_time = 0.10
    _accent_on = False
    _env_accent = None
    _filter = None  # the shared Biquad; see _build_filter()
    _cutoff = None  # its stable frequency node

    # --- the owned effects chain: class attrs; see _build_fx() ----------
    FX_BUFFER_SIZE = 1024
    FX_MAX_DELAY_MS = 1000.0  # buffer sizing only, not a knob -- see fx_delay_ms
    _fx_filter_stages = 0
    _fx_filter_mix = 1.0
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
        super().__init__(synthesizer, patch)
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
        self._accent_q = getattr(p, "accent_q", 0.6)
        self._slide_time = getattr(p, "slide_time", 0.10)
        get_wave(self._wave_name)  # warm the cache; note-on only reads it
        self._accent_on = False
        self._refresh_accent()  # also derives fenv_amount from envmod
        self._rebuild_env()

        # --- the owned effects chain -------------------------------------
        # Compare the three STRUCTURAL fields against what's already live
        # BEFORE overwriting them: only a real shape change should drop
        # self._fx. A patch load that leaves the fx shape alone must reach
        # the live effects the same as every other param here, not freeze
        # them -- see the "effects chain" section for why a naive
        # unconditional invalidate is a silent wrong-sound bug.
        new_stages = getattr(p, "fx_filter_stages", 0)
        new_distortion_on = getattr(p, "fx_distortion_on", False)
        new_echo_on = getattr(p, "fx_echo_on", False)
        structural_changed = (
            new_stages != self._fx_filter_stages
            or new_distortion_on != self._fx_distortion_on
            or new_echo_on != self._fx_echo_on
        )
        self._fx_filter_stages = new_stages
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
        p.slide_time = self._slide_time
        # super() saved whatever the last step left in the shared block,
        # which on an accented step is the boosted depth. envmod is the
        # real knob, so re-derive the clean value rather than store that.
        p.fenv_amount = -self._envmod * self._filt_f_blk.a
        p.fx_filter_stages = self._fx_filter_stages
        p.fx_filter_mix = self._fx_filter_mix
        p.fx_distortion_on = self._fx_distortion_on
        p.fx_drive = self._fx_drive
        p.fx_drive_mix = self._fx_drive_mix
        p.fx_echo_on = self._fx_echo_on
        p.fx_delay_ms = self._fx_delay_ms
        p.fx_delay_mix = self._fx_delay_mix
        p.fx_delay_decay = self._fx_delay_decay

    # --- the shared filter ------------------------------------------------
    # Mono, so ONE Biquad and one cutoff node serve every note: built once
    # and re-aimed, not allocated per note. Synth rebuilds both each
    # note-on because in poly it has to. Here it does not, and holding
    # still is what lets audio_fx point extra stages at this cutoff once
    # and have them track forever -- the same trick as the synth this was
    # ported from, which shares one filt_env LFO between its voice filter
    # and its effect filters.

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

        Its ``frequency`` is a stable node carrying the whole cutoff bus --
        filt_f, the filter LFO, the envelope sweep, the accent -- so a
        downstream stage can point at it once and follow all of it. That is
        all ``audio_fx.EffectsChain`` needs.
        """
        self._build_filter()
        return self._filter

    def _voice_cutoff(self, velocity):
        """One voice, so one cutoff node: re-aim it instead of rebuilding."""
        if self._filt_mode is None:
            return None
        self._build_filter()
        inner = self._cutoff.a  # the SUM inside the clamp
        inner.b = self._fenv_cur if self._fenv_cur is not None else 0.0
        inner.c = product(self._filt_vel_blk, velocity / 127.0) if self._filt_vel_blk.a else 0.0
        return self._cutoff

    def _make_filter(self):
        return self.filter

    # --- the owned effects chain (optional) -------------------------------
    # A specialized EffectsChain, not the general-purpose one: fixed order
    # (filter -> distortion -> echo, the acid-bass signal flow), built
    # from the SAME tracking_filter()/set_drive() free functions the demo
    # used to call by hand. The three fx_*_on/fx_filter_stages fields are
    # STRUCTURAL -- they decide what exists -- everything else is a LIVE
    # write into whatever's already built. See fx_drive and friends below.

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
        self._fx non-None with an fx_echo_on that never got its Echo --
        later code would treat the chain as already built and never retry.
        """
        if self._fx is not None:
            return
        chain = EffectsChain(self)
        stage = dist = delay = None
        # No filter to track with filt_type=None -- an ordinary, silent
        # no-op, the same as _voice_cutoff() returning None. tracking_filter
        # itself raises ValueError for external callers who don't already
        # know why; internally we do, so we just skip the stage instead of
        # letting that surface from an `output` property read.
        if self._fx_filter_stages > 0 and self._filt_mode is not None:
            stage = chain.add(
                tracking_filter(self, stages=self._fx_filter_stages, mix=self._fx_filter_mix)
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

        A no-op for anything not built yet -- called by every live fx_*
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
        past filter+distortion+echo -- it's an ordinary ``EffectsChain``.
        """
        self._build_fx()
        return self._fx

    @property
    def output(self):
        """What a mixer voice should play: the synth itself, or the tail
        of ``fx`` if any ``fx_*`` field asked for an effect.

        A mixer voice's ``play()`` captures this object's identity at
        call time. Changing any STRUCTURAL field (``fx_filter_stages``,
        ``fx_distortion_on``, ``fx_echo_on`` -- directly, via
        ``set_param()``, or via ``load_patch()``) invalidates the owned
        chain, so re-fetch ``output`` and hand it to the mixer voice
        again afterward. The LIVE fx knobs (mix, drive, delay time) need
        no such thing -- they reach whatever's already playing.
        """
        return self.fx.output

    # --- accent ----------------------------------------------------------

    def _refresh_accent(self):
        """Push the current accent state into the shared blocks.

        Called on every note-on and whenever a knob it depends on moves, so
        an accented note that is still sounding tracks the knob too. Every
        write here is O(1) and lands on a spare input, so nothing Synth
        reads back is disturbed -- see the module comment.
        """
        if self._accent_on:
            boost = self._accent_cutoff * self._accent
            self._filt_q_blk.b = self._accent_q * self._accent
            # the 303 scales env mod by the ALREADY accented cutoff, so an
            # accented step sweeps a wider range as well as a higher one
            envmod = min(1.0, self._envmod + 0.25 * self._accent)
        else:
            boost = 0.0
            self._filt_q_blk.b = 0.0
            envmod = self._envmod
        self._filt_sum.c = boost
        self._fenv.amount = -envmod * (self._filt_f_blk.a + boost)

    # --- real-time path ---------------------------------------------------

    def note_on_step(self, midi_note, slide=False, accent=False, velocity=127):
        """Play one sequencer step, with the 303's two per-step flags.

        ``slide`` glides from the previous step and ties to it, so the
        envelopes keep running. ``accent`` boosts cutoff, resonance,
        envelope depth and level for this step and every step after it,
        until an un-accented one puts them back -- which is how the
        original behaves, the accent living in shared state rather than in
        the voice.
        """
        self._accent_on = accent
        self._refresh_accent()  # BEFORE the press: the envelope depth has
        # to be non-zero already or make() builds no envelope node at all
        super().note_on(midi_note, velocity, glide=self._slide_time if slide else 0.0)

    def note_on(self, midi_note, velocity=127, glide=None):
        """MIDI-style note-on. Accents at or above ``accent_velocity``."""
        self._accent_on = velocity >= self.accent_velocity
        self._refresh_accent()
        super().note_on(midi_note, velocity, glide=glide)

    def _make_notes(self, midi_note, velocity):
        f = synthio.midi_to_hz(midi_note + self._transpose)
        # No amplitude: the 303 is a fixed-level instrument and velocity
        # picks the accent instead, which arrives as attack_level.
        # fmt: off
        return (synthio.Note(f, waveform=get_wave(self._wave_name),
                             envelope=self._env_accent if self._accent_on else self._env,
                             filter=self._make_filter(),
                             bend=self._bend_cur),)
        # fmt: on

    # --- amp envelope -----------------------------------------------------
    # Two cached Envelopes rather than one: synthio.Envelope is immutable,
    # so the accented level would otherwise mean building a new one at
    # every accented note-on.

    def _env_for(self, level):
        a, d, s, r = self._amp_env
        # fmt: off
        return synthio.Envelope(attack_time=a, decay_time=d, sustain_level=s,
                                release_time=r, attack_level=level)
        # fmt: on

    def _make_env(self):
        return self._env_for(self._amp_level)

    def _rebuild_env(self):
        super()._rebuild_env()  # self._env, plus the push to sounding notes
        self._env_accent = self._env_for(min(1.0, self._amp_level + 0.5 * self._accent))

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
    def filt_type(self):
        return self._filt_type

    @filt_type.setter
    def filt_type(self, v):
        # Overridden to also invalidate the owned fx chain on a real mode
        # change. _build_filter() already re-swaps the VOICE Biquad live
        # (its frequency/Q are shared blocks, but `mode` isn't), and
        # tracking_filter() copies that same mode as a plain value into
        # each owned stage -- so left alone, a filt_type change would
        # leave the voice on the new mode and the owned stages stuck on
        # the old one: wrong sound, no exception.
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

        This drives the FILTER envelope only -- ``amp_env`` (or
        ``decay_time``) is the amp's, and wants to be LONGER than this.
        An earlier version tied the two together, which sounds like one
        knob but makes envmod nearly inaudible: if the note fades out at
        the same rate the cutoff falls, the sweep is masked by the
        amplitude and the whole thing just reads as a pluck. Keep the amp
        alive underneath the sweep and the filter movement is obvious.

        It also has to be SHORTER than the gate, or the sweep is cut off
        partway and envmod does much less than its number suggests -- see
        the filter-envelope notes in the project docs.
        """
        return self._fenv.attack

    @decay.setter
    def decay(self, v):
        self._fenv.attack = v  # a rate write, cheap on a knob

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
        self._refresh_accent()

    @property
    def accent_q(self):
        """Resonance added by a full-strength accent."""
        return self._accent_q

    @accent_q.setter
    def accent_q(self, v):
        self._accent_q = v
        self._refresh_accent()

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

    # --- owned effects chain: the three STRUCTURAL switches --------------
    # Changing any of these invalidates self._fx (rebuilt lazily, next
    # .fx/.output access) but leaves whatever is currently built alone --
    # it's still what the mixer is playing. See "the owned effects chain"
    # above for why, and output's docstring for the resulting contract.

    @property
    def fx_filter_stages(self):
        """Extra 12 dB/octave Biquad stages cascaded after the voice's own
        filter, via ``tracking_filter()``. 0 = none (the default -- costs
        nothing and never touches ``audiofilters``). Has no effect while
        ``filt_type`` is ``None``: there is no cutoff to track."""
        return self._fx_filter_stages

    @fx_filter_stages.setter
    def fx_filter_stages(self, v):
        self._fx_filter_stages = v
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
        """Whether an echo stage exists at all -- see ``fx_distortion_on``,
        same reasoning."""
        return self._fx_echo_on

    @fx_echo_on.setter
    def fx_echo_on(self, v):
        self._fx_echo_on = v
        self._fx = None

    # --- owned effects chain: the six LIVE knobs --------------------------
    # Each reaches whatever's already built via _push_fx_live(); a no-op
    # until the matching structural switch above turns the effect on.

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
        """Echo feedback, 0..1 -- how much each repeat carries into the
        next. Unrelated to ``decay``, the filter-envelope fall time."""
        return self._fx_delay_decay

    @fx_delay_decay.setter
    def fx_delay_decay(self, v):
        self._fx_delay_decay = v
        self._push_fx_live()
