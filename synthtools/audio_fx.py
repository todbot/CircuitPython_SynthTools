# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# audio_fx.py - post-synth effects: extra filter stages that track the
# synth's cutoff, plus optional distortion and echo.
#
# A synthio.Note takes ONE Biquad, so 12 dB/octave is all a voice can do.
# Steeper means cascading more biquads downstream, and those need
# somewhere stable to point their `frequency`: Synth rebuilds the voice's
# cutoff node at every note-on, and it freezes once the Note is freed.
# BasslineSynth is mono, so it keeps ONE Biquad over one stable cutoff
# node -- copy `synth.filter`'s frequency and you track it for good.
#
# Slope: every Biquad is 12 dB/oct including the synth's own, so `stages`
# gives 12*(stages+1). Default 1 = 24 dB/oct. (A 303 is usually called
# ~18 dB/oct, which cascaded 2-pole sections cannot make at all.)
#
# Q tracks too, on every stage, matching the synth this was ported from
# (its `resonance` setter pushes the same Q into the voice filter and both
# extra ones by hand). Here it is automatic: `src.Q` is the synth's live
# `filt_q` block, the same object the voice's own Biquad reads, so wiring
# an extra stage's Q to it needs no propagation code at all -- one knob
# turn reaches every stage the instant it reaches the voice.
#
# Identical resonant sections stacked like this do pile up gain at the
# cutoff faster than one section alone -- each stage adds its own peak on
# top of the last. At a squelchy filt_q that is real headroom to watch for;
# it is also most of why a cascaded resonant filter reads as more
# aggressive than a single one, which is the point here.

import synthio

try:
    import audiodelays
    import audiofilters
except ImportError:  # not in every CircuitPython build
    audiodelays = None
    audiofilters = None


class EffectsChain:
    """Post-synth effects: filter stages tracking the synth's cutoff, plus
    optional distortion and echo. Hand ``output`` to a mixer voice::

        fx = EffectsChain(BasslineSynth(engine, patch), stages=1)
        mixer.voice[0].play(fx.output)

    ``stages`` extra 12 dB/octave sections give 12*(stages+1) overall,
    counting the synth's own, so the default is 24 dB/octave. They track
    the synth's cutoff AND resonance -- see the module comment.

    ``distortion`` and ``echo`` are opt-in; each costs a buffer and real
    CPU, and distortion is reportedly too slow to use on an rp2040.

    Needs a CircuitPython build with ``audiofilters`` (and ``audiodelays``
    for echo). Raises ImportError when constructed rather than when
    imported, so the rest of the package still loads without them.
    """

    def __init__(
        self,
        synth,
        stages=1,
        distortion=False,
        echo=False,
        buffer_size=1024,
        delay_ms=500,
        max_delay_ms=500,
        decay=0.1,
    ):
        if audiofilters is None:
            raise ImportError(
                "audiofilters is not in this CircuitPython build; "
                "EffectsChain needs it (audiodelays too, for echo)"
            )
        self.synth = synth
        synthesizer = synth.synthio
        cfg = {
            "sample_rate": synthesizer.sample_rate,
            "channel_count": synthesizer.channel_count,
            "buffer_size": buffer_size,
        }

        stages = max(0, int(stages))
        self.filter = None
        if stages:
            src = synth.filter  # the synth's own Biquad, built once
            if src is None:
                raise ValueError("synth has no filter (filt_type is None) to track")
            # Copies sharing src's frequency AND Q blocks -- both live, so
            # both track the synth (sweep, accent, and a filt_q knob turn)
            # with nothing to keep in sync by hand. One Filter holding a
            # tuple, not a Filter each: `filter` runs the sample through
            # them in order, saving a buffer and a pass per stage.
            biquads = tuple(
                synthio.Biquad(src.mode, frequency=src.frequency, Q=src.Q) for _ in range(stages)
            )
            self.filter = audiofilters.Filter(filter=biquads, mix=1.0, **cfg)

        self.distortion = None
        if distortion:
            # fmt: off
            self.distortion = audiofilters.Distortion(
                mode=audiofilters.DistortionMode.LOFI, mix=0.0, drive=0.5,
                soft_clip=True, pre_gain=0, post_gain=0, **cfg)
            # fmt: on

        self.echo = None
        if echo:
            if audiodelays is None:
                raise ImportError("audiodelays is not in this CircuitPython build")
            # fmt: off
            self.echo = audiodelays.Echo(
                mix=0.0, max_delay_ms=max_delay_ms, delay_ms=delay_ms,
                decay=decay, freq_shift=False, **cfg)
            # fmt: on

        # wire whatever exists, in order, and remember the tail
        self.output = synthesizer
        for fx in (self.filter, self.distortion, self.echo):
            if fx is not None:
                fx.play(self.output)
                self.output = fx

    # --- knobs, all no-ops when the effect was not built ----------------

    @property
    def filter_mix(self):
        """Dry/wet for the extra filter stages. 1.0 = fully filtered."""
        return self.filter.mix if self.filter is not None else 0.0

    @filter_mix.setter
    def filter_mix(self, v):
        if self.filter is not None:
            self.filter.mix = v

    @property
    def drive(self):
        """Distortion amount, 0..1. Driven through pre_gain, not the
        `drive` parameter, which does not do what its name suggests in LOFI
        mode; post_gain pulls back the level pre_gain adds."""
        return self.distortion.pre_gain / 50.0 if self.distortion is not None else 0.0

    @drive.setter
    def drive(self, v):
        if self.distortion is not None:
            self.distortion.pre_gain = v * 50.0
            self.distortion.post_gain = v * -25.0

    @property
    def drive_mix(self):
        return self.distortion.mix if self.distortion is not None else 0.0

    @drive_mix.setter
    def drive_mix(self, v):
        if self.distortion is not None:
            self.distortion.mix = v

    @property
    def delay_mix(self):
        return self.echo.mix if self.echo is not None else 0.0

    @delay_mix.setter
    def delay_mix(self, v):
        if self.echo is not None:
            self.echo.mix = v

    @property
    def delay_ms(self):
        return self.echo.delay_ms if self.echo is not None else 0.0

    @delay_ms.setter
    def delay_ms(self, v):
        if self.echo is not None:
            self.echo.delay_ms = v

    def delay_sync(self, bpm, steps=4, steps_per_beat=4):
        """Set the echo time to ``steps`` sequencer steps at ``bpm``. A
        tempo-synced delay is most of what makes an acid line sit right."""
        self.delay_ms = (60_000.0 / bpm / steps_per_beat) * steps
