# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synth.py -- Synth base class.
#
# Owns: voice bookkeeping, patch load/save, live parameter updates.
# Subclasses override _recompile() / _decompile() and _make_notes(), and
# extend _PARAMS.
#
# Things to note:
#
# 1. THE PATCH IS NOT LIVE STATE. _recompile() reads it once; a knob turn
#    never writes back. Only save_patch() does, so reloading is a revert.
#
# 2. PARAMETERS ARE BLOCKS, NOT NUMBERS. Every voice nests the same shared
#    synthio.Math, so one write reaches all of them inside the C renderer:
#    O(1) in polyphony, and it reaches notes that are already playing.
#
# Live-parameter cost, fastest to slowest:
#   1. shared block write  - one assignment. O(1). filt_f, filt_q,
#      fenv_amount, filt_vel, fenv_vel, the LFO rates and depths.
#   2. in-place buffer     - rewrite the shared envelope shape. O(1), but
#      it allocates temporaries: a switch, not a knob. fenv_curve.
#   3. cached-object swap  - rebuild once, next note-on picks it up. O(1).
#      amp_env, filt_type, wave.
#   4. per-voice loop      - only for genuinely per-note values (detune).
#      O(polyphony), so avoid in anything a knob drives.
#
# Every param is a property, so `synth.filt_f = 1000` is the fast path and
# set_param() is just a string front-end for MIDI CC / UI code.

import synthio

from .ahr_envelope import AHREnvelope
from .blocks import clamp, constrained_lerp, lerp, product, scalar_block, sum3
from .waves import ramp_wave

FILTER_MODES = {
    "LPF": synthio.FilterMode.LOW_PASS,
    "HPF": synthio.FilterMode.HIGH_PASS,
    "BPF": synthio.FilterMode.BAND_PASS,
    "NOTCH": synthio.FilterMode.NOTCH,
}


class Synth:
    """Base synth engine wrapping one synthio.Synthesizer.

    Owns voice bookkeeping (note_on()/note_off()), patch load/save, and
    live parameter updates. A style subclass overrides _make_notes() (what
    a key sounds like) and typically _recompile()/_decompile() (how the
    subclass's own Patch fields compile to/from live state), extending
    _PARAMS with its own settable names. SubtractiveSynth and
    WavetableSynth are the two worked examples.

    Every parameter is a plain property (``synth.filt_f = 2000``), each
    backed by a shared synthio block so one write reaches every sounding
    voice in O(1) regardless of polyphony: see the module docstring
    above for the full cost model. set_param(name, val) is a string
    front-end onto the same properties, for MIDI CC / UI code.

    A Patch is inert JSON-able data, compiled into live blocks once by
    load_patch() -> _recompile(); nothing after that writes back to it
    until save_patch() explicitly snapshots live state via _decompile().
    """

    # names settable via set_param(); also what a UI can enumerate
    # fmt: off
    _PARAMS = ("filt_f", "filt_q", "filt_type", "amp_env",
               "attack_time", "decay_time", "sustain_level", "release_time",
               "vib_depth", "vib_rate", "vib_delay",
               "penv_amount", "penv_time", "penv_out_amount", "penv_out_time",
               "filt_lfo_rate", "filt_lfo_amount",
               "fenv_amount", "fenv_attack", "fenv_release", "fenv_curve",
               "filt_vel", "fenv_vel", "filt_track", "glide_time")
    # fmt: on

    #: One voice at a time: a note-on steals whatever is sounding, whichever
    #: note it was, and ``glide_time`` slides into it from the previous note.
    #: Flip it on any style to get a monosynth::
    #:
    #:     lead = SubtractiveSynth(synthesizer, patch)
    #:     lead.mono = True
    #:     lead.glide_time = 0.08
    #:
    #: Glide is defined as meaningless in poly (one shared bend would drag
    #: every sounding voice) so it is only applied while this is set.
    #:
    #: 'mono' is a synth STYLE's default. ``Patch.mono`` overrides it per patch
    #: (``None`` there means "leave the style's default alone"), and
    #: ``save_patch()`` writes back whatever is live, so a mono lead
    #: survives a save/load round trip along with its ``glide_time``.
    #: Deliberately NOT in ``_PARAMS``: it is structural, like
    #: BasslineSynth's ``fx_*_on`` switches, and a MIDI CC flipping a synth
    #: between mono and poly mid-phrase is not something to expose by
    #: accident.
    mono = False

    # A downward fenv_amount, a negative filt_vel or a big filt_lfo_amount
    # can each drive the cutoff bus below zero, so it is clamped in one MID
    # block. Defensive rather than required: a negative Biquad.frequency
    # does NOT raise, but what such a filter *sounds* like is undefined.
    FILT_F_MIN = 20.0
    FILT_F_MAX = 20000.0

    #: MIDI note the keyboard tracking pivots around: at this pitch
    #: filt_track changes nothing, whatever its value. Middle C.
    FILT_TRACK_REF = 60

    def __init__(self, synthesizer, patch=None):
        self.synthio = synthesizer
        self.voices = {}  # midi_note -> tuple of synthio.Note
        self.patch = None
        # Every shared block below is created ONCE and never replaced:
        # sounding voices hold references to them, so identity must survive
        # patch reloads. _recompile() writes into them.
        self._filt_f_blk = scalar_block(2000.0)
        self._filt_q_blk = scalar_block(1.0)
        self._filt_vel_blk = scalar_block(0.0)
        self._fenv_vel_blk = scalar_block(0.0)
        self._filt_track_blk = scalar_block(0.0)
        # Ratios against this cancel the tuning reference entirely, so the
        # arithmetic below is exact for any 12-TET midi_to_hz.
        self._track_ref_hz = synthio.midi_to_hz(self.FILT_TRACK_REF)
        # --- the bend graph ------------------------------------------
        #
        #   SHARED:  bend = SUM(vib_lfo, bend_blk)
        #                     vib_lfo.scale = PRODUCT(vib_depth, vib_fade)
        #   VOICE:   note.bend = SUM(bend, penv)   only with a pitch envelope
        #
        # The vibrato fade-in lives INSIDE the LFO's scale rather than on
        # the bend path, because LFO.scale is a BlockInput. That keeps the
        # whole of vib_delay in the shared half: nothing per voice, and
        # vib_depth stays one write into its own block.
        self._vib_depth_blk = scalar_block(0.0)
        # A one-shot 0 -> 1 ramp at rate 1/vib_delay, so vib_delay = 0 needs
        # no special case: the ramp just finishes in a millisecond and the
        # graph stays static, which is what the identity rule wants.
        self._vib_fade = synthio.LFO(waveform=ramp_wave(), rate=1000.0, once=True)
        self._vib_lfo = synthio.LFO(rate=5.0, scale=product(self._vib_depth_blk, self._vib_fade))
        self._bend_blk = scalar_block(0.0)
        # --- glide, the third input of the bend SUM ------------------
        # Portamento needs a per-voice pitch offset ONLY when there are
        # several voices; in mono there is one, so it is shared like
        # everything else and occupies the spare third input of sum3().
        #
        # It is a POSITION lerp: the bend runs from the previous note's
        # pitch to zero while the Note itself is created at the new pitch.
        # Aimed the other way, successive glides would compound.
        #
        # In poly nothing writes _glide.a, so this sits at 0.0 and is inert.
        self._glide_pos = synthio.LFO(waveform=ramp_wave(), rate=1000.0, once=True)
        self._glide = constrained_lerp(0.0, 0.0, self._glide_pos)
        self._glide_time = 0.0
        self._last_midi = None  # where the next glide starts from
        self._bend = sum3(self._vib_lfo, self._bend_blk, self._glide)
        # --- the filter cutoff modulation bus ------------------------
        # Four sources sum onto one destination:
        #
        #   SHARED:  filt_base = MID(SUM(filt_f, filt_lfo), MIN, MAX)
        #   VOICE:   cutoff    = SUM(filt_base, fenv, vel_hz)
        #                          vel_hz = PRODUCT(filt_vel, vel/127)
        #                          fenv   = AHREnvelope.make(gain)
        #                            gain = LERP(1, vel/127, fenv_vel)
        #
        # SUM takes three inputs, so base+LFO, envelope and velocity all land
        # in ONE per-voice node. Every knob in there is a shared block nested
        # inside it, so each stays a single write however many voices are
        # sounding, including voices already in release.
        #
        # All three modulations are ADDITIVE and one-sided: filt_f is the
        # floor and they open upward from it. See filt_lfo_amount below for
        # how the LFO is shifted to make that true.
        self._filt_lfo = synthio.LFO(rate=0.5, scale=0.0, offset=0.0)
        self._filt_sum = sum3(self._filt_f_blk, self._filt_lfo)
        self._filt_base = clamp(self._filt_sum, self.FILT_F_MIN, self.FILT_F_MAX)
        # Anything not reachable from a sounding Note has to be rooted here
        # or synthio never updates it, and that applies to Math blocks, not
        # just LFOs. Unattached LFOs do not advance, so vibrato and the
        # filter sweep would jump phase at every note-on.
        #
        # `_filt_base` and `_bend` are the non-obvious ones: reachable only
        # through a voice, so they freeze with nothing sounding, and on a
        # fresh Synth have never been evaluated at all. Measured on hardware,
        # the first note-on after construction read its cutoff as 0.0 Hz (a
        # click), and notes after a silence read a cutoff frozen wherever the
        # LFO was when the last voice died.
        synthesizer.blocks.append(self._vib_lfo)
        synthesizer.blocks.append(self._filt_lfo)
        synthesizer.blocks.append(self._filt_base)
        synthesizer.blocks.append(self._bend)
        # The envelope is a modulation SOURCE: it produces 0 -> amount and
        # knows nothing about filters. Created once and never replaced,
        # since sounding voices hold references to its buffer and blocks.
        self._fenv = AHREnvelope()
        self._fenvs = {}  # midi_note -> env block, for held notes
        # The pitch envelope is the SAME class, falling instead of rising:
        # penv_amount settling to 0 (true pitch), then on note-off drifting
        # on to penv_out_amount. Its own instance, so its shape buffer and
        # rates are independent of the filter's.
        self._penv = AHREnvelope(falling=True)
        self._penvs = {}  # midi_note -> pitch env block
        # "voice under construction" temporaries, set by note_on around the
        # call to _make_notes so _make_filter and the subclasses can pick
        # them up
        self._fenv_cur = None
        self._cutoff_cur = None
        self._penv_cur = None
        self._bend_cur = None
        # live mirrors of patch values that have nowhere else to live
        self._filt_type = None
        self._filt_mode = None
        self._amp_env = [0.01, 0.10, 0.8, 0.35]
        # a mirror rather than 1/_vib_fade.rate, to avoid a reciprocal
        # round-trip through save/load
        self._vib_delay = 0.0
        self._env = self._make_env()
        if patch:
            self.load_patch(patch)

    # --- patch <-> live state -------------------------------------------
    # _recompile() reads the patch; _decompile() writes it. Nothing else
    # touches self.patch.

    def load_patch(self, patch):
        self.patch = patch
        self._recompile()

    def _recompile(self):
        """Compile patch data into live blocks and cached natives. Once per
        patch load, never per note. Subclasses call super()._recompile()."""
        p = self.patch
        # type(self).mono, NOT False: styles that are inherently monophonic
        # (BasslineSynth, SwarmSynth) declare it as a class attribute, and a
        # patch that does not mention mono must not de-mono them.
        want_mono = getattr(p, "mono", None)
        self.mono = type(self).mono if want_mono is None else want_mono
        self._filt_type = p.filt_type
        self._filt_mode = FILTER_MODES.get(p.filt_type)  # None = no filter
        # list(), NOT the patch's own list: attack_time & friends mutate
        # self._amp_env element-wise, and aliasing it would let a knob turn
        # write straight through into the loaded patch.
        self._amp_env = list(p.amp_env)
        self._env = self._make_env()
        self._filt_f_blk.a = p.filt_f  # write, don't replace
        self._filt_q_blk.a = p.filt_q
        self._filt_vel_blk.a = p.filt_vel
        self._fenv_vel_blk.a = p.fenv_vel
        self._filt_track_blk.a = p.filt_track
        self._filt_lfo.rate = p.filt_lfo_rate
        # via the property: the amount is a half-swing plus a matching
        # offset, and writing .scale alone here would leave a stale offset
        self.filt_lfo_amount = p.filt_lfo_amount
        self._vib_lfo.rate = p.vib_rate
        self._vib_depth_blk.a = p.vib_depth
        self.vib_delay = p.vib_delay  # via the property: sets a rate
        self.glide_time = getattr(p, "glide_time", 0.0)  # ditto
        # written into the existing envelopes, never new ones, and in one
        # call each so the shape is rebuilt once rather than per parameter
        self._fenv.configure(p.fenv_attack, p.fenv_release, p.fenv_amount, p.fenv_curve)
        # curve 1: penv_curve is not a patch field, though the class takes one
        self._penv.configure(p.penv_time, p.penv_out_time, p.penv_amount, 1, p.penv_out_amount)

    def _decompile(self):
        """Push live state back into self.patch. The opposite of
        _recompile(). Subclasses call super()._decompile()."""
        p = self.patch
        p.mono = self.mono  # resolves "unspecified" to what is actually live
        p.filt_type = self._filt_type
        p.amp_env = list(self._amp_env)  # copy out, so later knob turns
        #                                     do not leak into the patch
        p.filt_f = self._filt_f_blk.a
        p.filt_q = self._filt_q_blk.a
        p.filt_vel = self._filt_vel_blk.a
        p.fenv_vel = self._fenv_vel_blk.a
        p.filt_track = self._filt_track_blk.a
        p.filt_lfo_rate = self._filt_lfo.rate
        p.filt_lfo_amount = self.filt_lfo_amount  # undoes the half-swing
        p.vib_rate = self._vib_lfo.rate
        p.vib_depth = self._vib_depth_blk.a
        p.vib_delay = self._vib_delay
        p.glide_time = self._glide_time
        p.penv_amount = self._penv.amount
        p.penv_time = self._penv.attack
        p.penv_out_amount = self._penv.release_amount
        p.penv_out_time = self._penv.release
        p.fenv_amount = self._fenv.amount
        p.fenv_attack = self._fenv.attack
        p.fenv_release = self._fenv.release
        p.fenv_curve = self._fenv.curve

    def save_patch(self):
        """Snapshot what is currently being heard into the Patch, and return
        it. Knob turns do not reach the patch on their own, so call this
        before Patch.save():

            synth.save_patch().save("/patch.json")

        Mutates and returns the patch that was loaded; it is the same
        object, not a copy.
        """
        self._decompile()
        return self.patch

    def _make_env(self):
        a, d, s, r = self._amp_env
        return synthio.Envelope(attack_time=a, decay_time=d, sustain_level=s, release_time=r)

    # --- per-voice construction -----------------------------------------

    def _voice_fenv_gain(self, velocity):
        """This voice's envelope depth scale.

        Plain 1.0 when fenv_vel is off: there is no arithmetic to avoid in
        that case, and it lets AHREnvelope skip a block. Otherwise a LERP
        block, which is exactly `1 - fenv_vel + fenv_vel * vel_norm` but
        with fenv_vel still LIVE inside it, so the knob keeps reaching the
        voice after it has been pressed.
        """
        if not self._fenv_vel_blk.a:
            return 1.0
        return lerp(1.0, velocity / 127.0, self._fenv_vel_blk)

    def _voice_offsets(self, midi_note, velocity):
        """This voice's velocity and keyboard-tracking offsets, as ONE node.

        Both are the same idiom: a per-voice constant computed in Python,
        multiplied by a shared block that stays LIVE inside the graph, so
        the knob keeps reaching the voice after it has been pressed. They
        are folded together here so the cutoff SUM keeps its existing three
        inputs (base, envelope, offsets) instead of needing a fourth,
        which is also what lets BasslineSynth keep re-aiming one shared node.

        Returns None when neither is in play, so the ordinary patch
        allocates nothing at all.
        """
        vel_hz = None
        if self._filt_vel_blk.a:
            # signed: a negative filt_vel closes the filter as you play
            # harder. filt_vel stays live inside the PRODUCT.
            vel_hz = product(self._filt_vel_blk, velocity / 127.0)
        trk_hz = None
        if self._filt_track_blk.a:
            # cutoff += filt_f * filt_track * (f/f_ref - 1), so filt_track
            # 1.0 gives filt_f * f/f_ref: full tracking, the filter doubling
            # per octave. filt_f is nested rather than read, so BOTH knobs
            # stay live on a sounding voice.
            #
            # A ratio of two midi_to_hz values, not 2**(n/12). Real synthio's
            # midi_to_hz is NOT the exact formula the test stub uses
            # (measured on rp2040: midi_to_hz(69) reads 439.9991, not 440.0),
            # but its octave ratio is exactly 2.000000000, so a ratio is
            # right both on device and under the stubs.
            ratio = synthio.midi_to_hz(midi_note) / self._track_ref_hz - 1.0
            trk_hz = product(self._filt_f_blk, self._filt_track_blk, ratio)
        if vel_hz is None:
            return trk_hz
        if trk_hz is None:
            return vel_hz
        return sum3(vel_hz, trk_hz)

    def _voice_cutoff(self, midi_note, velocity):
        """This voice's node on the cutoff bus: SUM(base, envelope, offsets).

        Returns the SHARED base unchanged when neither the envelope nor any
        per-voice offset is in play, so the ordinary case allocates nothing
        at all. Either way filt_f reaches this voice with one write, because
        the shared base is nested inside.
        """
        if self._filt_mode is None:
            return None
        offsets = self._voice_offsets(midi_note, velocity)
        if self._fenv_cur is None and offsets is None:
            return self._filt_base  # already clamped
        # `is None` rather than truthiness throughout: these are synthio
        # blocks, and whether one is falsy is not ours to assume.
        #
        # Clamped again here, not just on the shared base: a downward
        # fenv_amount (a normal patch), a negative filt_vel, or a large
        # negative filt_track on a high note can each drive this sum below
        # zero on their own.
        return clamp(
            sum3(
                self._filt_base,
                self._fenv_cur if self._fenv_cur is not None else 0.0,
                offsets if offsets is not None else 0.0,
            ),
            self.FILT_F_MIN,
            self.FILT_F_MAX,
        )

    def _voice_bend(self):
        """This voice's bend input, shared by all its Notes.

        Returns the SHARED bend graph unchanged when no pitch envelope is
        in play, so the ordinary case allocates nothing and vibrato and the
        pitch wheel keep reaching every voice with one write. When there is
        one, the shared graph is still nested inside, so that stays true.

        Only meaningful during note_on: it reads the temporaries note_on
        sets up around _make_notes.
        """
        if self._penv_cur is None:
            return self._bend
        return sum3(self._bend, self._penv_cur)

    def _make_filter(self):
        """Per-note Biquad (filters hold state, so they cannot be shared).
        Every Note of one voice shares one cutoff graph.

        Only meaningful during note_on: it reads the temporaries note_on
        sets up around _make_notes.
        """
        if self._filt_mode is None:
            return None
        # fmt: off
        return synthio.Biquad(self._filt_mode, frequency=self._cutoff_cur,
                              Q=self._filt_q_blk)
        # fmt: on

    # --- real-time path -------------------------------------------------

    def _make_notes(self, midi_note, velocity):
        """Return a tuple of synthio.Note for this key. Override me."""
        raise NotImplementedError

    def note_on(self, midi_note, velocity=127, glide=None):
        """Press a note.

        ``glide`` overrides glide_time in seconds for this note only, and
        only matters in mono: a per-step slide flag needs that, because
        writing glide_time itself would leak into the patch.
        """
        if self.mono:
            # one voice: steal whatever is sounding, whichever note it is
            secs = self._glide_time if glide is None else glide
            stolen = [n for notes in self.voices.values() for n in notes] if secs else ()
            self.all_notes_off()
            # Freeze the stolen notes' pitch BEFORE aiming the glide.
            #
            # They are released but still audible, and they share the bend
            # graph _aim_glide is about to point at the NEW note's starting
            # pitch, which is offset by the interval being glided. So the old
            # tail gets yanked there too. Measured on rp2040: stepping
            # 43 -> 46 with a 0.35s glide dropped the still-sounding 43 to
            # 81.7 Hz, three semitones BELOW where it had been, and with a
            # slow attack that tail is the loudest thing present, so the step
            # sounds like it goes DOWN.
            #
            # The trade is that a frozen tail no longer receives vibrato, the
            # pitch wheel or a pitch-envelope release drift. Acceptable on a
            # fading release, and it only happens when portamento is on.
            for n in stolen:
                b = n.bend
                n.bend = getattr(b, "value", b)
            self._aim_glide(midi_note, glide)
        elif midi_note in self.voices:
            self.note_off(midi_note)
        # Restart the vibrato fade only when starting from silence, so
        # adding a note to a held chord does not duck everyone's vibrato
        # back to zero. After the steal above, so a mono retrigger still
        # counts as starting from silence.
        if not self.voices:
            self._vib_fade.retrigger()
        # Each envelope is an INPUT to the thing it modulates, so both have
        # to exist first. All four temporaries are set before _make_notes so
        # every Note of this voice shares one cutoff and one bend graph.
        if self._filt_mode is not None:
            self._fenv_cur = self._fenv.make(self._voice_fenv_gain(velocity))
        self._cutoff_cur = self._voice_cutoff(midi_note, velocity)
        self._penv_cur = self._penv.make()
        self._bend_cur = self._voice_bend()
        notes = self._make_notes(midi_note, velocity)
        if self._fenv_cur is not None:
            self._fenvs[midi_note] = self._fenv_cur
        if self._penv_cur is not None:
            self._penvs[midi_note] = self._penv_cur
        self._fenv_cur = None
        self._cutoff_cur = None
        self._penv_cur = None
        self._bend_cur = None
        self.voices[midi_note] = notes
        self.synthio.press(notes)

    def note_off(self, midi_note):
        notes = self.voices.pop(midi_note, None)
        if notes:
            # the Note keeps these alive while it rings out
            env = self._fenvs.pop(midi_note, None)
            if env is not None:
                self._fenv.start_release(env)
            penv = self._penvs.pop(midi_note, None)
            if penv is not None:
                self._penv.start_release(penv)
            # Freeze the bend on the way out, for the same reason note_on()
            # freezes the notes it steals, but covering the case note_on()
            # structurally cannot see: releasing pops the note from
            # self.voices while it is still audible, so a later glide drags
            # this tail along. Measured on rp2040, playing 48, releasing it,
            # then gliding to 36 threw the still-ringing 48 up to midi 57.9,
            # above BOTH notes, before it slid back.
            #
            # Guarded on glide_time so a tail keeps its vibrato when there is
            # no portamento to drag it. note_on()'s freeze is still not
            # redundant: it uses the per-note `glide` override, which can be
            # non-zero while glide_time is 0.
            if self.mono and self._glide_time:
                for n in notes:
                    b = n.bend
                    n.bend = getattr(b, "value", b)
            self.synthio.release(notes)

    def all_notes_off(self):
        for midi_note in list(self.voices.keys()):
            self.note_off(midi_note)

    def pitch_bend(self, amount):
        """+/-1.0 = one octave. One write into the shared bend graph, O(1)."""
        self._bend_blk.a = amount  # bend is performance state, not patch state

    def _aim_glide(self, midi_note, seconds=None):
        """Point the shared glide block at ``midi_note`` and start it.

        Bend units are octaves, so a semitone is 1/12. The offset is where
        the pitch STARTS; it always ends at 0, i.e. the note's own pitch.

        Called from note_on() in mono only. Note the previous note is
        still releasing at this point and shares this bend, so a glide
        drags its tail along too: inherent to a shared bend, and only
        audible with a long amp release and a long glide together.
        """
        prev = self._last_midi
        self._last_midi = midi_note
        secs = self._glide_time if seconds is None else seconds
        self._glide_pos.rate = 1.0 / max(secs, 0.001)
        if prev is None:
            self._glide.a = 0.0  # first note ever: nothing to glide from
        else:
            # Plus whatever glide is still in flight, so interrupting one
            # mid-slide starts the next from where the pitch actually IS.
            # Same structural continuity as AHREnvelope.start_release()'s
            # `env.a = env.value`: there is no rate to recompute.
            self._glide.a = (prev - midi_note) / 12.0 + self._glide.value
        self._glide_pos.retrigger()

    # --- live parameters ------------------------------------------------
    # Setters write live state ONLY. Getters read it back. The patch is not
    # involved until save_patch().

    @property
    def filt_f(self):
        return self._filt_f_blk.a

    @filt_f.setter
    def filt_f(self, v):
        self._filt_f_blk.a = v  # reaches every sounding voice, O(1)

    @property
    def filt_q(self):
        """Filter resonance, shared by every voice.

        **Useful range is about 0.6 to 6.** Below 0.6 the filter is
        overdamped and the knob does nothing audible; past 6 it is
        squealing and close to self-oscillating, so the top of a wider
        range is travel nobody wants. Size UI ranges to that, and
        remember that anything adding to resonance (``BasslineSynth``'s
        ``accent_q``, which lands on the same block's spare input) eats
        into the same ceiling.
        """
        return self._filt_q_blk.a

    @filt_q.setter
    def filt_q(self, v):
        self._filt_q_blk.a = v

    @property
    def filt_type(self):
        return self._filt_type

    @filt_type.setter
    def filt_type(self, v):
        self._filt_type = v
        self._filt_mode = FILTER_MODES.get(v)  # applies at next note-on

    # --- amp envelope ---------------------------------------------------
    # synthio.Envelope is immutable: every ADSR edit means a new object, one
    # small allocation per knob movement, so deadband the inputs.
    # push_env controls whether *sounding* notes get the new envelope:
    #   True  - turning release while holding a chord affects that release,
    #           which is what a player expects
    #   False - edits apply from the next note-on only. Safest.
    push_env = True

    def _rebuild_env(self):
        self._env = self._make_env()
        if self.push_env:
            for notes in self.voices.values():
                for n in notes:
                    n.envelope = self._env

    @property
    def amp_env(self):
        return self._amp_env

    @amp_env.setter
    def amp_env(self, v):
        self._amp_env = list(v)
        self._rebuild_env()

    @property
    def attack_time(self):
        return self._amp_env[0]

    @attack_time.setter
    def attack_time(self, v):
        self._amp_env[0] = v  # in-place, no list rebuild
        self._rebuild_env()

    @property
    def decay_time(self):
        return self._amp_env[1]

    @decay_time.setter
    def decay_time(self, v):
        self._amp_env[1] = v
        self._rebuild_env()

    @property
    def sustain_level(self):
        return self._amp_env[2]

    @sustain_level.setter
    def sustain_level(self, v):
        self._amp_env[2] = v
        self._rebuild_env()

    @property
    def release_time(self):
        return self._amp_env[3]

    @release_time.setter
    def release_time(self, v):
        self._amp_env[3] = v
        self._rebuild_env()

    # --- vibrato: both are single scalar writes into the shared graph ----

    @property
    def vib_depth(self):
        return self._vib_depth_blk.a

    @vib_depth.setter
    def vib_depth(self, v):
        # into its own block rather than onto LFO.scale, because scale now
        # holds PRODUCT(depth, fade). Still one write, still O(1).
        self._vib_depth_blk.a = v

    @property
    def vib_rate(self):
        return self._vib_lfo.rate

    @vib_rate.setter
    def vib_rate(self, v):
        self._vib_lfo.rate = v

    @property
    def vib_delay(self):
        """Seconds for the vibrato to fade in from nothing, restarted
        whenever playing begins from silence.

        Only a rate on the shared fade ramp, so it is cheap on a knob. It
        takes effect at the NEXT retrigger, not mid-fade.
        """
        return self._vib_delay

    @vib_delay.setter
    def vib_delay(self, v):
        self._vib_delay = v
        self._vib_fade.rate = 1.0 / max(v, 0.001)

    @property
    def glide_time(self):
        """Seconds to slide from the previous note into a new one.

        Portamento. Only applies while ``mono`` is set: one shared bend
        would drag every sounding voice otherwise. Only a rate on the
        shared ramp, so it is cheap on a knob, and it takes effect at the
        next note-on rather than mid-glide.
        """
        return self._glide_time

    @glide_time.setter
    def glide_time(self, v):
        self._glide_time = v
        self._glide_pos.rate = 1.0 / max(v, 0.001)

    # --- pitch envelope --------------------------------------------------
    # Thin delegates onto self._penv, an AHREnvelope running falling:
    # penv_amount -> 0 on the way in, then on to penv_out_amount on the way
    # out. Amounts are bend units, 1.0 = one octave. Like fenv_amount,
    # raising either from 0 only affects NEW notes, because at 0 no
    # per-voice node is built to write into.

    @property
    def penv_amount(self):
        return self._penv.amount

    @penv_amount.setter
    def penv_amount(self, v):
        self._penv.amount = v

    @property
    def penv_time(self):
        return self._penv.attack

    @penv_time.setter
    def penv_time(self, v):
        self._penv.attack = v

    @property
    def penv_out_amount(self):
        return self._penv.release_amount

    @penv_out_amount.setter
    def penv_out_amount(self, v):
        self._penv.release_amount = v

    @property
    def penv_out_time(self):
        return self._penv.release

    @penv_out_time.setter
    def penv_out_time(self, v):
        self._penv.release = v

    # --- filter LFO: shared, so both are one write ----------------------

    @property
    def filt_lfo_rate(self):
        return self._filt_lfo.rate

    @filt_lfo_rate.setter
    def filt_lfo_rate(self, v):
        self._filt_lfo.rate = v

    @property
    def filt_lfo_amount(self):
        """Hz ADDED above filt_f: the cutoff swings 0..v, never below it.

        synthio's LFO is ``waveform[idx] * scale + offset``, and the default
        waveform is a triangle centred on zero, so ``scale`` on its own is a
        HALF-swing about zero. Writing scale and offset to the same v/2
        recentres it: -v/2..+v/2 shifted up by v/2 is 0..v. This is the
        min/max-to-midpoint/range conversion from README-2-Modulation.md,
        with lmin fixed at 0.

        Doing it this way rather than with a custom unipolar waveform keeps
        the LFO on synthio's internal 16-bit resolution: a hand-built
        64-sample buffer would be measurably steppier.

        Two writes, but both land on the ONE shared LFO, so this is still
        O(1) in polyphony: there is no per-voice copy to walk.
        """
        return self._filt_lfo.scale * 2.0  # stored as half-swing, see below

    @filt_lfo_amount.setter
    def filt_lfo_amount(self, v):
        half = v * 0.5
        self._filt_lfo.scale = half
        self._filt_lfo.offset = half

    # --- filter envelope params -----------------------------------------
    # Thin delegates onto self._fenv, which owns the blocks and buffers.

    @property
    def fenv_amount(self):
        return self._fenv.amount

    @fenv_amount.setter
    def fenv_amount(self, v):
        # one write into the shared block, release included. If amount was 0
        # at note-on no envelope was built for that voice, so raising it from
        # 0 only affects new notes.
        self._fenv.amount = v

    @property
    def fenv_attack(self):
        return self._fenv.attack

    @fenv_attack.setter
    def fenv_attack(self, v):
        self._fenv.attack = v  # a rate write: cheap on a knob

    @property
    def fenv_release(self):
        return self._fenv.release

    @fenv_release.setter
    def fenv_release(self, v):
        self._fenv.release = v

    @property
    def fenv_curve(self):
        return self._fenv.curve

    @fenv_curve.setter
    def fenv_curve(self, v):
        # the shape is rewritten in place, so sounding voices morph
        # immediately, release included. O(1), but it allocates temporaries:
        # a switch, not a knob.
        self._fenv.curve = v

    # --- velocity -------------------------------------------------------
    # Both are shared blocks nested in each voice's graph, so they stay live
    # for voices that already have the relevant node. Turning one on from
    # zero still only affects new notes: at zero no node is built at all.

    @property
    def filt_vel(self):
        return self._filt_vel_blk.a

    @filt_vel.setter
    def filt_vel(self, v):
        self._filt_vel_blk.a = v

    @property
    def filt_track(self):
        """Keyboard tracking: how much the cutoff follows the played pitch.

        1.0 is full tracking: the cutoff doubles per octave, so the filter
        stays at a fixed point in the harmonic series and every note has the
        same timbre. 0 is off. Negative tracks INVERSELY, closing the filter
        as you play higher, which is what the Swarmatron's tracking knob does
        on the other side of centre.

        Pivots at ``FILT_TRACK_REF`` (MIDI 60): that note's cutoff is
        ``filt_f`` no matter what this is set to.

        One write, and it reaches every sounding voice: it is nested LIVE
        inside each voice's tracking node alongside ``filt_f``, so both keep
        moving a note that is already playing. Only turning it on *from
        zero* is next-note-on, the same caveat ``filt_vel`` has: at zero no
        node exists to write into.
        """
        return self._filt_track_blk.a

    @filt_track.setter
    def filt_track(self, v):
        self._filt_track_blk.a = v

    @property
    def fenv_vel(self):
        return self._fenv_vel_blk.a

    @fenv_vel.setter
    def fenv_vel(self, v):
        self._fenv_vel_blk.a = v

    def set_param(self, name, val):
        """String front-end for MIDI CC / UI / patch-editor code.
        Prefer ``synth.filt_f = v`` in hot loops."""
        if name not in self._PARAMS:
            raise KeyError(name)
        setattr(self, name, val)
