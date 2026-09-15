# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# audio_fx.py -- a generic post-synth effects chain, plus a factory for the
# one effect that needs synth-specific knowledge: extra filter stages that
# track the synth's own cutoff and resonance.
#
# EffectsChain itself never imports audiofilters/audiodelays: it only calls
# `.play(source)` on whatever effect objects it is handed, so it loads fine
# where those modules don't exist. Only tracking_filter(), and whatever
# Distortion/Echo a caller constructs, needs them.
#
# A synthio.Note takes ONE Biquad, so 12 dB/octave is all a voice can do.
# Steeper means cascading more biquads downstream, and those need somewhere
# stable to point their `frequency`: Synth rebuilds the voice's cutoff node
# at every note-on, and it freezes once the Note is freed. BasslineSynth is
# mono, so it keeps ONE Biquad over one stable cutoff node; copy
# `synth.filter`'s frequency and you track it for good. Slope is
# 12*(stages+1). (A 303 is usually called ~18 dB/oct, which cascaded 2-pole
# sections cannot make at all.)
#
# Q tracks on every stage, and automatically: `src.Q` is the synth's live
# `filt_q` block, the same object the voice's own Biquad reads, so wiring an
# extra stage's Q to it needs no propagation code.
#
# Identical resonant sections stacked this way do pile up gain at the cutoff,
# each stage adding its own peak on top of the last. At a squelchy filt_q
# that is real headroom to watch, and also most of why a cascaded resonant
# filter reads as more aggressive than a single one. tracking_filter()'s
# `spread` is the lever: offsetting the stages spreads those peaks out the
# way a real ladder's mismatched poles do.

import synthio

from .blocks import product

try:
    import audiofilters
except ImportError:  # not in every CircuitPython build
    audiofilters = None


class EffectsChain:
    """A synth's output, plus an ordered chain of playback effects it runs
    through. Add, insert, or remove any ``audiofilters``/``audiodelays``
    effect object; the chain keeps every effect's ``.play(source)`` pointed
    at whatever now precedes it::

        fx = EffectsChain(synth)
        fx.add(tracking_filter(synth, stages=1))
        fx.add(audiofilters.Distortion(mix=0.0, drive=0.5, ...))
        mixer.voice[0].play(fx.output)

    ``output`` is always the tail: the synth itself when the chain is
    empty. Building an ``EffectsChain`` touches no effects module at all,
    so it loads fine even where ``audiofilters`` doesn't exist; only the
    effects you add to it need it.

    A mixer voice holds whatever object ``output`` *was* at the time you
    called ``play()``: it has no way to notice ``output`` changing
    identity later. Any ``add``/``insert``/``remove`` that changes the
    tail (an ``add``, an ``insert`` at the end, or removing the current
    tail) needs ``mixer.voice[0].play(fx.output)`` called again to reach
    the speaker; an insert/remove in the *middle* rewires in place and
    needs nothing further, since the tail object itself doesn't change.
    """

    def __init__(self, synth):
        self.synth = synth
        self._effects = []

    @property
    def effects(self):
        """The chain in order, outermost effect last. Read-only: go
        through :meth:`add`/:meth:`insert`/:meth:`remove` so an effect's
        ``.play()`` source can never drift out of sync with this list."""
        return tuple(self._effects)

    @property
    def output(self):
        """The tail of the chain: what a mixer voice should play."""
        return self._effects[-1] if self._effects else self.synth.synthio

    def add(self, effect):
        """Append ``effect`` to the end of the chain and return it."""
        effect.play(self.output)
        self._effects.append(effect)
        return effect

    def insert(self, index, effect):
        """Insert ``effect`` at ``index`` (Python list semantics, negative
        included), rewiring everything from there on."""
        self._effects.insert(index, effect)
        self._rewire(self._effects.index(effect))
        return effect

    def remove(self, effect):
        """Take ``effect`` out of the chain and rewire around the gap."""
        index = self._effects.index(effect)
        del self._effects[index]
        self._rewire(index)

    def _rewire(self, from_index):
        src = self._effects[from_index - 1] if from_index > 0 else self.synth.synthio
        for stage in self._effects[from_index:]:
            stage.play(src)
            src = stage


def tracking_filter(synth, stages=1, buffer_size=1024, mix=1.0, hpf_f=None, spread=1.0):
    """Build one ``audiofilters.Filter`` holding ``stages`` extra Biquads
    that track ``synth.filter``'s cutoff AND resonance; see the module
    comment for why that's automatic once they share the live blocks.
    ``stages`` extra 12 dB/octave sections plus the synth's own give
    ``12*(stages+1)`` overall.

    ``spread`` offsets each stage's cutoff above the last by that ratio,
    approximating a real ladder's wide pole spread instead of stacking
    identical resonant peaks on one frequency; 1.0 shares one node and
    allocates nothing.

    ``hpf_f`` adds a fixed high-pass section at that frequency in Hz, in
    the SAME biquad tuple, so it costs no extra buffer and no extra pass.
    It is a plain number rather than a shared block on purpose: it must
    not follow the cutoff. A TB-303's thin bass comes from small coupling
    capacitors between the filter and the VCA, which sit at one corner
    whatever the filter is doing. ``stages=0`` is legal with it, for a
    high-pass alone.

    Raises ``ImportError`` if this build has no ``audiofilters``,
    ``ValueError`` if ``stages < 1`` without an ``hpf_f``, or if tracking
    stages were asked for and ``synth`` has no filter to track (either a
    poly synth, which has no ``.filter`` at all, or a mono one built with
    ``filt_type=None``).
    """
    if audiofilters is None:
        raise ImportError("audiofilters is not in this CircuitPython build")
    if stages < 1 and not hpf_f:
        raise ValueError("stages must be >= 1")
    src = getattr(synth, "filter", None)
    if stages >= 1 and src is None:
        raise ValueError("synth has no filter to track (mono-only, and filt_type must be set)")
    synthesizer = synth.synthio
    # Copies sharing src's frequency AND Q blocks, both live, so both track
    # the synth (sweep, accent, a filt_q turn) with nothing to keep in sync
    # by hand. One Filter holding a tuple, not a Filter each: `filter` runs
    # the sample through them in order, saving a buffer and a pass per stage.
    # `spread` offsets each stage above the last by that ratio. Identical
    # cascaded sections pile their resonant peaks on one frequency; real
    # ladder filters do not, and the TB-303's least of all, its bottom
    # ladder capacitor being half the value of the other three. Mismatched
    # stages approximate that wider pole spread and take the edge off the
    # ringing. 1.0, the default, shares one node and allocates nothing.
    #
    # An offset node needs NO rooting: measured on rp2040, a Math reachable
    # only through a Biquad inside an audiofilters.Filter tracks the sweep
    # exactly, while an otherwise identical one reachable from nothing at
    # all reads 0.0 forever. Nesting counts across the audiofilters
    # boundary, so `synthesizer.blocks` stays out of this.
    sections = []
    ratio = 1.0
    for _ in range(stages):
        freq = src.frequency if ratio == 1.0 else product(src.frequency, ratio)
        sections.append(synthio.Biquad(src.mode, frequency=freq, Q=src.Q))
        ratio *= spread
    biquads = tuple(sections)
    if hpf_f:
        # last, so it sheds low end from everything ahead of it
        biquads += (synthio.Biquad(synthio.FilterMode.HIGH_PASS, frequency=hpf_f, Q=0.707),)
    return audiofilters.Filter(
        filter=biquads,
        mix=mix,
        sample_rate=synthesizer.sample_rate,
        channel_count=synthesizer.channel_count,
        buffer_size=buffer_size,
    )


def set_drive(distortion, amount):
    """Set a ``Distortion`` effect's drive, 0..1, through ``pre_gain`` and
    ``post_gain`` (LOFI mode's own ``drive`` parameter does not do what
    its name suggests); ``post_gain`` pulls back the level ``pre_gain``
    adds."""
    distortion.pre_gain = amount * 50.0
    distortion.post_gain = amount * -25.0


def sync_delay(echo, bpm, steps=4, steps_per_beat=4):
    """Set an ``Echo`` effect's ``delay_ms`` to ``steps`` sequencer steps
    at ``bpm``: a tempo-synced delay is most of what makes a repeating
    line sit right."""
    echo.delay_ms = (60_000.0 / bpm / steps_per_beat) * steps
