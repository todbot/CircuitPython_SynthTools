# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Integration checks for synthtools' Synth against the synthio stubs.

Proves: block identity and sharing, in-place buffer rewrites, param routing,
and -- new -- that the patch is NOT live state. No DSP: the stubs do not render audio.

The filter cutoff bus:

    SHARED   filt_base = MID(SUM(filt_f, filt_lfo), FMIN, FMAX)
    VOICE    cutoff    = MID(SUM(filt_base, fenv, vel_hz), FMIN, FMAX)
                           vel_hz = PRODUCT(filt_vel, vel/127)
                           fenv   = CONSTRAINED_LERP(0.0, depth, pos)
                                      depth = shared amount, or
                                              PRODUCT(amount, gain)
                                      gain  = LERP(1, vel/127, fenv_vel)
                                      pos   = LFO(shared shape, once=True)

    python3 tests/test_wiring.py
    micropython tests/test_wiring.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/stubs")
sys.path.insert(0, _D + "/..")

import synthio  # noqa: E402
import synthtools  # noqa: E402
from synthtools import Patch, SubtractiveSynth, Synth  # noqa: E402
from synthtools.ahr_envelope import AHREnvelope  # noqa: E402
from synthtools.waves import ENV_PEAK  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


def vals(a):
    return [int(v) for v in a]


# --- the package must survive a missing optional dependency --------------
# synthtools/__init__.py resolves names LAZILY (PEP 562), so a missing
# optional dependency is no longer something the package has to defend
# against: wavetable is simply never imported unless asked for. That is
# strictly better than the try/except this file used to carry, where the
# name silently did not exist and the user got "cannot import name".
# There is no adafruit_wave stub here, so this path runs every time
# -- which also means WavetableSynth itself is NOT covered by these tests.
ck(hasattr(synthtools, "Synth") and hasattr(synthtools, "SubtractiveSynth"),
   "core exports must survive a missing adafruit_wave")
ck(not any(m.endswith(".wavetable") or m.endswith(".wavetable_synth")
           for m in sys.modules),
   "importing synthtools must not pull wavetable in at all -- that, not a "
   "try/except, is what makes a board without adafruit_wave work")
try:
    synthtools.WavetableSynth
    fails.append("WavetableSynth must raise without adafruit_wave -- if this "
                 "fails, a real adafruit_wave is installed and the "
                 "missing-dependency path is no longer being tested")
except ImportError as e:
    ck("adafruit_wave" in str(e),
       "the error must NAME the missing dependency, got %r" % (str(e),))
except AttributeError:
    fails.append("a missing optional dep must surface as ImportError naming "
                 "adafruit_wave, not as a bare AttributeError")

# --- patch defaults and JSON round-trip ----------------------------------
p = Patch()
ck(p.fenv_curve == 1, "default fenv_curve should be 1, got %r" % p.fenv_curve)
ck("fenv_curve" in p.to_dict(), "fenv_curve must appear in to_dict()")
ck("filt_lfo_amount" in p.to_dict(), "filt_lfo_amount must appear in to_dict()")
ck(Patch.from_json(Patch(fenv_curve=3).to_json()).fenv_curve == 3,
   "fenv_curve must survive a JSON round-trip")
ck(Patch.from_json('{"name":"old","filt_f":900}').fenv_curve == 1,
   "legacy patch without fenv_curve must default to linear")
ck(Patch.from_json('{"name":"old","filt_f":900}').filt_lfo_amount == 0,
   "legacy patch without filt_lfo_amount must default to off")
# fenv_hold is gone, but old patch files still carry it: Patch's setattr
# loop must accept it as an inert extra rather than raising.
ck(Patch.from_json('{"fenv_hold":0.2}').fenv_hold == 0.2,
   "a retired field must still load as a harmless extra attribute")

# --- synth construction --------------------------------------------------
sio = synthio.Synthesizer()
s = SubtractiveSynth(sio, Patch(filt_f=1000, fenv_amount=3000,
                                fenv_attack=0.1, fenv_release=0.3))

for name in ("fenv_curve", "filt_vel", "fenv_vel",
             "filt_lfo_rate", "filt_lfo_amount"):
    ck(name in s._PARAMS, "%s must be in the _PARAMS whitelist" % name)
ck("fenv_hold" not in s._PARAMS, "fenv_hold must be gone from _PARAMS")

ck(s.fenv_curve == 1, "synth.fenv_curve must read live state")
ck(s._vib_lfo in sio.blocks,
   "the vibrato LFO must be appended to synth.blocks or it never ticks")
ck(s._filt_lfo in sio.blocks,
   "the filter LFO must be appended to synth.blocks or it never ticks")
# Math blocks need rooting too, not just LFOs. _filt_base and _bend are only
# reachable through a voice, so with nothing sounding they freeze -- and on a
# fresh Synth they have never been evaluated. Measured on hardware: without
# this the first note-on read its cutoff as 0.0 Hz.
ck(s._filt_base in sio.blocks,
   "the shared cutoff base must be rooted in synth.blocks, or the first "
   "note-on after silence inherits a stale (or never-computed) cutoff")
ck(s._bend in sio.blocks,
   "the shared bend graph must be rooted in synth.blocks for the same reason")

# --- the shared half of the cutoff bus -----------------------------------
ck(s._filt_sum.a is s._filt_f_blk, "the bus must sum the shared filt_f block")
ck(s._filt_sum.b is s._filt_lfo, "...and the shared filter LFO")
ck(s._filt_base.operation == "MID", "the shared base must be clamped")
ck(s._filt_base.a is s._filt_sum, "the clamp must wrap the sum")
s.filt_lfo_amount = 1500
s.filt_lfo_rate = 3.0
ck(s._filt_lfo.rate == 3.0, "filt_lfo_rate must be one write")

# The LFO must be ADDITIVE: filt_f is the floor and the LFO opens upward,
# the same convention as filt_vel. synthio's LFO is
# `waveform[idx] * scale + offset` over a zero-centred default triangle, so
# scale ALONE would swing +/-amount about filt_f and push the bottom half
# into the FILT_F_MIN clamp. scale == offset == amount/2 recentres it.
ck(abs(s._filt_lfo.scale - 750) < 1e-6,
   "amount must be stored as a half-swing in scale, got %r" % s._filt_lfo.scale)
ck(abs(s._filt_lfo.offset - 750) < 1e-6,
   "...and matched by an equal offset, or the swing stays centred on filt_f "
   "(got %r)" % s._filt_lfo.offset)
ck(abs(s.filt_lfo_amount - 1500) < 1e-6,
   "the getter must undo the half-swing, got %r" % s.filt_lfo_amount)
# Sweep the phase rather than assuming where the peak sits: the buffer's
# peak is at index 32 of 64, but the stub maps phase 0.5 to int(0.5*63) = 31,
# so a spot check at 0.5 reads 96.9% and proves nothing useful either way.
lfo_lo = lfo_hi = None
base_lo = base_hi = None
for _i in range(65):
    s._filt_lfo.phase = _i / 64.0
    v, b = s._filt_lfo.value, s._filt_base.value
    lfo_lo = v if lfo_lo is None else min(lfo_lo, v)
    lfo_hi = v if lfo_hi is None else max(lfo_hi, v)
    base_lo = b if base_lo is None else min(base_lo, b)
    base_hi = b if base_hi is None else max(base_hi, b)
s._filt_lfo.phase = 0.0

ck(abs(lfo_lo) < 1e-6,
   "the LFO's floor must be exactly 0 -- it ADDS to filt_f, never subtracts. "
   "Got %r; a negative floor means the bipolar default waveform is back" % lfo_lo)
ck(abs(lfo_hi - 1500) < 1.0,
   "the LFO must reach the full amount at its peak, got %r" % lfo_hi)
ck(abs(base_lo - s.filt_f) < 1e-6,
   "filt_f must be the FLOOR of the modulated base, got %r want %r"
   % (base_lo, s.filt_f))
ck(abs(base_hi - (s.filt_f + 1500)) < 1.0,
   "the base must peak at filt_f + amount, got %r" % base_hi)

s.filt_lfo_amount = 0     # the stubs render no DSP; the sweep itself is a
s.filt_lfo_rate = 0.5     # hardware-tier check

# --- the shared base is clamped ------------------------------------------
s.filt_f = 1
ck(abs(s._filt_base.value - s.FILT_F_MIN) < 1e-6,
   "an absurdly low filt_f must clamp to FILT_F_MIN, got %r" % s._filt_base.value)
s.filt_f = 999999
ck(abs(s._filt_base.value - s.FILT_F_MAX) < 1e-6,
   "an absurdly high filt_f must clamp to FILT_F_MAX, got %r" % s._filt_base.value)
s.filt_f = 1000

env_obj = s._fenv
lin_shape = vals(env_obj._wave)
buf = env_obj._wave
blk_f, blk_q = s._filt_f_blk, s._filt_q_blk
base_blk = s._filt_base

# --- blocks and buffers must survive a patch reload ----------------------
# Sounding voices hold references to these, so identity has to be stable.
s.load_patch(Patch(filt_f=1234, fenv_amount=2000))
ck(s._filt_f_blk is blk_f, "filt_f block must be written, never replaced")
ck(s._filt_q_blk is blk_q, "filt_q block must be written, never replaced")
ck(s._filt_base is base_blk, "the shared cutoff base must never be replaced")
ck(s._fenv is env_obj, "the AHREnvelope must be written, never replaced")
ck(s._fenv._wave is buf, "the shape buffer must survive a patch reload")
ck(s._fenv._amt is env_obj._amt, "the depth block must survive a patch reload")
ck(s._filt_f_blk.a == 1234, "patch reload must push filt_f into the shared block")
ck(s._fenv.amount == 2000, "patch reload must push fenv_amount into the envelope")

# =====================================================================
# the patch is NOT live state
# =====================================================================
pat = Patch(filt_f=1000, filt_q=1.1, wave="SAW", detune=1.002,
            amp_env=[0.01, 0.10, 0.8, 0.35], fenv_amount=3000,
            fenv_attack=0.1, fenv_release=0.3)
s.load_patch(pat)

s.filt_f = 2000
s.attack_time = 0.5
s.release_time = 0.9      # index 3: the one a wrong _decompile would drop
s.fenv_amount = 500
s.wave = "SQU"
s.detune = 1.5
s.filt_lfo_amount = 700

ck(pat.filt_f == 1000, "a knob turn must NOT reach the patch")
ck(pat.amp_env[0] == 0.01 and pat.amp_env[3] == 0.35,
   "amp_env must be COPIED at load, not aliased -- otherwise an in-place "
   "element write leaks straight into the patch")
ck(pat.fenv_amount == 3000, "fenv_amount must not reach the patch either")
ck(pat.wave == "SAW", "a subclass param must not reach the patch")

ck(s.filt_f == 2000, "the getter must read live state, got %r" % s.filt_f)
ck(s.attack_time == 0.5, "attack_time getter must read live state")
ck(s.release_time == 0.9, "release_time getter must read live state")
ck(s.fenv_amount == 500, "fenv_amount getter must read live state")
ck(s.wave == "SQU", "wave getter must read live state")
ck(s.detune == 1.5, "detune getter must read live state")

ret = s.save_patch()
ck(ret is pat, "save_patch() must return the loaded patch object")
ck(pat.filt_f == 2000, "save_patch() must commit filt_f")
ck(pat.amp_env[0] == 0.5 and pat.amp_env[3] == 0.9,
   "save_patch() must commit EVERY amp_env stage, not just the first")
ck(pat.fenv_amount == 500, "save_patch() must commit fenv_amount")
ck(pat.filt_lfo_amount == 700, "save_patch() must commit filt_lfo_amount")
ck(pat.wave == "SQU" and pat.detune == 1.5,
   "save_patch() must reach the subclass's _decompile() too")

# and the committed patch must not become an alias either
s.attack_time = 0.7
ck(pat.amp_env[0] == 0.5,
   "amp_env must be copied OUT by _decompile too, or knob turns after a save "
   "keep leaking into the patch")

# --- a patch file older than the current fields must LOAD, not just parse ---
# Patch.__init__ sets every default BEFORE applying kwargs, so any Patch --
# however old the JSON -- always carries the newer fields, and _recompile can
# read p.filt_lfo_rate & co. unguarded. That is a property of Patch, not an
# accident, so it is worth a test that drives it all the way through the
# engine rather than only checking Patch's own defaults.
legacy = Patch.from_json('{"name":"old","filt_f":900,"fenv_hold":0.2,'
                         '"filt_type":"LPF","fenv_amount":1000}')
s.load_patch(legacy)                  # must not raise
ck(s.filt_lfo_rate == 0.5, "a pre-filter-LFO patch must load with the default")
ck(s.filt_vel == 0, "a pre-velocity patch must load with no velocity response")
s.note_on(60, velocity=100)           # and the note-on path must survive it
ck(60 in s.voices, "a legacy patch must still play")
s.all_notes_off()
# the retired field rides along untouched -- Patch round-trips unknown keys,
# and _decompile has no reason to touch one it does not own
s.save_patch()
ck(legacy.to_dict().get("fenv_hold") == 0.2,
   "a retired field must survive save_patch() as an inert extra, neither "
   "consumed nor rewritten")

# reloading is therefore a revert
s.load_patch(Patch(filt_f=1000, fenv_amount=3000,
                   fenv_attack=0.1, fenv_release=0.3))
ck(s.filt_f == 1000, "load_patch must overwrite live state")

# --- note on: the shared graph must reach the voice ----------------------
# filt_vel and fenv_vel are both 0 here, so this is also the check that the
# common case allocates as little as possible.
s.note_on(60)
ck(len(sio.pressed) == 2,
   "detune != 1.0 should press 2 notes, got %d" % len(sio.pressed))
env = s._fenvs[60]
ck(env.operation == "CONSTRAINED_LERP",
   "the voice envelope must be a CONSTRAINED_LERP")
ck(env.a == 0.0, "the envelope is a modulation SOURCE: it must rise from 0")
ck(env.b is s._fenv._amt,
   "with fenv_vel=0 the depth must BE the shared amount block, no extra Math")
pos = env.c
ck(pos.waveform is s._fenv._wave,
   "the position LFO must read the shared shape buffer")
ck(pos.rate is s._fenv._rate_a,
   "the position LFO must use the shared attack rate")
ck(pos.once, "the position LFO must be one-shot")

cutoff = s.voices[60][0].filter.frequency
ck(cutoff.operation == "MID", "the voice cutoff must be clamped")
ck(cutoff.a.operation == "SUM", "...over a SUM of the modulation sources")
ck(cutoff.a.a is s._filt_base, "the voice must nest the shared base")
ck(cutoff.a.b is env, "...and its own envelope")
ck(cutoff.a.c == 0.0, "with filt_vel=0 the velocity term must be a literal 0")
for n in sio.pressed:
    ck(n.bend is s._bend, "every note must share the one bend graph")
    ck(n.filter.frequency is cutoff,
       "every Note of one voice must share ONE cutoff graph")

# --- globals stay O(1) while the voice sounds ----------------------------
pos.phase = 1.0                       # envelope at full depth
s.filt_f = 800
ck(s._filt_f_blk.a == 800, "filt_f must be one write into the shared block")
ck(cutoff.a.a is s._filt_base, "the sounding voice must still point at the base")
ck(abs(cutoff.value - (800 + 3000)) < 1e-6,
   "the voice's cutoff must follow filt_f, got %r" % cutoff.value)
s.fenv_amount = 2500
ck(abs(cutoff.value - (800 + 2500)) < 1e-6,
   "the voice's cutoff must follow fenv_amount, got %r" % cutoff.value)
s.fenv_amount = 3000
s.filt_f = 1000

# --- the curve is live: change it while a voice is sounding --------------
s.set_param("fenv_curve", 2)
ck(s._fenv._wave is buf, "the shape buffer must be rewritten IN PLACE, not replaced")
ck(pos.waveform is s._fenv._wave, "sounding voice must still see the shared buffer")
cur_shape = vals(s._fenv._wave)
ck(cur_shape != lin_shape, "the shape must change when fenv_curve changes")
ck(cur_shape[0] == 0 and cur_shape[-1] == ENV_PEAK, "curved endpoints must hold")
# The rise fills the whole buffer, so every interior sample is comparable.
# curve=2 sits ABOVE linear: the buffer holds 1-(1-t)^curve, because the
# release reruns it as V*(1-s(t)) and so inverts its curvature.
ck(all(c >= lin for c, lin in zip(cur_shape, lin_shape)),
   "curve=2 must never sit below linear")
ck(cur_shape[32] > lin_shape[32], "curve=2 must sit above linear mid-rise")

# --- release: endpoints swap, waveform is NEVER reassigned ---------------
# synthio.LFO.waveform is read-only on real hardware, so a release that
# reassigns it raises AttributeError at every note-off. The stub enforces
# that too -- check the guard itself still works, or this whole section
# quietly stops meaning anything.
try:
    pos.waveform = s._fenv._wave
    fails.append("the synthio stub must refuse to reassign LFO.waveform, "
                 "the way real synthio does -- otherwise it cannot catch the "
                 "bug it exists to catch")
except AttributeError:
    pass
wave_before = pos.waveform
pos.phase = 0.5                      # part-way up the rise
mid = cutoff.value
v_start = env.value                  # the envelope's height at note-off
s.note_off(60)
ck(pos.waveform is wave_before, "release must NOT reassign the LFO's waveform")
ck(pos.rate is s._fenv._rate_r, "release must swap to the shared release rate")
ck(env.b is s._fenv._rel_amt,
   "release must aim at the shared release-amount BLOCK, not a bare 0.0 -- "
   "that is what removes the rising/falling branch and keeps the target live")
ck(abs(env.b.value) < 1e-6,
   "...and for a filter envelope that block holds 0.0, got %r" % env.b.value)
ck(abs(cutoff.value - mid) < 1e-6,
   "release must start exactly where the attack got to: %r -> %r"
   % (mid, cutoff.value))

# --- the release must be a DECAY, not a mirrored attack ------------------
# NOTE this section deliberately runs with fenv_curve still at 2. At curve=1
# the correct and the broken shapes are algebraically identical (1-t == 1-t),
# so a release only ever tested at curve=1 proves nothing about the shape --
# which is exactly how the mirrored-attack release shipped.
#
# release(t) = V * (1 - s(t)). With s = 1-(1-t)^2 that is V*(1-t)^2:
# 0.258*V by halfway. With the old s = t^2 it would read 0.758*V -- hanging
# near the top, then falling off a cliff.
pos.phase = 0.5
want = v_start * (1.0 - s._fenv._wave[31] / float(ENV_PEAK))
ck(abs(env.value - want) < 1e-6,
   "halfway through the release the envelope must follow the buffer: "
   "%r want %r" % (env.value, want))
ck(env.value < 0.5 * v_start,
   "halfway through the release the envelope must be past half its starting "
   "height (%r of %r) -- anything above that is a mirrored attack, not a decay"
   % (env.value, v_start))

pos.phase = 1.0
ck(abs(cutoff.value - s._filt_base.value) < 1e-6,
   "a fully released voice must sit on the shared base, got %r want %r"
   % (cutoff.value, s._filt_base.value))
ck(60 not in s.voices and 60 not in s._fenvs, "note_off must drop the voice")
s.set_param("fenv_curve", 1)

# --- fenv_amount == 0 costs nothing --------------------------------------
s.fenv_amount = 0
s.note_on(64)
ck(64 not in s._fenvs, "no filter envelope should be built when fenv_amount is 0")
ck(sio.pressed[-1].filter.frequency is s._filt_base,
   "with no modulation at all the Biquad must ride the SHARED base directly, "
   "allocating nothing per voice")
s.all_notes_off()
s.fenv_amount = 3000

# --- set_param is a whitelist --------------------------------------------
try:
    s.set_param("fenv_curv", 2)
    fails.append("set_param must reject names outside _PARAMS")
except KeyError:
    pass

# --- all_notes_off leaves nothing behind ---------------------------------
s.note_on(60)
s.note_on(67)
s.all_notes_off()
ck(not s.voices, "all_notes_off must clear every voice")
ck(not s._fenvs, "all_notes_off must clear every filter envelope")
ck(not s._penvs, "all_notes_off must clear every pitch envelope")

# =====================================================================
# pitch modulation: vibrato fade-in and the pitch envelope
# =====================================================================

# --- vib_delay: a fade INSIDE the shared LFO's scale ---------------------
s.load_patch(Patch(vib_depth=0.01, vib_rate=5.0, vib_delay=1.5))
ck(s._vib_lfo.scale is not None and hasattr(s._vib_lfo.scale, "operation"),
   "the vibrato LFO's scale must be a PRODUCT(depth, fade), not a float")
ck(s._vib_lfo.scale.a is s._vib_depth_blk,
   "the fade must nest the shared depth block, so vib_depth stays one write")
ck(s._vib_lfo.scale.b is s._vib_fade, "...and the shared fade ramp")
ck(abs(s._vib_fade.rate - 1.0 / 1.5) < 1e-6,
   "vib_delay must set the fade rate to 1/seconds, got %r" % s._vib_fade.rate)
ck(s._vib_fade.once, "the fade ramp must be one-shot")
ck(s._vib_fade.waveform is not None,
   "the fade needs an explicit RAMP waveform -- synthio's default is a "
   "zero-centred triangle, which would come back down again")
ck(s.vib_delay == 1.5, "the getter must read live state")

# vib_delay = 0 must need no special case: the ramp just finishes at once
s.vib_delay = 0.0
ck(s._vib_fade.rate >= 1000.0,
   "vib_delay=0 must become an effectively instant ramp, got %r"
   % s._vib_fade.rate)
s.vib_delay = 1.5

# depth still reaches a sounding voice with one write
s._vib_fade.phase = 1.0                  # fade complete
s.vib_depth = 0.02
ck(abs(s._vib_lfo.scale.value - 0.02) < 1e-6,
   "vib_depth must still be one write through the PRODUCT, got %r"
   % s._vib_lfo.scale.value)
s._vib_fade.phase = 0.0
ck(abs(s._vib_lfo.scale.value) < 1e-6,
   "at the start of the fade the effective depth must be 0, got %r"
   % s._vib_lfo.scale.value)

# --- the fade retriggers from SILENCE, not on every note-on --------------
s._vib_fade.retriggered = 0
s.note_on(60)
ck(s._vib_fade.retriggered == 1, "the first note from silence must retrigger")
s.note_on(64)
ck(s._vib_fade.retriggered == 1,
   "adding a note to a held chord must NOT restart the fade -- that would "
   "duck everyone's vibrato back to zero")
s.note_off(60)
s.note_on(67)
ck(s._vib_fade.retriggered == 1,
   "...still not, while any note is held")
s.all_notes_off()
s.note_on(60)
ck(s._vib_fade.retriggered == 2,
   "starting again from silence must retrigger")
s.all_notes_off()

# --- pitch envelope: costs nothing when off ------------------------------
s.load_patch(Patch(vib_depth=0.01))      # all four penv_* default to 0
s.note_on(60)
ck(60 not in s._penvs, "no pitch envelope should be built when both amounts are 0")
for n in s.voices[60]:
    ck(n.bend is s._bend,
       "with no pitch envelope every Note must ride the SHARED bend graph "
       "directly, allocating nothing per voice")
s.all_notes_off()

# --- pitch envelope: per voice when on -----------------------------------
s.load_patch(Patch(penv_amount=0.5, penv_time=0.1,
                   penv_out_amount=0.25, penv_out_time=0.2))
s.note_on(60)
s.note_on(64)
p60, p64 = s._penvs[60], s._penvs[64]
ck(p60 is not p64, "each voice must get its OWN pitch envelope")
ck(p60.c is not p64.c, "...with its own position LFO, so they can be staggered")
b60 = s.voices[60][0].bend
ck(b60 is not s._bend, "a voice with a pitch envelope needs its own bend node")
ck(b60.operation == "SUM", "the per-voice bend must be a SUM")
ck(b60.a is s._bend, "...nesting the shared bend graph, so vibrato still reaches it")
ck(b60.b is p60, "...plus this voice's own pitch envelope")
for n in s.voices[60]:
    ck(n.bend is b60, "every Note of one voice must share ONE bend node")
ck(s.voices[64][0].bend is not b60, "a different voice gets a different node")

# --- bend-in shape: amount -> 0, the OPPOSITE of the filter envelope -----
p60.c.phase = 0.0
ck(abs(p60.value - 0.5) < 1e-6,
   "at note-on the pitch envelope must sit at penv_amount, got %r" % p60.value)
p60.c.phase = 1.0
ck(abs(p60.value) < 1e-6,
   "and settle to 0 = true pitch, got %r" % p60.value)
ck(abs(b60.value - s._bend.value) < 1e-6,
   "once settled the voice's bend must equal the shared bend")

# --- bend-out on note-off ------------------------------------------------
p60.c.phase = 1.0
before = p60.value
s.note_off(60)
ck(p60.b is s._penv._rel_amt,
   "release must aim at the shared out-amount BLOCK, so penv_out_amount "
   "stays live for a voice that is already drifting")
p60.c.phase = 0.0
ck(abs(p60.value - before) < 1e-6,
   "the bend-out must start exactly where the note left off: %r -> %r"
   % (before, p60.value))
p60.c.phase = 1.0
ck(abs(p60.value - 0.25) < 1e-6,
   "and land on penv_out_amount, got %r" % p60.value)
s.all_notes_off()

# --- out-only patch: the node must still be built at press ---------------
s.load_patch(Patch(penv_amount=0.0, penv_out_amount=0.3, penv_out_time=0.2))
s.note_on(60)
ck(60 in s._penvs,
   "an out-only pitch envelope must still build its node at note-on -- "
   "note-off has nothing to re-aim otherwise")
ck(abs(s._penvs[60].value) < 1e-6,
   "...and read 0 during the note, got %r" % s._penvs[60].value)
s.note_off(60)
s.all_notes_off()

# --- identity across a patch reload --------------------------------------
penv_obj, vib_fade, vib_lfo, bend = s._penv, s._vib_fade, s._vib_lfo, s._bend
amt_blk, rel_blk = s._penv._amt, s._penv._rel_amt
s.load_patch(Patch(penv_amount=0.2, penv_out_amount=0.1, vib_delay=0.5))
ck(s._penv is penv_obj, "the pitch envelope must be written, never replaced")
ck(s._penv._amt is amt_blk and s._penv._rel_amt is rel_blk,
   "its blocks must survive a patch reload")
ck(s._vib_fade is vib_fade and s._vib_lfo is vib_lfo,
   "the vibrato objects must survive a patch reload")
ck(s._bend is bend, "the shared bend graph must survive a patch reload")
ck(abs(s._penv.amount - 0.2) < 1e-6, "reload must push penv_amount through")
ck(abs(s._penv.release_amount - 0.1) < 1e-6, "...and penv_out_amount")
ck(abs(s._vib_fade.rate - 1.0 / 0.5) < 1e-6, "...and vib_delay")

# --- the two envelopes are independent instances -------------------------
ck(s._penv is not s._fenv, "pitch and filter envelopes are separate instances")
ck(s._penv._wave is not s._fenv._wave,
   "each envelope owns its shape buffer, so penv curvature is independent "
   "of fenv_curve")
ck(s._penv._falling and not s._fenv._falling,
   "the pitch envelope falls, the filter envelope rises")
s.all_notes_off()

# =====================================================================
# velocity -> filter cutoff, and velocity -> envelope depth
# =====================================================================

# --- reusability: the envelope must work with no filter anywhere ---------
# This is the property a future pitch envelope needs -- the envelope takes
# no destination at all, and nothing here touches a Biquad.
solo = AHREnvelope(attack=0.1, release=0.2, amount=1.0)
senv = solo.make()
ck(senv is not None, "a standalone AHREnvelope must build a block")
ck(senv.a == 0.0, "a standalone envelope must rise from 0")
ck(senv.c.waveform is solo._wave, "standalone must use its own shape buffer")
senv.c.phase = 1.0
ck(abs(senv.value - 1.0) < 1e-6,
   "standalone must reach its amount, got %r" % senv.value)
solo.start_release(senv)
senv.c.phase = 1.0
ck(abs(senv.value - 0.0) < 1e-6, "standalone release must return to zero")
ck(AHREnvelope(amount=0).make() is None, "amount=0 must build nothing")

# --- velocity -> cutoff ---------------------------------------------------
FV = 2000
s.load_patch(Patch(filt_f=1000, filt_vel=FV, fenv_amount=0))
s.note_on(60, velocity=127)
hard = s.voices[60][0].filter.frequency
s.note_on(64, velocity=32)
soft = s.voices[64][0].filter.frequency

ck(hard is not soft, "different velocities must get different cutoff blocks")
ck(abs(hard.value - (1000 + FV)) < 1e-6,
   "velocity 127 must give filt_f + filt_vel, got %r" % hard.value)
ck(abs(soft.value - (1000 + (32 / 127.0) * FV)) < 1e-6,
   "velocity 32 must give filt_f + (32/127)*filt_vel, got %r" % soft.value)
ck(hard.a.a is s._filt_base and soft.a.a is s._filt_base,
   "both per-voice cutoffs must nest the shared base")
ck(hard.a.c.a is s._filt_vel_blk,
   "the velocity term must nest the SHARED filt_vel block, not a baked float")
s.filt_f = 500
ck(abs(hard.value - (500 + FV)) < 1e-6,
   "filt_f must remain O(1) through the per-voice block")
ck(abs(soft.value - (500 + (32 / 127.0) * FV)) < 1e-6, "...for every voice")
# filt_vel is a block now, so it reaches a voice that is ALREADY sounding
s.filt_vel = 1000
ck(abs(hard.value - (500 + 1000)) < 1e-6,
   "filt_vel must stay live for a sounding voice, got %r" % hard.value)
s.all_notes_off()

# --- signed filt_vel: hard playing closes the filter ---------------------
s.load_patch(Patch(filt_f=3000, filt_vel=-2000, fenv_amount=0))
s.note_on(60, velocity=127)
s.note_on(64, velocity=0)
ck(abs(s.voices[60][0].filter.frequency.value - 1000) < 1e-6,
   "a negative filt_vel must CLOSE the filter at full velocity, got %r"
   % s.voices[60][0].filter.frequency.value)
ck(abs(s.voices[64][0].filter.frequency.value - 3000) < 1e-6,
   "...and leave velocity 0 at the base")
s.all_notes_off()

# --- the per-voice sum is clamped too ------------------------------------
# a downward envelope is a normal patch, and it can take the sum negative
s.load_patch(Patch(filt_f=1000, fenv_amount=-5000, fenv_attack=0.1))
s.note_on(60, velocity=127)
c = s.voices[60][0].filter.frequency
s._fenvs[60].c.phase = 1.0
ck(abs(c.value - s.FILT_F_MIN) < 1e-6,
   "a downward sweep past zero must clamp to FILT_F_MIN, got %r" % c.value)
s.all_notes_off()

# --- velocity -> envelope depth ------------------------------------------
s.load_patch(Patch(filt_f=1000, fenv_amount=3000, fenv_vel=1.0,
                   fenv_attack=0.1, fenv_release=0.3))
s.note_on(60, velocity=127)
s.note_on(64, velocity=64)
e_hard, e_soft = s._fenvs[60], s._fenvs[64]
e_hard.c.phase = 1.0
e_soft.c.phase = 1.0
# gain 1.0 collapses to the shared block; anything else wraps it in a PRODUCT
ck(e_hard.b.a is s._fenv._amt or e_hard.b is s._fenv._amt,
   "the hard voice's depth must still nest the shared amount block")
ck(e_soft.b.a is s._fenv._amt, "a scaled voice must still nest the shared block")
ck(e_soft.b.b.c is s._fenv_vel_blk,
   "the velocity gain must nest the SHARED fenv_vel block, not a baked float")
ck(abs(e_hard.value - 3000) < 1e-6,
   "full velocity depth = fenv_amount, got %r" % e_hard.value)
ck(abs(e_soft.value - 3000 * 64 / 127.0) < 1e-6,
   "velocity 64 must scale depth by vel/127, got %r" % e_soft.value)
# the shared depth must still reach BOTH voices with one write
s.fenv_amount = 1000
ck(abs(e_hard.value - 1000) < 1e-6, "fenv_amount stays O(1) with velocity scaling")
ck(abs(e_soft.value - 1000 * 64 / 127.0) < 1e-6, "...for the scaled voice too")
# and so must fenv_vel itself, which the old Python-side gain could not do
s.fenv_vel = 0.0
ck(abs(e_soft.value - 1000) < 1e-6,
   "fenv_vel must stay LIVE for a sounding voice: dropping it to 0 must "
   "restore full depth, got %r" % e_soft.value)
s.all_notes_off()

# a velocity-0 note with full tracking sweeps nothing, but must not raise
s.load_patch(Patch(filt_f=1000, fenv_amount=3000, fenv_vel=1.0))
s.note_on(72, velocity=0)
ck(72 in s._fenvs, "a zero-gain voice still gets an envelope (fenv_vel is live)")
ck(abs(s._fenvs[72].b.value) < 1e-6, "...whose depth is currently zero")
s.note_off(72)          # must not raise
s.all_notes_off()

# --- release continuity with every combination of the velocity terms -----
for fv, filt_vel in ((0.0, 0), (0.75, 0), (0.75, 2000)):
    s.load_patch(Patch(filt_f=1000, fenv_amount=3000, fenv_vel=fv,
                       filt_vel=filt_vel, fenv_attack=0.1, fenv_release=0.3))
    s.note_on(60, velocity=40)
    e = s._fenvs[60]
    c = s.voices[60][0].filter.frequency
    e.c.phase = 0.4
    before = c.value
    s.note_off(60)
    ck(abs(c.value - before) < 1e-6,
       "release continuous (fenv_vel=%s filt_vel=%s): %r -> %r"
       % (fv, filt_vel, before, c.value))
    e.c.phase = 1.0
    # the envelope falls to 0; the velocity offset is static and stays
    want = 1000 + filt_vel * 40 / 127.0
    ck(abs(c.value - want) < 1e-6,
       "release lands on base+velocity (fenv_vel=%s filt_vel=%s): %r want %r"
       % (fv, filt_vel, c.value, want))
    s.all_notes_off()

print("shape linear:", [lin_shape[i] for i in (0, 16, 32, 48, 63)])
print("shape curve2:", [cur_shape[i] for i in (0, 16, 32, 48, 63)])
# --- keyboard tracking: filt_track ---------------------------------------
# The Swarmatron's 'T' switch: the cutoff follows the BASE pitch, with the
# knob setting amount AND direction. Same idiom as filt_vel -- a per-voice
# constant from the note, times a shared block that stays live inside the
# graph -- so this is Synth behaviour, not a swarm-specific one.
st = SubtractiveSynth(sio, Patch(filt_type="LPF", filt_f=1000, filt_q=1.0,
                                 fenv_amount=0, filt_vel=0, filt_track=0.0))

# off by default: no per-voice node at all, just the shared base
st.note_on(60)
ck(st.voices[60][0].filter.frequency is st._filt_base,
   "filt_track 0 must allocate NO per-voice cutoff node")
st.note_off(60)

# full tracking: an octave up must double the cutoff, exactly
st.filt_track = 1.0
for note, want in ((60, 1000.0), (72, 2000.0), (48, 500.0)):
    st.note_on(note)
    got = st.voices[note][0].filter.frequency.value
    ck(abs(got - want) < 0.01,
       "filt_track 1.0: note %d must sit at %.1f Hz, got %.4f" % (note, want, got))
    st.note_off(note)

# the pivot note is untouched whatever the amount
for amt in (-1.0, 0.5, 2.0):
    st.filt_track = amt
    st.note_on(Synth.FILT_TRACK_REF)
    ck(abs(st.voices[Synth.FILT_TRACK_REF][0].filter.frequency.value - 1000.0) < 0.01,
       "FILT_TRACK_REF must read filt_f at filt_track %r" % amt)
    st.note_off(Synth.FILT_TRACK_REF)

# negative = inverse: playing higher CLOSES the filter
st.filt_track = -1.0
st.note_on(72)
ck(st.voices[72][0].filter.frequency.value < 1000.0,
   "negative filt_track must close the filter as pitch rises, got %r"
   % st.voices[72][0].filter.frequency.value)
st.note_off(72)

# THE point: both knobs stay LIVE inside a sounding voice's tracking node
st.filt_track = 1.0
st.note_on(72)
cut = st.voices[72][0].filter.frequency
ck(abs(cut.value - 2000.0) < 0.01, "sanity before the live writes")
st.filt_track = 0.5                       # half tracking, mid-note
ck(abs(cut.value - 1500.0) < 0.01,
   "writing filt_track must move a SOUNDING voice: want 1500, got %r" % cut.value)
st.filt_f = 2000                          # and filt_f still reaches it too
ck(abs(cut.value - 3000.0) < 0.01,
   "filt_f must still reach the same sounding voice: want 3000, got %r" % cut.value)
st.note_off(72)
st.filt_f = 1000

# a big negative tracking on a high note is clamped, not negative
st.filt_track = -4.0
st.note_on(96)
ck(st.voices[96][0].filter.frequency.value >= Synth.FILT_F_MIN,
   "a large negative filt_track must be caught by the existing clamp, got %r"
   % st.voices[96][0].filter.frequency.value)
st.note_off(96)
st.filt_track = 0.0

# tracking and velocity coexist -- they fold into ONE node, not four inputs
st.filt_track = 1.0
st.filt_vel = 500
st.note_on(72, velocity=127)
got = st.voices[72][0].filter.frequency.value
ck(abs(got - 2500.0) < 0.01,
   "tracking + velocity must both land: want 2500, got %r" % got)
st.note_off(72)
st.filt_vel = 0

# patch round-trip: the silent-save trap
ck("filt_track" in Patch().to_dict(), "filt_track must be a Patch field")
ck("filt_track" in st._PARAMS, "filt_track must be in the _PARAMS whitelist")
ck(Patch.from_json('{"name":"old"}').filt_track == 0.0,
   "a legacy patch must default filt_track to 0 (off)")
pt = Patch(filt_track=0.25)
st2 = SubtractiveSynth(sio, pt)
ck(st2.filt_track == 0.25, "filt_track must load through _recompile")
st2.filt_track = 0.75
ck(pt.filt_track == 0.25, "a knob turn must NOT reach the patch")
st2.save_patch()
ck(pt.filt_track == 0.75, "save_patch() must commit filt_track")

print()
if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_wiring: all checks passed")
