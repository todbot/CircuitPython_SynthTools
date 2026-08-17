# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""EffectsChain's generic add/insert/remove wiring, tracking_filter()'s
cutoff/resonance tracking, and the set_drive()/sync_delay() helpers.

The interesting claim for the chain itself is that add/insert/remove keep
every effect's `.play(source)` pointed at whatever now precedes it, and
that EffectsChain needs no audiofilters import at all to do that -- only
building a specific effect (tracking_filter, or a caller's own Distortion/
Echo) does.

The interesting claim for tracking_filter() is that a downstream Biquad
can hold a PERMANENT reference to the synth's cutoff. Synth builds a
fresh cutoff node at every note-on, so the naive version goes stale after
one note and then freezes once its Note is freed. BasslineSynth.filter is
the mono answer: one voice, one cutoff, built once and re-aimed.

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

import audiodelays  # noqa: E402
import audiofilters  # noqa: E402
import synthio  # noqa: E402
from synthtools import BasslineSynth, Patch, SubtractiveSynth  # noqa: E402
from synthtools.audio_fx import EffectsChain, set_drive, sync_delay, tracking_filter  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


def make(**kw):
    kw.setdefault("wave", "SAW")
    kw.setdefault("filt_f", 1200)
    kw.setdefault("envmod", 0.75)
    return BasslineSynth(synthio.Synthesizer(), Patch(**kw))


class _Stage:
    """A stand-in effect: all EffectsChain needs is `.play(source)`."""

    def __init__(self, name):
        self.name = name
        self.source = None

    def play(self, source):
        self.source = source

    def __repr__(self):
        return "Stage(%s)" % self.name


# --- the chain itself: add / insert / remove, no audiofilters needed -----

syn0 = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0))
fx = EffectsChain(syn0)
ck(fx.output is syn0.synthio, "an empty chain's output must be the synth itself")
ck(fx.effects == (), "an empty chain must report no stages")

a, b, c = _Stage("a"), _Stage("b"), _Stage("c")
fx.add(a)
ck(a.source is syn0.synthio, "the first stage must be wired straight to the synth")
ck(fx.output is a, "output must track the newly added tail")

fx.add(b)
ck(b.source is a, "the second stage must be wired to the first")
ck(fx.output is b, "output must move to the new tail")
ck(fx.effects == (a, b), "stages must report insertion order")

fx.insert(1, c)
ck(fx.effects == (a, c, b), "insert must land at the given index")
ck(c.source is a, "an inserted stage must read from what now precedes it")
ck(b.source is c, "insert must rewire everything AFTER the inserted stage")
ck(fx.output is b, "output must still be the true tail after an insert in the middle")

fx.insert(0, _Stage("head"))
head = fx.effects[0]
ck(head.source is syn0.synthio, "inserting at 0 must read straight from the synth")
ck(a.source is head, "insert at 0 must rewire the old first stage to the new one")

fx.remove(c)
ck(fx.effects == (head, a, b), "remove must drop exactly the given effect")
ck(b.source is a, "remove must rewire around the gap it left")

fx.remove(head)
ck(fx.effects == (a, b), "removing the head must rewire the new head to the synth")
ck(a.source is syn0.synthio, "...specifically, straight back to the synth")

# insert() must normalize the index like list.insert does -- a raw pass-
# through of a negative or out-of-range index into _rewire() would either
# rewire the wrong stage or IndexError after the list was already mutated
fx.insert(-1, _Stage("before-tail"))
before_tail = fx.effects[-2]
ck(before_tail.name == "before-tail", "insert(-1, ...) must land just before the tail")
ck(before_tail.source is a, "the inserted stage must read from what precedes it")
ck(b.source is before_tail, "insert(-1, ...) must rewire the true tail to the inserted stage")
fx.remove(before_tail)

fx.insert(99, _Stage("past-end"))
ck(fx.effects[-1].name == "past-end", "insert() past the end must behave like append")
ck(fx.effects[-1].source is fx.effects[-2], "...and still be wired to the true previous tail")
fx.remove(fx.effects[-1])

# EffectsChain must not need audiofilters at all -- only building a
# specific effect (tracking_filter, or a caller's own Distortion/Echo)
# should. Prove it by knocking the module out from under audio_fx and
# confirming the chain still works with plain stand-in effects.
import synthtools.audio_fx as _fx_mod  # noqa: E402

_saved, _fx_mod.audiofilters = _fx_mod.audiofilters, None
no_fx = EffectsChain(SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0)))
no_fx.add(_Stage("still works"))
ck(no_fx.output.name == "still works",
   "EffectsChain must build and wire fine with audiofilters entirely absent")
_fx_mod.audiofilters = _saved

# --- tracking_filter(): the cutoff a downstream filter can hold onto -----

syn = make(filt_q=1.8, fenv_attack=0.09)
bq = syn.filter
cb = bq.frequency
ck(cb in syn.synthio.blocks,
   "the cutoff node must be ROOTED, or it freezes between notes and the fx "
   "filter sits at whatever the last note left behind")

tf = tracking_filter(syn, stages=2)
ck(isinstance(tf.filter, tuple) and len(tf.filter) == 2,
   "the stages must go into ONE Filter as a tuple of biquads -- a Filter "
   "each would cost an extra buffer and pass per stage")
ck(all(b.frequency is cb for b in tf.filter), "every stage must track the synth's cutoff")
ck(all(b.Q is syn._filt_q_blk for b in tf.filter),
   "every stage must ALSO track the synth's resonance -- the original this "
   "was ported from pushes Q into every filter by hand on a knob turn; "
   "here it must be automatic, because they share the live block")
syn.filt_q = 2.4
ck(all(b.Q.a == 2.4 for b in tf.filter),
   "a filt_q knob turn must reach every stage with no propagation code, "
   "since Q is a shared block, not a copied number")

seen = []
for n in (36, 38, 40):
    syn.note_on_step(n)
    seen.append(syn.voices[n][0].filter)
    syn.note_off(n)
ck(all(f is bq for f in seen),
   "mono reuses ONE Biquad for every note rather than allocating a pair "
   "each time -- the same arrangement as the synth this was ported from")

# it must carry the whole bus, not just filt_f
syn.note_on_step(36)
env = syn._fenvs[36]
env.c.phase = 0.0
top = cb.value
env.c.phase = 1.0
bottom = cb.value
ck(abs(top - 1200.0) < 1e-6, "cutoff must start the sweep at filt_f, got %r" % top)
ck(abs(bottom - 300.0) < 1e-6,
   "cutoff must FOLLOW the envelope down -- that is the whole point of "
   "tracking, got %r" % bottom)
syn.note_off(36)

# accent rides it too
syn.note_on_step(38, accent=True)
ck(cb.value > 1200.0, "an accented step must lift cutoff, got %r" % cb.value)
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
try:
    tracking_filter(poly, stages=1)
    ck(False, "a poly synth has no .filter -- tracking_filter must refuse it")
except ValueError:
    pass

try:
    tracking_filter(make(filt_type=None), stages=1)
    ck(False, "filt_type=None must be refused rather than tracking nothing")
except ValueError:
    pass

try:
    tracking_filter(make(), stages=0)
    ck(False, "stages < 1 must be refused -- an empty chain already needs no filter")
except ValueError:
    pass

# --- wiring a real tracking_filter into a chain ---------------------------

full = EffectsChain(make(filt_f=1200))
tf2 = full.add(tracking_filter(full.synth, stages=1))
ck(tf2.source is full.synth.synthio, "the filter's input must be the Synthesizer")
ck(full.output is tf2, "with one stage the filter IS the output")

dist = full.add(audiofilters.Distortion(mix=0.0, drive=0.5, pre_gain=0, post_gain=0))
ck(dist.source is tf2, "distortion must follow the filter it was added after")
ck(full.output is dist, "output must move to the newly added tail")

# --- set_drive() / sync_delay(): the two bits of non-obvious math --------

set_drive(dist, 0.5)
ck(dist.pre_gain == 25.0 and dist.post_gain == -12.5,
   "set_drive must round-trip amount through pre_gain/post_gain")

echo = full.add(audiodelays.Echo(mix=0.0, delay_ms=0, max_delay_ms=500, decay=0.1))
sync_delay(echo, 130, steps=4)
ck(abs(echo.delay_ms - 4 * (60_000.0 / 130 / 4)) < 1e-6,
   "sync_delay must land on the step grid, got %r" % echo.delay_ms)

# --- BasslineSynth's OWNED effects chain ----------------------------------

default = make()
ck(default.output is default.synthio,
   "the default patch must build nothing -- no extra filter, no "
   "distortion, no echo -- and cost nothing")

stages_syn = make(fx_filter_stages=2, fx_filter_mix=0.6)
ck(isinstance(stages_syn.fx.effects[0].filter, tuple)
   and len(stages_syn.fx.effects[0].filter) == 2,
   "fx_filter_stages must build a tracking_filter() with that many stages")
ck(stages_syn.fx.effects[0].filter[0].frequency is stages_syn.filter.frequency,
   "the owned stage must track the synth's own cutoff, same as the free function")
ck(stages_syn.fx.effects[0].mix == 0.6, "fx_filter_mix must reach the built stage")

no_filter = make(filt_type=None, fx_filter_stages=2)
ck(no_filter.output is no_filter.synthio,
   "fx_filter_stages > 0 with filt_type=None must build nothing and raise "
   "nothing -- there is no cutoff to track, same as _voice_cutoff()'s own "
   "silent no-op")

dist_syn = make(fx_distortion_on=True, fx_drive=0.5, fx_drive_mix=0.4)
ck(len(dist_syn.fx.effects) == 1 and isinstance(dist_syn.fx.effects[0], audiofilters.Distortion),
   "fx_distortion_on must build exactly one Distortion")
ck(dist_syn.fx.effects[0].pre_gain == 25.0 and dist_syn.fx.effects[0].post_gain == -12.5,
   "fx_drive must reach the built Distortion through set_drive()")
ck(dist_syn.fx.effects[0].mix == 0.4, "fx_drive_mix must reach the built Distortion")

echo_syn = make(fx_echo_on=True, fx_delay_ms=250, fx_delay_mix=0.4, fx_delay_decay=0.2)
ck(len(echo_syn.fx.effects) == 1 and isinstance(echo_syn.fx.effects[0], audiodelays.Echo),
   "fx_echo_on must build exactly one Echo")
ck(echo_syn.fx.effects[0].delay_ms == 250 and echo_syn.fx.effects[0].mix == 0.4
   and echo_syn.fx.effects[0].decay == 0.2,
   "fx_delay_ms/fx_delay_mix/fx_delay_decay must all reach the built Echo")

full_syn = make(fx_filter_stages=1, fx_distortion_on=True, fx_echo_on=True)
kinds = [type(e).__name__ for e in full_syn.fx.effects]
ck(kinds == ["Filter", "Distortion", "Echo"],
   "the owned chain's order must be fixed: filter, then distortion, then echo")

# --- live knobs reach an already-built chain without disturbing identity --

live_syn = make(fx_distortion_on=True)
chain_before = live_syn.fx
dist_before = live_syn.fx.effects[0]
live_syn.fx_drive = 0.9
live_syn.fx_drive_mix = 0.7
ck(live_syn.fx is chain_before and live_syn.fx.effects[0] is dist_before,
   "a LIVE knob must never rebuild the chain -- only structural fields do")
ck(dist_before.mix == 0.7, "fx_drive_mix must reach the object already playing")

# --- structural changes invalidate the CHAIN, but leave the still-playing
# objects alone and still live-updatable, until the caller rebuilds -------

struct_syn = make(fx_distortion_on=True, fx_drive=0.2)
old_chain = struct_syn.fx
old_dist = struct_syn.fx.effects[0]
struct_syn.fx_echo_on = True  # a structural change
ck(struct_syn._fx is None,
   "a structural setter must invalidate self._fx so the next access rebuilds")
ck(struct_syn._fx_dist is old_dist,
   "...but must NOT drop the still-playing Distortion object itself")
struct_syn.fx_drive = 0.8  # a live knob, written before the rebuild happens
ck(old_dist.pre_gain == 40.0,
   "a live knob must still reach the OLD, still-playing object even mid-"
   "transition -- it is what the mixer is actually sounding")
new_chain = struct_syn.fx  # forces the rebuild
ck(new_chain is not old_chain and len(new_chain.effects) == 2,
   "the rebuild must produce a NEW chain reflecting the structural change")

# --- a filt_type change must invalidate the owned chain too --------------
# tracking_filter() copies the voice Biquad's `mode` as a plain VALUE, not
# a live block like frequency/Q -- so left alone, a filt_type change would
# leave the voice on the new mode and an owned stage stuck on the old one.

mode_syn = make(filt_type="LPF", fx_filter_stages=1)
mode_chain = mode_syn.fx
old_stage_mode = mode_syn.fx.effects[0].filter[0].mode
mode_syn.filt_type = "HPF"
ck(mode_syn._fx is None,
   "a real filt_type change must invalidate the owned chain -- the owned "
   "stages copied the OLD mode as a value and have no way to track a new one")
ck(mode_syn.fx is not mode_chain, "...so the next access must rebuild it")
ck(mode_syn.fx.effects[0].filter[0].mode == mode_syn.filter.mode
   and mode_syn.fx.effects[0].filter[0].mode != old_stage_mode,
   "the rebuilt stage must match the VOICE's new mode, not the stale one")

same_mode_syn = make(filt_type="LPF", fx_filter_stages=1)
same_mode_chain = same_mode_syn.fx
same_mode_syn.filt_type = "LPF"  # same value, not a real change
ck(same_mode_syn._fx is same_mode_chain,
   "setting filt_type to what it already was must NOT invalidate the chain")

# --- load_patch() must not silently freeze a chain that hasn't changed shape

same_shape = make(fx_distortion_on=True, fx_drive=0.1)
chain_id = same_shape.fx
dist_id = same_shape.fx.effects[0]
same_shape.load_patch(Patch(wave="SAW", filt_f=1200, envmod=0.75,
                             fx_distortion_on=True, fx_drive=0.6))
ck(same_shape._fx is chain_id and same_shape.fx.effects[0] is dist_id,
   "loading a patch with the SAME fx shape must reach the live effect, "
   "not rebuild -- the whole point of _recompile() comparing before "
   "invalidating")
ck(dist_id.pre_gain == 30.0, "...and the new drive value must actually be there")

diff_shape = make(fx_distortion_on=True)
chain_id2 = diff_shape.fx
diff_shape.load_patch(Patch(wave="SAW", filt_f=1200, envmod=0.75, fx_echo_on=True))
ck(diff_shape._fx is None,
   "loading a patch with a DIFFERENT fx shape must invalidate the chain")

# --- _build_fx() is atomic: a failure partway must not wedge self._fx ----

import synthtools.bassline_synth as _bl_mod  # noqa: E402

atomic_syn = make(fx_distortion_on=True, fx_echo_on=True)
_saved_ad, _bl_mod.audiodelays = _bl_mod.audiodelays, None
try:
    atomic_syn.output
    ck(False, "audiodelays missing + fx_echo_on=True must raise ImportError")
except ImportError:
    pass
ck(atomic_syn._fx is None,
   "a failed build must leave self._fx None, not half-built, so a later "
   "successful build can still happen")
_bl_mod.audiodelays = _saved_ad
ck(len(atomic_syn.fx.effects) == 2,
   "once audiodelays is back, a retry must build the full chain cleanly")

# --- patch save/load round-trips all nine fields, and set_param() ---------

rt = make(fx_filter_stages=3, fx_filter_mix=0.5, fx_distortion_on=True,
          fx_drive=0.3, fx_drive_mix=0.2, fx_echo_on=True, fx_delay_ms=222,
          fx_delay_mix=0.1, fx_delay_decay=0.4)
saved = rt.save_patch()
ck(saved.fx_filter_stages == 3 and saved.fx_filter_mix == 0.5
   and saved.fx_distortion_on is True and saved.fx_drive == 0.3
   and saved.fx_drive_mix == 0.2 and saved.fx_echo_on is True
   and saved.fx_delay_ms == 222 and saved.fx_delay_mix == 0.1
   and saved.fx_delay_decay == 0.4,
   "save_patch() must round-trip all nine fx_* fields")

pset = make()
pset.set_param("fx_drive_mix", 0.55)
ck(pset.fx_drive_mix == 0.55, "set_param must reach a LIVE fx_* field")
try:
    pset.set_param("fx_distortion_on", True)
    ck(False, "set_param must refuse a STRUCTURAL fx_* field -- a MIDI CC "
              "silently muting the fx chain (nothing re-play()s the mixer) "
              "is worse than just not exposing the switch there")
except KeyError:
    pass

if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_audio_fx: all checks passed")
