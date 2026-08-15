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

from .synth import Synth
from .waves import get_wave


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
                               "slide_time", "transpose")
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
