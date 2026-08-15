# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""EffectsChain wiring, and the cutoff tracking it depends on.

The interesting claim is that a downstream Biquad can hold a PERMANENT
reference to the synth's cutoff. Synth builds a fresh cutoff node at every
note-on, so the naive version goes stale after one note and then freezes
once its Note is freed. Synth.cutoff_block is the mono answer: one voice,
one cutoff, built once and re-aimed.

The other claim is that extra stages are FLAT. Cascading identical
resonant sections piles up N times the resonance rather than steepening
the slope, so resonance stays on the synth's own per-note Biquad.

No DSP here: stubs cannot tell you what a 24 dB/octave slope sounds like,
only that the graph is wired to produce one. Slope and resonance are
on-device questions.

    python3 tests/test_audio_fx.py
    micropython tests/test_audio_fx.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/stubs_fx")  # BEFORE synthtools is imported
sys.path.insert(0, _D + "/stubs")
sys.path.insert(0, _D + "/..")

import audiofilters  # noqa: E402
import synthio  # noqa: E402
from synthtools import BasslineSynth, Patch, SubtractiveSynth  # noqa: E402
from synthtools.audio_fx import EffectsChain  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


def make(**kw):
    kw.setdefault("wave", "SAW")
    kw.setdefault("filt_f", 1200)
    kw.setdefault("envmod", 0.75)
    return BasslineSynth(synthio.Synthesizer(), Patch(**kw))


# --- the cutoff a downstream filter can actually hold on to --------------

syn = make(filt_q=1.8, fenv_attack=0.09)
bq = syn.filter
cb = bq.frequency
ck(cb in syn.synthio.blocks,
   "the cutoff node must be ROOTED, or it freezes between notes and the fx "
   "filter sits at whatever the last note left behind")
ck(bq.Q is syn._filt_q_blk, "the shared filter must read the live resonance block")

seen = []
for n in (36, 38, 40):
    syn.note_on_step(n)
    seen.append(syn.voices[n][0].filter)
    syn.note_off(n)
ck(all(f is bq for f in seen),
   "mono reuses ONE Biquad for every note rather than allocating a pair "
   "each time -- the same arrangement as the synth this was ported from")
ck(syn.filter is bq and syn.filter.frequency is cb,
   "filter and its cutoff node must survive note after note")

# it must carry the whole bus, not just filt_f
syn.note_on_step(36)
env = syn._fenvs[36]
env.c.phase = 0.0
top = cb.value
env.c.phase = 1.0
bottom = cb.value
ck(abs(top - 1200.0) < 1e-6, "cutoff_block must start the sweep at filt_f, got %r" % top)
ck(abs(bottom - 300.0) < 1e-6,
   "cutoff_block must FOLLOW the envelope down -- that is the whole point of "
   "tracking, got %r" % bottom)
syn.note_off(36)

# accent rides it too
syn.note_on_step(38, accent=True)
ck(cb.value > 1200.0, "an accented step must lift cutoff_block, got %r" % cb.value)
syn.note_off(38)

# identity must NOT depend on envmod: a chain built while envmod is 0 has
# to keep working when it is turned up
zero = make(envmod=0.0)
before = zero.filter.frequency
zero.note_on_step(36)
ck(zero.voices[36][0].filter.frequency is before,
   "the cutoff node must be the voice's even at envmod=0, or turning "
   "envmod up silently orphans anything already tracking it")
zero.envmod = 0.8
zero.note_off(36)
zero.note_on_step(38)
ck(zero.filter.frequency is before and zero.voices[38][0].filter.frequency is before,
   "raising envmod must not replace the tracked node")

# poly is untouched: Synth still rebuilds a cutoff node per voice, and
# gained no tracking API for a mono-only, effects-only concern
poly = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0))
ck(not hasattr(poly, "filter"), "the shared filter belongs to BasslineSynth, not Synth")
ck(not hasattr(poly, "cutoff_block"), "Synth must carry no cutoff-tracking API")

# --- the chain ------------------------------------------------------------

fx = EffectsChain(syn, stages=2)
ck(isinstance(fx.filter.filter, tuple) and len(fx.filter.filter) == 2,
   "the stages must go into ONE Filter as a tuple of biquads -- a Filter "
   "each would cost an extra buffer and pass per stage")
ck(all(b.frequency is cb for b in fx.filter.filter),
   "every stage must track the synth's cutoff")
ck(all(b.Q is syn._filt_q_blk for b in fx.filter.filter),
   "every stage must ALSO track the synth's resonance -- the original this "
   "was ported from pushes Q into every filter by hand on a knob turn; "
   "here it must be automatic, because they share the live block")
syn.filt_q = 2.4
ck(all(b.Q.a == 2.4 for b in fx.filter.filter),
   "a filt_q knob turn must reach every stage with no propagation code, "
   "since Q is a shared block, not a copied number")
ck(fx.filter.source is syn.synthio, "the filter's input must be the Synthesizer")
ck(fx.output is fx.filter, "with no other effects the filter IS the output")
ck(fx.distortion is None and fx.echo is None,
   "distortion and echo must be opt-in -- each costs a buffer and real CPU")

# stages=0 is legal: no extra slope, just the synth's own 12 dB/octave
bare = EffectsChain(make(), stages=0)
ck(bare.filter is None and bare.output is bare.synth.synthio,
   "stages=0 must build nothing and pass the synth straight through")

# order: synth -> filter -> distortion -> echo, and output is the tail
full = EffectsChain(make(), stages=1, distortion=True, echo=True)
ck(full.filter.source is full.synth.synthio, "filter takes the synth")
ck(full.distortion.source is full.filter, "distortion follows the filter")
ck(full.echo.source is full.distortion, "echo is last")
ck(full.output is full.echo, "output must be the TAIL of the chain")
ck(full.distortion.mode == audiofilters.DistortionMode.LOFI,
   "LOFI is the mode cheap enough to be usable")
ck(full.drive_mix == 0.0 and full.delay_mix == 0.0,
   "both must arrive silent, so adding them cannot change the sound until asked")

# knobs reach through, and are no-ops when the effect was not built
full.drive = 0.5
ck(full.drive == 0.5, "drive must round-trip through pre_gain")
ck(full.distortion.post_gain < 0, "post_gain must pull back the level pre_gain added")
full.delay_sync(130, steps=4)
ck(abs(full.delay_ms - 4 * (60_000.0 / 130 / 4)) < 1e-6,
   "delay_sync must land on the step grid, got %r" % full.delay_ms)

bare.drive = 0.9
bare.delay_mix = 0.5
ck(bare.drive == 0.0 and bare.delay_mix == 0.0,
   "a knob for an effect that was not built must be a harmless no-op")

# an effect object's truthiness is not ours to assume -- the same rule
# _voice_cutoff states for blocks. A stub with no __bool__/__len__ is
# always truthy, so pin the intent by making one falsy on purpose.
class _Falsy(audiofilters.Filter):
    def __len__(self):
        return 0


probe = EffectsChain(make(), stages=1, distortion=True)
probe.distortion.__class__ = _Falsy
probe.drive_mix = 0.4
ck(probe.drive_mix == 0.4,
   "knobs must test `is not None`, not truthiness -- a falsy-but-present "
   "effect object would silently turn every setter into a no-op")

# stages is clamped rather than trusted
ck(EffectsChain(make(), stages=-1).filter is None, "a negative stages count must mean none")

# a synth with no filter has no cutoff to track
try:
    EffectsChain(make(filt_type=None), stages=1)
    ck(False, "filt_type=None must be refused rather than tracking nothing")
except ValueError:
    pass

if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_audio_fx: all checks passed")
