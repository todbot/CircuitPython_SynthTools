# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# swarm_synth.py -- a massed-oscillator drone voice in the style of the
# Dewanatron Swarmatron: N oscillators on one pitch, fanned apart by a
# single "swarm" control.
#
# The real instrument is eight oscillators, sine or sawtooth, played
# MONOPHONICALLY from a pitch ribbon. A second ribbon and a knob drive the
# "swarm" from a few cents apart out to "a wide chord of equidistant pitches
# spread over the entire spectrum". EQUIDISTANT is the operative word: hence
# the evenly spaced fan in _set_fan(), and why swarm_spread is not clamped
# to a narrow chorus range. "Taffy pulling", working both ribbons together,
# is the signature gesture, and the reason the spread here is a live shared
# block rather than a per-Note frequency.
#
# References:
#   https://en.wikipedia.org/wiki/Swarmatron
#   https://www.soundonsound.com/reviews/dewanatron-swarmatron
#   http://dewanatron.com/instruments.php?page=swarmatron
#
# Building this from a SubtractiveSynth playing 8 notes would mean finding
# and rewriting every sounding Note on every sweep, since
# synthio.Note.frequency is a plain float:
#
#     for notes in self.voices.values():          # subtractive_synth.py
#         notes[1].frequency = notes[0].frequency * v
#
# note.bend is a BlockInput instead, so the whole fan hangs off ONE shared
# scalar block and a sweep is a single write reaching every sounding
# oscillator, O(1) in polyphony:
#
#   SHARED (built once in __init__, one set per synth):
#     fan[i] = SUM(PRODUCT(swarm_blk, k_i), drift_lfo[i])
#                k_i         fixed fan coefficient, evenly over [-1, +1]
#                drift_lfo[i] = LFO(rate = slow_i, scale = drift_blk)
#
#   PER VOICE (one per oscillator, built at note_on):
#     note[i].bend = SUM(voice_bend, fan[i])
#
# swarm_drift models the real instrument's analog oscillator drift; without
# it a fixed-ratio digital fan sounds like a chorus pedal. Those LFOs run at
# mutually non-harmonic slow rates with staggered phase so they never line
# up, and synthio's default zero-centred triangle is already the right
# bipolar shape.
#

import synthio

from .blocks import product, scalar_block, sum3
from .synth import Synth
from .waves import get_wave_2x, random_phase_wave


class SwarmSynth(Synth):
    """A Swarmatron-style drone voice: ``swarm_count`` oscillators on one
    pitch, fanned apart in a symmetric spread and drifting independently.

    Monophonic by default (``mono = True``), like the instrument it is named
    after: see the module docstring for the polyphony arithmetic. Set
    ``glide_time`` for the ribbon-ish slide between notes.

    Patch fields, on top of the shared ``Synth`` ones:

    ``wave``
        oscillator waveform name, as SubtractiveSynth. The real
        instrument switches between sine and sawtooth.
    ``swarm_count``
        oscillators per key, 1..MAX_OSCS. Applied at the next note-on.
    ``swarm_spread``
        the OUTERMOST oscillator's offset, in bend units (octaves):
        0.01 = +/-12 cents, 1.0 = a two-octave equidistant cluster. The
        rest fan evenly between, symmetric about the played pitch.
    ``swarm_drift``
        depth of each oscillator's slow independent wander, same units;
        0 = perfectly stable tuning.

    ``swarm_spread`` and ``swarm_drift`` are each ONE write into a shared
    block and reach every sounding oscillator, so sweeping the swarm under
    a held drone (the whole point of the instrument) works at any
    polyphony. ``swarm_count`` changes what the NEXT note-on builds; voices
    already sounding keep the oscillators they were pressed with.
    """

    #: Most oscillators a single key can stack. The fan blocks are all built
    #: up front, so this is a fixed cost, not a per-note one.
    MAX_OSCS = 8

    _PARAMS = Synth._PARAMS + ("wave", "swarm_count", "swarm_spread", "swarm_drift")

    #: One voice at a time, like the real instrument, and 8 oscillators a
    #: key means poly runs out of synthio's 24-note budget at three keys.
    mono = True

    # class attrs: the base __init__ builds its graph before this subclass
    # has run any setup of its own
    _wave_name = "SAW"
    _swarm_count = MAX_OSCS

    def __init__(self, synthesizer, patch=None):
        # The shared fan is built HERE, before super().__init__() runs its
        # load_patch() -> _recompile(): it must exist by then, and none of it
        # may ever be replaced, since sounding voices hold references.
        self._swarm_blk = scalar_block(0.0)
        self._drift_blk = scalar_block(0.0)
        self._drift_lfos = []
        self._fan = []
        for i in range(self.MAX_OSCS):
            # Slow, mutually non-harmonic rates plus a staggered phase so the
            # oscillators never wander in step.
            lfo = synthio.LFO(
                rate=0.07 + 0.031 * i,
                scale=self._drift_blk,
                phase_offset=i / self.MAX_OSCS,
            )
            self._drift_lfos.append(lfo)
            # .b holds the fan coefficient and is rewritten in place by
            # _set_fan(); the block itself is never replaced.
            self._fan.append(sum3(product(self._swarm_blk, 0.0), lfo))
        self._set_fan(self._swarm_count)
        # The fan Math MUST be rooted; everything nested inside it need not
        # be, so this is one append per oscillator, not two.
        #
        # An UNROOTED fan reads 0.0 with nothing sounding AND at the first
        # note-on that uses it, so the swarm would sound in unison for one
        # 5.8ms block before snapping apart. Same class of bug as the 0.0 Hz
        # first-note cutoff in synth.py.
        #
        # A continuous LFO nested inside a rooted Math does tick. Measured:
        # rooted, nested-only and rooted+nested LFOs all advanced over 0.7s
        # at 2 Hz; only a genuinely orphaned one stayed frozen. "An
        # unattached LFO never ticks" means UNATTACHED, not un-rooted.
        for f in self._fan:
            synthesizer.blocks.append(f)
        super().__init__(synthesizer, patch)

    def _set_fan(self, count):
        """Write the fan coefficients for ``count`` oscillators.

        Evenly spaced over [-1, +1], symmetric about the played pitch, so an
        ODD count puts one oscillator exactly on true pitch. Written into
        the existing PRODUCT blocks' spare .b input rather than rebuilding
        them, so block identity survives a count change and voices already
        sounding are never orphaned. Slots above `count` keep whatever
        coefficient they last held: harmless, since nothing reads them
        until a note-on uses that slot again, which rewrites it first.
        """
        for i in range(count):
            # count == 1 would divide by zero; a lone oscillator sits on pitch
            self._fan[i].a.b = 0.0 if count == 1 else (2.0 * i / (count - 1)) - 1.0

    def _recompile(self):
        super()._recompile()
        p = self.patch
        self._wave_name = p.wave
        get_wave_2x(self._wave_name)  # warm the cache; note-on only slices
        self._swarm_count = self._clamp_count(getattr(p, "swarm_count", self.MAX_OSCS))
        self._set_fan(self._swarm_count)
        self._swarm_blk.a = getattr(p, "swarm_spread", 0.01)
        self._drift_blk.a = getattr(p, "swarm_drift", 0.003)

    def _decompile(self):
        super()._decompile()
        p = self.patch
        p.wave = self._wave_name
        p.swarm_count = self._swarm_count
        p.swarm_spread = self._swarm_blk.a
        p.swarm_drift = self._drift_blk.a

    def _clamp_count(self, v):
        return min(self.MAX_OSCS, max(1, int(v)))

    def _make_notes(self, midi_note, velocity):
        f = synthio.midi_to_hz(midi_note)
        # Detuned oscillators beat, so their peaks DO periodically align:
        # divide by the count so the worst case still tops out at 1.0, the
        # same ceiling SubtractiveSynth's 0.625/0.375 split keeps. Make the
        # level back up at the mixer, not here.
        # FIXME: check this experimentally
        amp = velocity / 127 / self._swarm_count
        notes = []
        for i in range(self._swarm_count):
            # The per-Note SUM is built even when swarm_spread is 0. The
            # tempting _voice_cutoff()-style "allocate nothing when it's off"
            # shortcut would make the swarm knob next-note-on only from zero,
            # and sweeping the spread up from nothing under a held drone is
            # exactly what this instrument is for.
            # fmt: off
            notes.append(synthio.Note(f, waveform=random_phase_wave(self._wave_name),
                                      envelope=self._env, amplitude=amp,
                                      filter=self._make_filter(),
                                      bend=sum3(self._bend_cur, self._fan[i])))
            # fmt: on
        return tuple(notes)

    @property
    def wave(self):
        """Oscillator waveform name, shared by every oscillator in the swarm.

        Each one still gets its OWN random start point in the cycle at every
        note-on, which is half of what keeps a swarm from sounding phasey.
        """
        return self._wave_name

    @wave.setter
    def wave(self, v):
        self._wave_name = v
        get_wave_2x(v)  # O(1); warms the cache for the next note-on

    @property
    def swarm_count(self):
        """Oscillators per key, 1..MAX_OSCS.

        Genuinely structural (it changes how many Notes a key builds) so
        it applies at the NEXT note-on; voices already sounding keep theirs.
        Nothing downstream needs re-wiring for that, which is why it is a
        safe set_param() name.
        """
        return self._swarm_count

    @swarm_count.setter
    def swarm_count(self, v):
        self._swarm_count = self._clamp_count(v)
        self._set_fan(self._swarm_count)

    @property
    def swarm_spread(self):
        """The outermost oscillator's pitch offset, in bend units (octaves).

        0 collapses the swarm to unison; 0.01 is +/-12 cents; 0.5 and up is
        the equidistant chord spread over octaves that the real instrument's
        span ribbon reaches. Not clamped, because both ends are the
        instrument. One write, reaching every sounding oscillator.
        """
        return self._swarm_blk.a

    @swarm_spread.setter
    def swarm_spread(self, v):
        self._swarm_blk.a = v

    @property
    def swarm_drift(self):
        """Depth of each oscillator's slow independent wander, bend units.

        0 = perfectly stable digital tuning. A few thousandths (0.002-0.006)
        is the analog-ish restlessness the real instrument has. One write,
        into the shared scale of every drift LFO at once.
        """
        return self._drift_blk.a

    @swarm_drift.setter
    def swarm_drift(self, v):
        self._drift_blk.a = v
