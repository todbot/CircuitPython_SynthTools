# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# fm_synth.py - a two-oscillator frequency-modulation synth voice, built on
# the Synth engine (synth.py).
#
# --- how FM happens in synthio ------------------------------------------
#
# synthio has no first-class FM. Note.frequency is a plain float, not a
# BlockInput, so nothing can ride on it; the only pitch input that takes a
# live block is note.bend. So FM here is an audio-rate LFO summed onto that
# bend -- one small block graph per voice:
#
#   VOICE:  note.bend = SUM(shared_bend_graph, fm_lfo)
#           fm_lfo    = LFO(waveform = shared modulator wave,
#                           rate     = PRODUCT(carrier_hz, fm_ratio_blk),
#                           scale    = fm_index_blk, offset = 0)
#
# In most other synthesisers this is called "linear FM" -- the modulator adds
# Hz to the carrier. synthio's bend is multiplicative (frequency * 2**bend),
# so this is "exponential FM", the arrangement most early digital synths and
# analog-modelled ones used. It is proportionally richer in high partials and
# can break up aggressively; a low-pass filter after the voice is the
# traditional tamer -- the shared Synth filter graph is right there.
#
# --- the two FM knobs ---------------------------------------------------
#
# fm_ratio - modulator frequency as a multiple of the carrier (0.5, 1, 2, ...).
#            Stored as a shared scalar block. Each voice's LFO rate is
#            PRODUCT(carrier_hz, that block), so one write reaches every
#            sounding voice -- O(1) in polyphony, even mid-note.
#
# fm_index - FM depth in bend units, where 1.0 = one octave (the same unit
#            synth.py already uses for vib_depth and penv_amount). At index I
#            the modulator swings the carrier pitch by a factor of 2**I before
#            snapping back each cycle. 0 = off, and costs nothing: no per-voice
#            LFO is built at all. 0.5 - 2.0 is a useful starting range.
#
# --- the honest caveats -------------------------------------------------
#
# - Not band-limited. synthio resamples the carrier waveform but does not
#   anti-alias the FM sidebands, so high indexes on high notes fold back
#   noise. Keep the sample rate up and the index modest, or filter after.
# - No feedback. A classic DX "feedback" operator reads its own output, which
#   the synthio block graph cannot express (no cycles). The closest stand-in
#   is an audiofilters.Distortion after the voice.
#
# Both are inherent to synthio, not gaps this file could have filled.

import synthio

from .blocks import product, scalar_block, sum3
from .synth import Synth
from .waves import get_wave, get_wave_2x, random_phase_wave

#: single-cycle size of the modulator waveform table, same as the carrier
FM_WAVE_SIZE = 256


class FMSynth(Synth):
    """A frequency-modulation voice: one carrier oscillator whose pitch is
    bent (via ``note.bend``, the only live pitch input synthio offers) by an
    audio-rate modulator LFO.

    Patch fields, on top of the shared Synth ones:

        fm_ratio  modulator frequency, as a ratio of the carrier
        fm_index  FM depth, in bend units (octaves); 0 = off
        fm_wave   modulator waveform name (any ``waves`` name, default SIN)

    ``fm_ratio`` and ``fm_index`` are shared blocks nested in every voice's FM
    node, so each is ONE write that reaches every sounding note -- including
    ones already pressed -- at any polyphony. ``fm_index`` of 0 builds no
    per-voice node at all, so a patch without FM costs exactly what a plain
    ``Synth`` voice costs.
    """

    _PARAMS = Synth._PARAMS + ("wave", "fm_ratio", "fm_index", "fm_wave")

    # class attrs: base __init__ builds its graph before this subclass has run
    # any setup of its own, so a patch-less FMSynth(engine) still plays
    _wave_name = "SAW"
    _fm_wave_name = "SIN"
    _fm_wave = None

    def __init__(self, synthesizer, patch=None):
        # Shared FM blocks are created HERE, before super().__init__() runs
        # its load_patch() -> _recompile(): they must exist by then, and must
        # never be replaced -- sounding voices keep references across loads.
        self._fm_ratio_blk = scalar_block(1.0)
        self._fm_index_blk = scalar_block(0.0)
        super().__init__(synthesizer, patch)

    def _recompile(self):
        super()._recompile()
        p = self.patch
        self._wave_name = p.wave
        get_wave_2x(self._wave_name)  # warm the carrier cache; note-on only slices
        self._fm_ratio_blk.a = p.fm_ratio
        self._fm_index_blk.a = p.fm_index
        self._fm_wave_name = p.fm_wave
        self._fm_wave = get_wave(self._fm_wave_name, size=FM_WAVE_SIZE)

    def _decompile(self):
        super()._decompile()
        p = self.patch
        p.wave = self._wave_name
        p.fm_ratio = self._fm_ratio_blk.a
        p.fm_index = self._fm_index_blk.a
        p.fm_wave = self._fm_wave_name

    def _make_fm_modulator(self, carrier_hz):
        """This voice's audio-rate modulator, riding on note.bend.

        Per voice: the rate Math bakes in this note's carrier frequency, so
        it cannot be shared -- but the ratio and index nested inside it ARE
        the shared blocks, so both knobs stay one write and stay live for a
        note that is already sounding.
        """
        return synthio.LFO(
            waveform=self._fm_wave,
            rate=product(carrier_hz, self._fm_ratio_blk),
            scale=self._fm_index_blk,
        )

    def _make_notes(self, midi_note, velocity):
        f = synthio.midi_to_hz(midi_note)
        bend = self._bend_cur
        if self._fm_index_blk.a:
            bend = sum3(bend, self._make_fm_modulator(f))
        # fmt: off
        return (synthio.Note(f, waveform=random_phase_wave(self._wave_name),
                             envelope=self._env, amplitude=velocity / 127,
                             filter=self._make_filter(), bend=bend),)
        # fmt: on

    # --- live parameters ------------------------------------------------
    # Every setter writes live state ONLY; the patch is not touched until
    # save_patch(). fm_ratio and fm_index are each one write into a shared
    # block, O(1) in polyphony, reaching voices already sounding.

    @property
    def wave(self):
        return self._wave_name

    @wave.setter
    def wave(self, v):
        self._wave_name = v
        get_wave_2x(v)  # O(1); warms the cache for the next note-on

    @property
    def fm_ratio(self):
        return self._fm_ratio_blk.a

    @fm_ratio.setter
    def fm_ratio(self, v):
        self._fm_ratio_blk.a = v  # one write, reaches every sounding voice

    @property
    def fm_index(self):
        return self._fm_index_blk.a

    @fm_index.setter
    def fm_index(self, v):
        # One write into the shared block every voice's LFO scale is nested
        # on. Note: if index was 0 at note-on no LFO was built for that
        # voice, so raising it from 0 only affects new notes -- the same
        # rule as fenv_amount.
        self._fm_index_blk.a = v

    @property
    def fm_wave(self):
        return self._fm_wave_name

    @fm_wave.setter
    def fm_wave(self, v):
        self._fm_wave_name = v
        self._fm_wave = get_wave(v, size=FM_WAVE_SIZE)  # next note-on uses it
        self._fm_wave = get_wave(v, size=FM_WAVE_SIZE)  # next note-on uses it
