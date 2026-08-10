# synth.py - Synth base class.
# Owns: voice bookkeeping, patch load/save, live parameter updates.
# Subclasses override _recompile() / _decompile() and _make_notes(), and
# extend _PARAMS.
#
# Requires CircuitPython 10+ (mode-based synthio.Biquad).
#
# --- two ideas run through this file ---------------------------------
#
# 1. THE PATCH IS NOT LIVE STATE. A Patch is inert JSON-able data. It is
#    read once by _recompile() and then left alone -- turning a knob does
#    NOT write to it. save_patch() is the only thing that pushes live
#    state back, via _decompile(). So "the patch on disk" and "what I am
#    hearing" are separate things, and reloading the patch reverts.
#
# 2. PARAMETERS ARE BLOCKS, NOT NUMBERS. Anywhere synthio accepts a
#    BlockInput, a shared synthio.Math can stand in for a float and stay
#    writable. Every voice nests the same shared block, so one write
#    reaches all of them inside the C renderer -- O(1) in polyphony,
#    regardless of how many notes are sounding. Doing that arithmetic in
#    the block graph rather than in Python is also what lets a knob reach
#    a note that is ALREADY playing.
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
# Every param is a property, so `synth.filt_f = 1000` is the fast path and
# set_param() is just a string front-end for MIDI CC / UI code.

import synthio

from .ahr_envelope import AHREnvelope
from .blocks import scalar_block, sum3, product, lerp, clamp

FILTER_MODES = {
    "LPF": synthio.FilterMode.LOW_PASS,
    "HPF": synthio.FilterMode.HIGH_PASS,
    "BPF": synthio.FilterMode.BAND_PASS,
    "NOTCH": synthio.FilterMode.NOTCH,
}


class Synth:
    # names settable via set_param(); also what a UI can enumerate
    _PARAMS = ("filt_f", "filt_q", "filt_type", "amp_env",
               "attack_time", "decay_time", "sustain_level", "release_time",
               "vib_depth", "vib_rate",
               "filt_lfo_rate", "filt_lfo_amount",
               "fenv_amount", "fenv_attack", "fenv_release", "fenv_curve",
               "filt_vel", "fenv_vel")

    # The cutoff bus can now be driven below zero -- a downward fenv_amount,
    # a negative filt_vel, a big filt_lfo_amount -- none of which was
    # reachable when the cutoff was just a scalar. So it is clamped, in one
    # MID block, since the middle of three values is exactly a clamp.
    #
    # A negative Biquad.frequency does NOT raise or crash (measured on
    # CircuitPython 10.3.0-alpha.3 / rp2040), so this is defensive rather
    # than mandatory: what such a filter *sounds* like is undefined, and a
    # downward sweep hitting 0 Hz is an ordinary patch, not an edge case.
    # Cost is one shared block plus one per modulated voice.
    FILT_F_MIN = 20.0
    FILT_F_MAX = 20000.0

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
        # Bend graph, shared by every voice:
        #   vib_lfo (depth=scale) --\
        #                            SUM --> note.bend
        #   bend_blk (wheel) -------/
        # Both inputs are global, so one Math object serves all notes and
        # both vibrato depth and pitch bend become single scalar writes.
        self._vib_lfo = synthio.LFO(rate=5.0, scale=0.0)
        self._bend_blk = scalar_block(0.0)
        self._bend = sum3(self._vib_lfo, self._bend_blk)
        # --- the filter cutoff modulation bus ------------------------
        # Four sources sum onto one destination:
        #
        #   SHARED:  filt_base = MID(SUM(filt_f, filt_lfo), MIN, MAX)
        #   VOICE:   cutoff    = SUM(filt_base, fenv, vel_hz)
        #                          vel_hz = PRODUCT(filt_vel, vel/127)
        #                          fenv   = AHREnvelope.make(gain)
        #                            gain = LERP(1, vel/127, fenv_vel)
        #
        # SUM takes three inputs, so base+LFO, envelope and velocity all
        # land in ONE per-voice node. Every knob in there is a shared block
        # nested inside it, so each stays a single write no matter how many
        # voices are sounding -- including voices already in release.
        #
        # Every one of the three modulations is ADDITIVE and one-sided:
        # filt_f is the floor and they open upward from it. synthio's LFO
        # outputs `waveform[idx] * scale + offset` and its default waveform
        # is a triangle centred on zero, so scale ALONE would swing
        # +/-amount about filt_f and push the bottom half into the
        # FILT_F_MIN clamp. Setting scale and offset both to amount/2 shifts
        # the whole swing up into 0..amount -- see filt_lfo_amount below.
        self._filt_lfo = synthio.LFO(rate=0.5, scale=0.0, offset=0.0)
        self._filt_sum = sum3(self._filt_f_blk, self._filt_lfo)
        self._filt_base = clamp(self._filt_sum, self.FILT_F_MIN,
                                self.FILT_F_MAX)
        # Anything not reachable from a sounding Note has to be rooted here
        # or synthio never updates it -- and that applies to Math blocks,
        # not just LFOs.
        #
        # The LFOs are the obvious case: unattached, they do not advance, so
        # vibrato and the filter sweep would jump phase at every note-on.
        #
        # `_filt_base` and `_bend` are the non-obvious one. Both are only
        # reachable through a voice, so with nothing sounding they freeze --
        # and on a freshly built Synth they have never been evaluated at
        # all. Measured on hardware: the first note-on after construction
        # read its cutoff as 0.0 Hz (a filter slammed shut for a block, i.e.
        # a click), and later notes after a silence read a stale cutoff
        # frozen at wherever the LFO was when the last voice died. Rooting
        # them here makes the shared half of the graph always-live, so a
        # note-on inherits a correct cutoff and bend on its very first
        # update. Costs two list entries.
        synthesizer.blocks.append(self._vib_lfo)
        synthesizer.blocks.append(self._filt_lfo)
        synthesizer.blocks.append(self._filt_base)
        synthesizer.blocks.append(self._bend)
        # The envelope is a modulation SOURCE: it produces 0 -> amount and
        # knows nothing about filters. Created once and never replaced --
        # sounding voices hold references to its buffer and blocks.
        self._fenv = AHREnvelope()
        self._fenvs = {}          # midi_note -> env block, for held notes
        # "voice under construction" temporaries, set by note_on around the
        # call to _make_notes so _make_filter can pick them up
        self._fenv_cur = None
        self._cutoff_cur = None
        # live mirrors of patch values that have nowhere else to live
        self._filt_type = None
        self._filt_mode = None
        self._amp_env = [0.01, 0.10, 0.8, 0.35]
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
        self._filt_type = p.filt_type
        self._filt_mode = FILTER_MODES.get(p.filt_type)  # None = no filter
        # list(), NOT the patch's own list: attack_time & friends mutate
        # self._amp_env element-wise, and aliasing it would let a knob turn
        # write straight through into the loaded patch.
        self._amp_env = list(p.amp_env)
        self._env = self._make_env()
        self._filt_f_blk.a = p.filt_f                    # write, don't replace
        self._filt_q_blk.a = p.filt_q
        self._filt_vel_blk.a = p.filt_vel
        self._fenv_vel_blk.a = p.fenv_vel
        self._filt_lfo.rate = p.filt_lfo_rate
        # via the property: the amount is a half-swing plus a matching
        # offset, and writing .scale alone here would leave a stale offset
        self.filt_lfo_amount = p.filt_lfo_amount
        self._vib_lfo.rate = p.vib_rate
        self._vib_lfo.scale = p.vib_depth
        # written into the existing envelope, never a new one, and in one
        # call so the shape is rebuilt once rather than per parameter
        self._fenv.configure(p.fenv_attack, p.fenv_release,
                             p.fenv_amount, p.fenv_curve)

    def _decompile(self):
        """Push live state back into self.patch. The opposite of
        _recompile(). Subclasses call super()._decompile()."""
        p = self.patch
        p.filt_type = self._filt_type
        p.amp_env = list(self._amp_env)     # copy out, so later knob turns
        #                                     do not leak into the patch
        p.filt_f = self._filt_f_blk.a
        p.filt_q = self._filt_q_blk.a
        p.filt_vel = self._filt_vel_blk.a
        p.fenv_vel = self._fenv_vel_blk.a
        p.filt_lfo_rate = self._filt_lfo.rate
        p.filt_lfo_amount = self.filt_lfo_amount   # undoes the half-swing
        p.vib_rate = self._vib_lfo.rate
        p.vib_depth = self._vib_lfo.scale
        p.fenv_amount = self._fenv.amount
        p.fenv_attack = self._fenv.attack
        p.fenv_release = self._fenv.release
        p.fenv_curve = self._fenv.curve

    def save_patch(self):
        """Snapshot what is currently being heard into the Patch, and return
        it. Knob turns do not reach the patch on their own, so call this
        before Patch.save():

            synth.save_patch().save("/patch.json")

        Mutates and returns the patch that was loaded -- it is the same
        object, not a copy.
        """
        self._decompile()
        return self.patch

    def _make_env(self):
        a, d, s, r = self._amp_env
        return synthio.Envelope(attack_time=a, decay_time=d,
                                sustain_level=s, release_time=r)

    # --- per-voice construction -----------------------------------------

    def _voice_fenv_gain(self, velocity):
        """This voice's envelope depth scale.

        Plain 1.0 when fenv_vel is off -- there is no arithmetic to avoid in
        that case, and it lets AHREnvelope skip a block. Otherwise a LERP
        block, which is exactly `1 - fenv_vel + fenv_vel * vel_norm` but
        with fenv_vel still LIVE inside it, so the knob keeps reaching the
        voice after it has been pressed.
        """
        if not self._fenv_vel_blk.a:
            return 1.0
        return lerp(1.0, velocity / 127.0, self._fenv_vel_blk)

    def _voice_cutoff(self, velocity):
        """This voice's node on the cutoff bus: SUM(base, envelope, vel).

        Returns the SHARED base unchanged when neither the envelope nor
        velocity is in play, so the ordinary case allocates nothing at all.
        Either way filt_f reaches this voice with one write, because the
        shared base is nested inside.
        """
        if self._filt_mode is None:
            return None
        vel_hz = None
        if self._filt_vel_blk.a:
            # signed: a negative filt_vel closes the filter as you play
            # harder. filt_vel stays live inside the PRODUCT.
            vel_hz = product(self._filt_vel_blk, velocity / 127.0)
        if self._fenv_cur is None and vel_hz is None:
            return self._filt_base          # already clamped
        # `is None` rather than truthiness throughout: these are synthio
        # blocks, and whether one is falsy is not ours to assume.
        # Clamped again here, not just on the shared base: a downward
        # fenv_amount (a normal patch) or a negative filt_vel can drive
        # this sum below zero all on its own.
        return clamp(sum3(self._filt_base,
                          self._fenv_cur if self._fenv_cur is not None else 0.0,
                          vel_hz if vel_hz is not None else 0.0),
                     self.FILT_F_MIN, self.FILT_F_MAX)

    def _make_filter(self):
        """Per-note Biquad (filters hold state, so they cannot be shared).
        Every Note of one voice shares one cutoff graph.

        Only meaningful during note_on: it reads the temporaries note_on
        sets up around _make_notes.
        """
        if self._filt_mode is None:
            return None
        return synthio.Biquad(self._filt_mode, frequency=self._cutoff_cur,
                              Q=self._filt_q_blk)

    # --- real-time path -------------------------------------------------

    def _make_notes(self, midi_note, velocity):
        """Return a tuple of synthio.Note for this key. Override me."""
        raise NotImplementedError

    def note_on(self, midi_note, velocity=127):
        if midi_note in self.voices:
            self.note_off(midi_note)
        # The envelope is an INPUT to the cutoff, so it has to exist first.
        # Both are built before _make_notes so every Note of this voice
        # shares one cutoff graph.
        if self._filt_mode is not None:
            self._fenv_cur = self._fenv.make(self._voice_fenv_gain(velocity))
        self._cutoff_cur = self._voice_cutoff(velocity)
        notes = self._make_notes(midi_note, velocity)
        if self._fenv_cur is not None:
            self._fenvs[midi_note] = self._fenv_cur
        self._fenv_cur = None
        self._cutoff_cur = None
        self.voices[midi_note] = notes
        self.synthio.press(notes)

    def note_off(self, midi_note):
        notes = self.voices.pop(midi_note, None)
        if notes:
            env = self._fenvs.pop(midi_note, None)
            if env is not None:
                # the Note keeps it alive while it rings out
                self._fenv.start_release(env)
            self.synthio.release(notes)

    def all_notes_off(self):
        for midi_note in list(self.voices.keys()):
            self.note_off(midi_note)

    def pitch_bend(self, amount):
        """+/-1.0 = one octave. One write into the shared bend graph, O(1)."""
        self._bend_blk.a = amount   # bend is performance state, not patch state

    # --- live parameters ------------------------------------------------
    # Setters write live state ONLY. Getters read it back. The patch is not
    # involved until save_patch().

    @property
    def filt_f(self):
        return self._filt_f_blk.a

    @filt_f.setter
    def filt_f(self, v):
        self._filt_f_blk.a = v     # reaches every sounding voice, O(1)

    @property
    def filt_q(self):
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
        self._filt_mode = FILTER_MODES.get(v)   # applies at next note-on

    # --- amp envelope ---------------------------------------------------
    # synthio.Envelope is immutable: every ADSR edit means a new object.
    # That is one small allocation per knob movement, so deadband inputs.
    # push_env controls whether *sounding* notes get the new envelope:
    #   True  - turning release while holding a chord affects that release
    #           (what a player expects). Changing sustain_level mid-note
    #           steps the level rather than slewing.
    #   False - edits only apply from the next note-on. Safest.
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
        self._amp_env[0] = v       # in-place, no list rebuild
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
        return self._vib_lfo.scale

    @vib_depth.setter
    def vib_depth(self, v):
        self._vib_lfo.scale = v         # O(1), reaches every sounding voice

    @property
    def vib_rate(self):
        return self._vib_lfo.rate

    @vib_rate.setter
    def vib_rate(self, v):
        self._vib_lfo.rate = v

    # --- filter LFO: shared, so both are one write ----------------------

    @property
    def filt_lfo_rate(self):
        return self._filt_lfo.rate

    @filt_lfo_rate.setter
    def filt_lfo_rate(self, v):
        self._filt_lfo.rate = v

    @property
    def filt_lfo_amount(self):
        return self._filt_lfo.scale * 2.0    # stored as half-swing, see below

    @filt_lfo_amount.setter
    def filt_lfo_amount(self, v):
        """Hz ADDED above filt_f: the cutoff swings 0..v, never below it.

        synthio's LFO is `waveform[idx] * scale + offset`, and the default
        waveform is a triangle centred on zero, so `scale` on its own is a
        HALF-swing about zero. Writing scale and offset to the same v/2
        recentres it: -v/2..+v/2 shifted up by v/2 is 0..v. This is the
        min/max-to-midpoint/range conversion from README-2-Modulation.md,
        with lmin fixed at 0.

        Doing it this way rather than with a custom unipolar waveform keeps
        the LFO on synthio's internal 16-bit resolution -- a hand-built
        64-sample buffer would be measurably steppier.

        Two writes, but both land on the ONE shared LFO, so this is still
        O(1) in polyphony: there is no per-voice copy to walk.
        """
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
        # one write into the shared block; reaches every voice, including
        # ones already in release. Note: if amount was 0 at note-on no
        # envelope was built for that voice, so raising it from 0 only
        # affects new notes.
        self._fenv.amount = v

    @property
    def fenv_attack(self):
        return self._fenv.attack

    @fenv_attack.setter
    def fenv_attack(self, v):
        self._fenv.attack = v           # a rate write: cheap on a knob

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
        # the shape is rewritten in place, so sounding voices -- including
        # ones already in release -- morph immediately. O(1), but it does
        # allocate temporaries: this is a switch, not a knob.
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
    def fenv_vel(self):
        return self._fenv_vel_blk.a

    @fenv_vel.setter
    def fenv_vel(self, v):
        self._fenv_vel_blk.a = v

    def set_param(self, name, val):
        """String front-end for MIDI CC / UI / patch-editor code.
        Prefer `synth.filt_f = v` in hot loops."""
        if name not in self._PARAMS:
            raise KeyError(name)
        setattr(self, name, val)
