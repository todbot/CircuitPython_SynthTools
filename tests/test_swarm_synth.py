# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Integration checks for SwarmSynth against the synthio stubs.

Proves the design in swarm_synth.py holds: the swarm spread lives on
note.bend (a BlockInput) rather than note.frequency (a plain float), so
sweeping it reaches every SOUNDING oscillator with ONE write, O(1) in
polyphony. That is the whole reason this is not two lines of
SubtractiveSynth, whose `detune` setter has to loop over live voices.

The three checks that would ship as real bugs if dropped:

  1. the shared fan blocks are rooted in synthesizer.blocks: unrooted,
     they are only reachable through a sounding Note, so the FIRST note-on
     of a fresh synth reads every fan as 0.0 and the swarm sounds in unison
     for one block before snapping apart (the same failure synth.py
     documents measuring as a 0.0 Hz first-note cutoff);
  2. the per-Note bend SUM is built even at swarm_spread 0, or sweeping the
     spread up from nothing under a held drone (the instrument's defining
     gesture) would be next-note-on only;
  3. swarm_count 1 does not divide by zero in the fan coefficient.

No DSP: the stubs do not render audio, so this checks identity, wiring and
block arithmetic only. Whether a swarm SOUNDS right is a hardware question.

    python3 tests/test_swarm_synth.py
    micropython tests/test_swarm_synth.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/stubs")
sys.path.insert(0, _D + "/..")

import synthio  # noqa: E402
from synthtools import Patch, SwarmSynth  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


def close(a, b, eps=1e-9):
    return abs(a - b) < eps


# --- swarm_* are NOT Patch fields: they ride in __dict__ via getattr ------
p = Patch()
ck(not hasattr(p, "swarm_count"),
   "swarm_* must stay OUT of Patch, they are style-specific, read with getattr")
rt = Patch.from_json(Patch(swarm_count=4, swarm_spread=0.05, swarm_drift=0.01).to_json())
ck(rt.swarm_count == 4 and close(rt.swarm_spread, 0.05) and close(rt.swarm_drift, 0.01),
   "swarm_* must round-trip through JSON as unknown-kwarg extras")

# --- construction: the fan, its rooting, the whitelist --------------------
sio = synthio.Synthesizer()
s = SwarmSynth(sio, Patch(filt_f=1200, swarm_count=8, swarm_spread=0.01, swarm_drift=0.0))

ck(len(s._fan) == SwarmSynth.MAX_OSCS, "one fan block per oscillator SLOT, always MAX_OSCS")
for i, f in enumerate(s._fan):
    ck(f in sio.blocks, "fan[%d] must be ROOTED in synthesizer.blocks (catch 1)" % i)
    ck(f.a.a is s._swarm_blk, "fan[%d] must nest the SHARED swarm block, so one write reaches it" % i)
    ck(f.b is s._drift_lfos[i], "fan[%d] must sum in its own drift LFO" % i)
    ck(f.b.scale is s._drift_blk, "drift LFO %d must take the shared drift block as its scale" % i)
# A drift LFO ticks because it is NESTED inside a rooted fan, not because it
# is rooted itself, measured on rp2040 (10.3.0-alpha.3): rooted,
# nested-only and rooted+nested LFOs all advance; only a genuinely orphaned
# one freezes. So what must hold is REACHABILITY from a rooted block, and
# the drift LFOs must NOT be separately rooted (that is 8 wasted evaluations
# a block). The stubs cannot see ticking at all (nothing advances
# LFO.phase there) so this is asserted structurally.
for i, lfo in enumerate(s._drift_lfos):
    ck(lfo not in sio.blocks,
       "drift LFO %d must NOT be separately rooted; nesting in the fan is enough" % i)
    ck(s._fan[i] in sio.blocks and s._fan[i].b is lfo,
       "drift LFO %d must be reachable from a ROOTED fan block" % i)
    ck(not lfo.once, "a drift LFO is free-running, not a one-shot position ramp")
# distinct rates and phases, or the eight wander in lockstep
ck(len({l.rate for l in s._drift_lfos}) == SwarmSynth.MAX_OSCS,
   "every drift LFO needs its own rate")
ck(len({l.phase_offset for l in s._drift_lfos}) == SwarmSynth.MAX_OSCS,
   "every drift LFO needs its own phase offset")

for name in ("wave", "swarm_count", "swarm_spread", "swarm_drift"):
    ck(name in s._PARAMS, "%s must be in the _PARAMS whitelist" % name)
ck(SwarmSynth.mono is True, "SwarmSynth must be monophonic by default, like the instrument")
ck(s.swarm_count == 8 and close(s.swarm_spread, 0.01),
   "the patch must reach live state through _recompile")

# --- the fan is EQUIDISTANT and symmetric about the played pitch ----------
ks = [s._fan[i].a.b for i in range(8)]
ck(close(ks[0], -1.0) and close(ks[7], 1.0), "the outermost pair must sit at -1 and +1")
gaps = [ks[i + 1] - ks[i] for i in range(7)]
ck(max(gaps) - min(gaps) < 1e-9, "coefficients must be EQUIDISTANT, got %r" % (gaps,))
ck(close(sum(ks), 0.0), "the fan must be symmetric about 0 (the played pitch)")

# --- a voice: one Note per oscillator, each with its own bend SUM ---------
s.note_on(60, velocity=127)
notes = s.voices[60]
ck(len(notes) == 8, "swarm_count 8 must build 8 Notes, got %d" % len(notes))
for i, n in enumerate(notes):
    ck(n.bend is not s._bend, "Note %d must have its OWN bend node, not the shared one" % i)
    ck(n.bend.operation == "SUM", "the per-Note bend must be a SUM")
    ck(n.bend.a is s._bend, "...nesting the shared bend graph, so vibrato/pitchbend still reach it")
    ck(n.bend.b is s._fan[i], "...and summing in THIS oscillator's fan block")
    ck(n.frequency == notes[0].frequency,
       "every oscillator must sit on the SAME frequency, the spread is bend, not frequency")
# each oscillator gets its own random phase slice
ck(any(notes[i].waveform is not notes[0].waveform for i in range(1, 8)),
   "each oscillator needs its own random-phase waveform slice")

# --- amplitude: the worst case (all peaks aligned) still tops out at 1.0,
ck(close(sum(n.amplitude for n in notes), 1.0),
   "amplitudes must sum to velocity/127, got %r" % sum(n.amplitude for n in notes))

# --- THE design claim: one write sweeps a SOUNDING drone (catch 2) -------
s2 = SwarmSynth(sio, Patch(swarm_count=8, swarm_spread=0.0, swarm_drift=0.0))
s2.note_on(60)
held = s2.voices[60]
before = [n.bend.value for n in held]
ck(max(before) - min(before) < 1e-9, "at spread 0 every oscillator must be in unison")
s2.swarm_spread = 0.02  # ONE write, no per-voice loop anywhere
after = [n.bend.value for n in held]
ck(close(min(after), -0.02) and close(max(after), 0.02),
   "one write must fan the ALREADY SOUNDING notes to +/-spread, got %r" % (after,))
ck(close(sum(after), 0.0), "the swept fan must stay symmetric about the played pitch")
ck(all(held[i].bend.value < held[i + 1].bend.value for i in range(7)),
   "the fan must stay monotonic across oscillator slots")
# drift reaches sounding voices the same way
s2.swarm_drift = 0.005
ck(s2._drift_blk.a == 0.005 and held[0].bend.b.b.scale is s2._drift_blk,
   "swarm_drift must be one write into the block every sounding drift LFO scales by")

# --- swarm_count 1 must not divide by zero (catch 3) ---------------------
s2.swarm_count = 1
ck(close(s2._fan[0].a.b, 0.0), "a lone oscillator must sit ON pitch, not at -1")
s2.note_on(62)
ck(len(s2.voices[62]) == 1, "swarm_count 1 must build exactly one Note")
ck(close(s2.voices[62][0].bend.value, s2._bend.value + s2._drift_lfos[0].value),
   "a lone oscillator gets no spread offset")

# --- count changes rewrite coefficients IN PLACE (identity rule) ---------
ids = [id(f) for f in s2._fan]
prods = [id(f.a) for f in s2._fan]
s2.swarm_count = 5
ck([id(f) for f in s2._fan] == ids, "a count change must NOT replace the fan blocks")
ck([id(f.a) for f in s2._fan] == prods, "...nor the PRODUCT blocks inside them")
ck(close(s2._fan[0].a.b, -1.0) and close(s2._fan[4].a.b, 1.0) and close(s2._fan[2].a.b, 0.0),
   "5 oscillators must re-fan to -1..+1 with the middle one on pitch")
# out-of-range counts clamp rather than raise
s2.swarm_count = 99
ck(s2.swarm_count == SwarmSynth.MAX_OSCS, "swarm_count must clamp to MAX_OSCS")
s2.swarm_count = 0
ck(s2.swarm_count == 1, "swarm_count must clamp up to 1")

# --- count applies at the NEXT note-on, not to sounding voices -----------
s3 = SwarmSynth(sio, Patch(swarm_count=8))
s3.note_on(60)
s3.swarm_count = 3
ck(len(s3.voices[60]) == 8, "a sounding voice keeps the oscillators it was pressed with")
s3.note_off(60)
s3.note_on(64)
ck(len(s3.voices[64]) == 3, "the next note-on must use the new count")

# --- mono: a note-on steals the whole previous swarm ---------------------
s4 = SwarmSynth(sio, Patch(swarm_count=4))
s4.note_on(60)
s4.note_on(67)
ck(list(s4.voices.keys()) == [67], "mono: a note-on must steal whatever was sounding, got %r"
   % list(s4.voices.keys()))

# --- set_param string interface ------------------------------------------
s4.set_param("swarm_spread", 0.03)
s4.set_param("swarm_drift", 0.004)
s4.set_param("swarm_count", 6)
ck(close(s4.swarm_spread, 0.03) and close(s4.swarm_drift, 0.004) and s4.swarm_count == 6,
   "set_param must reach every swarm property")
try:
    s4.set_param("swarm_span", 1)
    fails.append("set_param must reject an unknown name")
except KeyError:
    pass

# --- the patch is NOT live state; save_patch commits ---------------------
pat = Patch(name="swarm", wave="SAW", swarm_count=8, swarm_spread=0.01, swarm_drift=0.003)
s5 = SwarmSynth(sio, pat)
s5.swarm_spread = 0.4
s5.swarm_drift = 0.0
s5.swarm_count = 5
s5.wave = "SIN"
ck(close(pat.swarm_spread, 0.01) and pat.swarm_count == 8 and pat.wave == "SAW",
   "a knob turn must NOT reach the patch")
ret = s5.save_patch()
ck(ret is pat, "save_patch() must return the loaded patch object, not a copy")
ck(close(pat.swarm_spread, 0.4) and close(pat.swarm_drift, 0.0) and pat.swarm_count == 5,
   "save_patch() must commit every swarm field (the silent-save trap)")
ck(pat.wave == "SIN", "save_patch() must commit the waveform too")

# reloading a different patch reverts live state
s5.load_patch(Patch(swarm_count=2, swarm_spread=0.02, swarm_drift=0.001))
ck(s5.swarm_count == 2 and close(s5.swarm_spread, 0.02) and close(s5.swarm_drift, 0.001),
   "load_patch must overwrite live swarm state")
ck(close(s5._fan[0].a.b, -1.0) and close(s5._fan[1].a.b, 1.0),
   "load_patch must re-fan the coefficients too")

# --- a patch with no swarm_* fields must LOAD and PLAY on the defaults ----
legacy = Patch.from_json('{"name":"old","filt_f":900,"wave":"SQU"}')
s5.load_patch(legacy)
ck(s5.swarm_count == SwarmSynth.MAX_OSCS,
   "a patch with no swarm fields must default to a full swarm")
ck(close(s5.swarm_spread, 0.01) and close(s5.swarm_drift, 0.003),
   "...and to the default spread and drift")
s5.note_on(60)
ck(len(s5.voices[60]) == SwarmSynth.MAX_OSCS, "a legacy patch must still play a full swarm")

# --- shared objects survive a patch reload (the identity rule) -----------
fan0, swarm_blk, drift_blk = s5._fan[0], s5._swarm_blk, s5._drift_blk
s5.load_patch(Patch(swarm_count=7, swarm_spread=0.06))
ck(s5._fan[0] is fan0, "the fan blocks must survive a patch reload")
ck(s5._swarm_blk is swarm_blk and s5._drift_blk is drift_blk,
   "the swarm/drift blocks must survive a patch reload")
ck(s5.voices[60][0].bend.b is fan0,
   "...so the voice sounding across the reload still points at a live fan")

# --- the pitch envelope must reach ALL EIGHT oscillators -----------------
# CLAUDE.md's named subclass trap: a Note built with self._bend instead of
# self._bend_cur silently ignores the pitch envelope. test_wiring.py pins
# this for SubtractiveSynth's two Notes; a swarm has eight chances to get
# it wrong, and a single stale oscillator would just sound slightly off.
s7 = SwarmSynth(sio, Patch(swarm_count=6, penv_amount=0.05, penv_time=0.1))
s7.note_on(60)
sw = s7.voices[60]
voice_bend = sw[0].bend.a
ck(voice_bend is not s7._bend,
   "with a pitch envelope the voice needs its OWN bend node under each fan")
ck(voice_bend.a is s7._bend, "...still nesting the shared bend graph")
for i, n in enumerate(sw):
    ck(n.bend.a is voice_bend,
       "oscillator %d must ride the voice's bend node (_bend_cur, not _bend)" % i)
    ck(n.bend.b is s7._fan[i], "...while keeping its own fan offset")

# --- no filter is an ordinary case, not an error -------------------------
s6 = SwarmSynth(sio, Patch(filt_type=None, swarm_count=3))
s6.note_on(60)
ck(len(s6.voices[60]) == 3 and s6.voices[60][0].filter is None,
   "filt_type None must play an unfiltered swarm")

print()
if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_swarm_synth: all checks passed")
for x in (s, s2, s3, s4, s5, s6, s7):
    x.all_notes_off()
