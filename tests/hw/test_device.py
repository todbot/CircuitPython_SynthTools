# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT

import time
import synthio

from synth_setup import synth as engine, mixer
from synthtools import Patch, SubtractiveSynth
from synthtools.ahr_envelope import AHREnvelope

mixer.voice[0].level = 0.0          # verify the block graph, don't make noise

fails = []


def ck(cond, msg):
    print(("  ok  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def settle(t=0.25):
    time.sleep(t)


print("--- 10.2  MathOperation arithmetic matches the docs ---------------")
for op, a, b, c, want, name in (
    (synthio.MathOperation.PRODUCT, 2.0, 3.0, 4.0, 24.0, "PRODUCT a*b*c"),
    (synthio.MathOperation.SUM, 2.0, 3.0, 4.0, 9.0, "SUM a+b+c"),
    (synthio.MathOperation.LERP, 10.0, 20.0, 0.25, 12.5, "LERP a*(1-c)+b*c"),
    (synthio.MathOperation.MID, 5.0, 1.0, 9.0, 5.0, "MID middle-of-three"),
    (synthio.MathOperation.MID, -7.0, 20.0, 20000.0, 20.0, "MID clamps low"),
):
    m = synthio.Math(op, a, b, c)
    engine.blocks.append(m)
    settle(0.1)
    ck(abs(m.value - want) < 0.001, "%s == %s, got %r" % (name, want, m.value))
    engine.blocks.remove(m)

print("--- PROBE: what does Biquad do with a negative frequency? --------")
# This is why the cutoff bus is clamped with MID. If Biquad turns out to
# handle it gracefully, FILT_F_MIN/FILT_F_MAX and both clamp blocks can go.
try:
    bq = synthio.Biquad(synthio.FilterMode.LOW_PASS, frequency=-500.0, Q=1.0)
    n = synthio.Note(440, filter=bq)
    engine.press(n)
    settle(0.2)
    engine.release(n)
    settle(0.2)
    print("      NEGATIVE Biquad.frequency was ACCEPTED and did not crash")
    print("      -> the MID clamp is defensive only; audio quality unknown")
except Exception as e:      # noqa: BLE001 -- this is the whole point
    print("      NEGATIVE Biquad.frequency raised %s: %s" % (type(e).__name__, e))
    print("      -> the MID clamp is MANDATORY, keep it")

print("--- 10.1 / 10.5  blocks nest, and Biquad.frequency takes one -----")
patch = Patch(name="hw", wave="SAW", detune=1.0, filt_type="LPF",
              filt_f=1000, filt_q=1.2, fenv_amount=3000,
              fenv_attack=0.5, fenv_release=0.5,
              amp_env=[0.01, 0.1, 0.8, 2.0])
s = SubtractiveSynth(engine, patch)

s.note_on(60, velocity=127)
settle(0.05)
env = s._fenvs[60]
note = s.voices[60][0]
cutoff = note.filter.frequency
ck(note.filter is not None, "voice got a Biquad")
ck(cutoff.a.a is s._filt_base, "the voice's cutoff nests the shared base")
ck(cutoff.a.b is env, "...and its own envelope")
ck(env.a == 0.0, "the envelope is a source: it rises from 0")
ck(env.b is s._fenv._amt, "depth IS the shared amount block at gain 1.0")
ck(env.c.waveform is s._fenv._wave, "position LFO reads the shared shape buffer")
ck(s._filt_lfo in engine.blocks, "the filter LFO must be in synth.blocks")

print("--- the envelope actually sweeps --------------------------------")
v0 = cutoff.value
settle(0.3)
v1 = cutoff.value
settle(0.5)
v2 = cutoff.value
print("      %.1f -> %.1f -> %.1f   (base 1000, peak 4000)" % (v0, v1, v2))
ck(v1 > v0 + 50, "rose during attack (%.1f -> %.1f)" % (v0, v1))
ck(v2 > 3500, "reached near peak, got %.1f" % v2)

print("--- PROBE: does a deep chain lag? --------------------------------")
# cutoff -> SUM -> env -> depth(_amt) is 4 levels. Blocks update every 256
# samples; if each level cost its own update, one write would take several
# updates to land at the top.
s.fenv_amount = 1500
settle(0.02)                      # ~1 block update at 44.1kHz is ~5.8ms
near = cutoff.value
settle(0.3)
later = cutoff.value
print("      after ~20ms: %.1f    after ~320ms: %.1f  (want ~2500)" % (near, later))
ck(abs(near - later) < 60,
   "a global write must land at the deepest node within one update, not "
   "propagate one level per update")
s.fenv_amount = 3000
settle(0.3)

print("--- globals stay O(1) while the voice sounds --------------------")
s.filt_f = 400
settle(0.15)
ck(abs(s._filt_f_blk.value - 400) < 0.001, "one write moved the shared cutoff")
ck(abs(cutoff.value - 3400) < 20, "the voice followed it: %.1f" % cutoff.value)
s.filt_f = 1000
settle(0.15)

print("--- the filter LFO reaches the voice ----------------------------")
AMT = 600
s.filt_lfo_amount = 0             # baseline: where the cutoff sits with no LFO
settle(0.15)
base_hz = cutoff.value
s.filt_lfo_amount = AMT
s.filt_lfo_rate = 2.0
settle(0.05)
lo = hi = cutoff.value
for _ in range(80):               # ~1.2s at 15ms: 2+ cycles, fine enough
    settle(0.015)                 # sampling to land near the true extrema
    v = cutoff.value
    lo = min(lo, v)
    hi = max(hi, v)
swing = hi - lo
print("      cutoff swung %.1f .. %.1f Hz  (width %.1f, want ~%d)"
      % (lo, hi, swing, AMT))
# bracket the WIDTH, not just "it moved": a > 200 check would also pass a
# half-wired LFO. The width is ~1*amount, not 2*amount, because the LFO is
# ADDITIVE -- filt_f is the floor and it opens upward. If this reads ~2*AMT
# the LFO's offset has been lost and the swing has recentred on filt_f.
# Discrete sampling can only under-read the extrema, hence the slack.
ck(0.75 * AMT < swing < 1.25 * AMT,
   "filt_lfo_amount must swing the cutoff by ~1*amount, got %.1f" % swing)
ck(lo > base_hz - 0.2 * AMT,
   "the LFO must never pull the cutoff BELOW its unmodulated base: floor "
   "%.1f, base %.1f" % (lo, base_hz))
ck(hi > base_hz + 0.75 * AMT,
   "...and must reach base+amount at its peak: %.1f vs %.1f"
   % (hi, base_hz + AMT))
s.filt_lfo_amount = 0
settle(0.2)

print("--- 10.6  in-place shape rewrite under a sounding voice ---------")
w = env.c.waveform
s.fenv_curve = 2
settle(0.1)
ck(env.c.waveform is w, "voice still points at the same buffer object")
ck(cutoff.value > 0, "voice still sane after the rewrite (%.1f)" % cutoff.value)
s.fenv_curve = 1
settle(0.4)

print("--- 10.3  release WITHOUT reassigning waveform ------------------")
peak = cutoff.value
s.note_off(60)
settle(0.02)
just_after = cutoff.value
ck(env.c.waveform is w, "release must NOT reassign the LFO waveform")
ck(abs(peak - just_after) < 150,
   "release starts where the attack got to: %.1f -> %.1f" % (peak, just_after))
settle(0.7)
print("      settled at %.1f (want ~1000 = base)" % cutoff.value)
ck(abs(cutoff.value - 1000) < 60, "release landed on the base (%.1f)" % cutoff.value)
s.all_notes_off()
settle(0.3)

print("--- release from MID-attack (the case that used to jump) --------")
s.note_on(60, velocity=127)
settle(0.25)
c = s.voices[60][0].filter.frequency
mid = c.value
s.note_off(60)
settle(0.02)
print("      %.1f -> %.1f" % (mid, c.value))
ck(abs(mid - c.value) < 150, "no jump on mid-attack release")
settle(0.7)
ck(abs(c.value - 1000) < 60, "still lands on base (%.1f)" % c.value)
s.all_notes_off()
settle(0.3)

print("--- curve=2 release must be a DECAY, not a mirrored attack -------")
# The one shape the software tiers can only check arithmetically. Note this
# runs at fenv_curve=2 on purpose: at curve=1 the correct and the broken
# shapes are identical, which is how a mirrored-attack release once shipped.
#   release(t) = V * (1 - s(t)), s = 1-(1-t)^2  =>  V*(1-t)^2
#   at halfway: 0.25 of the envelope's height. The old s = t^2 gave 0.75.
s.load_patch(Patch(filt_type="LPF", filt_f=1000, filt_q=1.2, fenv_amount=3000,
                   fenv_attack=0.1, fenv_release=1.0, fenv_curve=2,
                   amp_env=[0.01, 0.1, 0.8, 3.0]))
s.note_on(60, velocity=127)
settle(0.5)                       # well past the 0.1s attack, sitting at depth
e = s._fenvs[60]
v_start = e.value
s.note_off(60)
settle(0.5)                       # halfway through a 1.0s release
half = e.value
frac = half / v_start
print("      envelope %.1f -> %.1f at halfway (%.2f of its height)"
      % (v_start, half, frac))
ck(frac < 0.45,
   "a decay must be well past half by halfway, got %.2f -- above 0.5 means "
   "the envelope hangs at the top and then plunges" % frac)
ck(0.10 < frac < 0.42, "want ~0.25 for curve=2, got %.2f" % frac)
settle(0.8)
ck(e.value < 0.06 * v_start,
   "and it must reach the floor by the end (%.1f of %.1f)" % (e.value, v_start))
s.all_notes_off()
settle(0.3)

print("--- release really takes fenv_release seconds --------------------")
# the retired hold used to shrink the rise to _frac of the buffer, which
# forced _rate_r = _frac/release. With a full-buffer rise it is 1/release.
s.load_patch(Patch(filt_type="LPF", filt_f=1000, filt_q=1.2, fenv_amount=3000,
                   fenv_attack=0.1, fenv_release=0.5,
                   amp_env=[0.01, 0.1, 0.8, 3.0]))
s.note_on(60, velocity=127)
settle(0.4)                       # well past the attack
c = s.voices[60][0].filter.frequency
s.note_off(60)
t0 = time.monotonic()
while c.value > 1100 and time.monotonic() - t0 < 2.0:
    time.sleep(0.005)
took = time.monotonic() - t0
print("      release took %.2fs (set to 0.50s)" % took)
ck(0.35 < took < 0.70, "release duration must match fenv_release, got %.2fs" % took)
s.all_notes_off()
settle(0.3)

print("--- velocity -> cutoff (filt_vel), including negative ------------")
s.load_patch(Patch(filt_type="LPF", filt_f=1000, filt_vel=2000, filt_q=1.2,
                   fenv_amount=0, amp_env=[0.01, 0.1, 0.8, 0.2]))
s.note_on(60, velocity=127)
s.note_on(64, velocity=32)
settle(0.15)
hard = s.voices[60][0].filter.frequency
soft = s.voices[64][0].filter.frequency
print("      vel127 -> %.1f Hz    vel32 -> %.1f Hz" % (hard.value, soft.value))
ck(abs(hard.value - 3000.0) < 1.0, "vel 127 gives filt_f+filt_vel = 3000")
ck(abs(soft.value - (1000 + (32 / 127) * 2000)) < 1.0, "vel 32 scales correctly")
s.filt_f = 500
settle(0.15)
ck(abs(hard.value - 2500.0) < 1.0, "filt_f still O(1) through the per-voice block")
ck(abs(soft.value - (500 + (32 / 127) * 2000)) < 1.0, "...for every voice")
# filt_vel is a shared block now, so it reaches a voice already sounding
s.filt_vel = -400
settle(0.15)
ck(abs(hard.value - 100.0) < 1.0,
   "filt_vel must stay LIVE for a sounding voice, got %.1f" % hard.value)
s.all_notes_off()
settle(0.3)

print("--- velocity -> envelope depth (fenv_vel), live ------------------")
s.load_patch(Patch(filt_type="LPF", filt_f=1000, fenv_amount=3000, fenv_vel=1.0,
                   fenv_attack=0.3, fenv_release=0.3,
                   amp_env=[0.01, 0.1, 0.8, 0.2]))
s.note_on(60, velocity=127)
s.note_on(64, velocity=64)
settle(0.7)
h, sf = s._fenvs[60], s._fenvs[64]
print("      vel127 depth %.1f Hz   vel64 depth %.1f Hz" % (h.value, sf.value))
ck(abs(h.value - 3000) < 30, "full velocity depth = fenv_amount")
ck(abs(sf.value - 3000 * 64 / 127) < 30, "velocity 64 scales the depth")
s.fenv_vel = 0.0
settle(0.15)
ck(abs(sf.value - 3000) < 30,
   "fenv_vel must stay LIVE: dropping it restores full depth (%.1f)" % sf.value)
s.all_notes_off()
settle(0.3)

print("--- the cutoff bus clamps -----------------------------------------")
s.load_patch(Patch(filt_type="LPF", filt_f=1000, fenv_amount=-5000,
                   fenv_attack=0.2, fenv_release=0.2,
                   amp_env=[0.01, 0.1, 0.8, 1.0]))
s.note_on(60, velocity=127)
settle(0.5)
c = s.voices[60][0].filter.frequency
print("      downward sweep past zero settled at %.1f Hz" % c.value)
ck(abs(c.value - s.FILT_F_MIN) < 1.0, "must clamp at FILT_F_MIN, not go negative")
s.all_notes_off()
settle(0.3)

print("--- release continuity with the velocity terms ------------------")
for fv, filt_vel in ((0.0, 0), (0.75, 0), (0.75, 2000)):
    s.load_patch(Patch(filt_type="LPF", filt_f=1000, fenv_amount=3000,
                       fenv_vel=fv, filt_vel=filt_vel,
                       fenv_attack=0.5, fenv_release=0.5,
                       amp_env=[0.01, 0.1, 0.8, 2.0]))
    s.note_on(60, velocity=40)
    settle(0.25)
    c = s.voices[60][0].filter.frequency
    want = 1000 + filt_vel * 40 / 127
    v_before = c.value
    s.note_off(60)
    settle(0.02)
    ck(abs(v_before - c.value) < 150,
       "fenv_vel=%s filt_vel=%s: %.1f -> %.1f" % (fv, filt_vel, v_before, c.value))
    settle(0.9)
    ck(abs(c.value - want) < 60,
       "   ...and landed on base+velocity %.1f (got %.1f)" % (want, c.value))
    s.all_notes_off()
    settle(0.3)

print("--- the patch is NOT live state ----------------------------------")
pat = Patch(filt_type="LPF", filt_f=1000, wave="SAW", detune=1.0,
            amp_env=[0.01, 0.1, 0.8, 0.3], fenv_amount=2000)
s.load_patch(pat)
s.filt_f = 2500
s.attack_time = 0.4
s.wave = "SQU"
ck(pat.filt_f == 1000, "a knob turn must NOT reach the patch")
ck(pat.amp_env[0] == 0.01, "amp_env must be copied at load, not aliased")
ck(pat.wave == "SAW", "a subclass param must not reach the patch either")
ck(s.filt_f == 2500, "the getter must read live state")
s.save_patch()
ck(pat.filt_f == 2500 and pat.amp_env[0] == 0.4 and pat.wave == "SQU",
   "save_patch() must commit everything, subclass params included")

print("--- vib_delay: does the fade tick nested inside LFO.scale? -------")
# _vib_fade is NOT rooted in synth.blocks -- it is nested in _vib_lfo.scale,
# and _vib_lfo IS rooted. Unattached Math blocks were found to freeze, so
# this checks the nesting really is enough.
s.load_patch(Patch(filt_type="LPF", filt_f=2000, fenv_amount=0,
                   vib_depth=0.02, vib_rate=5.0, vib_delay=1.0,
                   amp_env=[0.01, 0.1, 0.9, 0.2]))
s.note_on(60, velocity=127)
settle(0.05)
scale_blk = s._vib_lfo.scale
readings = []
for _ in range(7):
    readings.append(scale_blk.value)
    settle(0.2)
print("      effective vib depth over 1.4s: "
      + " ".join("%.4f" % v for v in readings))
ck(readings[0] < 0.004, "vibrato must start at ~0 depth, got %.4f" % readings[0])
ck(readings[-1] > 0.016,
   "...and reach vib_depth once the fade completes, got %.4f" % readings[-1])
ck(all(readings[i] <= readings[i + 1] + 0.001 for i in range(len(readings) - 1)),
   "the fade must rise monotonically -- if it is flat at 0 the nested ramp "
   "is not ticking and _vib_fade needs rooting in synth.blocks")
s.all_notes_off()
settle(0.3)

print("--- vib fade retriggers from SILENCE, not per note ---------------")
s.note_on(60, velocity=127)
settle(0.6)                       # part-way up the fade
mid = s._vib_lfo.scale.value
s.note_on(64, velocity=127)       # add to the held chord
settle(0.05)
after = s._vib_lfo.scale.value
print("      depth %.4f before adding a note, %.4f after" % (mid, after))
ck(after >= mid - 0.001,
   "adding a note to a held chord must not duck the vibrato back to 0")
s.all_notes_off()
settle(0.4)
s.note_on(60, velocity=127)
settle(0.05)
fresh = s._vib_lfo.scale.value
print("      after silence, a new note restarts the fade at %.4f" % fresh)
ck(fresh < 0.004, "starting from silence must restart the fade, got %.4f" % fresh)
s.all_notes_off()
settle(0.3)

print("--- pitch envelope: bends INTO the note, then OUT of it -----------")
s.load_patch(Patch(filt_type="LPF", filt_f=3000, fenv_amount=0, vib_depth=0.0,
                   penv_amount=0.5, penv_time=0.4,
                   penv_out_amount=0.25, penv_out_time=0.4,
                   amp_env=[0.01, 0.1, 0.9, 1.5]))
s.note_on(60, velocity=127)
settle(0.03)
penv = s._penvs[60]
bend = s.voices[60][0].bend
ck(bend is not s._bend, "a voice with a pitch envelope gets its own bend node")
start = penv.value
settle(0.25)
partway = penv.value
settle(0.35)
settled = penv.value
print("      bend %.3f -> %.3f -> %.3f  (want 0.5 -> ~0.25 -> 0)"
      % (start, partway, settled))
ck(start > 0.42, "must start at penv_amount, got %.3f" % start)
ck(partway < start - 0.1, "must be falling toward pitch, got %.3f" % partway)
ck(abs(settled) < 0.03, "must settle on true pitch, got %.3f" % settled)

out_start = penv.value
s.note_off(60)
settle(0.03)
ck(abs(penv.value - out_start) < 0.05,
   "the bend-out must start where the note left off: %.3f -> %.3f"
   % (out_start, penv.value))
settle(0.6)
print("      after note-off, drifted to %.3f (want 0.25)" % penv.value)
ck(abs(penv.value - 0.25) < 0.04,
   "must drift to penv_out_amount, got %.3f" % penv.value)
s.all_notes_off()
settle(0.3)

print("--- pitch envelope costs nothing when off ------------------------")
s.load_patch(Patch(filt_type="LPF", filt_f=3000, fenv_amount=0))
s.note_on(60, velocity=127)
settle(0.05)
ck(60 not in s._penvs, "both amounts 0 must build no pitch envelope")
ck(s.voices[60][0].bend is s._bend,
   "...and every Note rides the shared bend graph directly")
s.all_notes_off()
settle(0.3)

print("--- AHREnvelope standalone, both directions ----------------------")
solo = AHREnvelope(attack=0.3, release=0.3, amount=1.0)
senv = solo.make()
engine.blocks.append(senv)
settle(0.7)
print("      rising:  %.3f (amount 1.0)" % senv.value)
ck(senv.value > 0.9, "standalone envelope rose to its amount")
solo.start_release(senv)
settle(0.5)
ck(senv.value < 0.15, "standalone envelope released to zero (%.3f)" % senv.value)
engine.blocks.remove(senv)

# The same class the other way up, which is all a pitch envelope is.
# NOTE the long attack: a falling envelope is already on its way down the
# instant it exists, so the first reading has to be taken while barely any
# of it has elapsed. At attack=0.3 a 0.05s settle is a sixth of the fall
# and reads ~0.83 -- correct behaviour, but useless as a "starts at its
# amount" check. At attack=1.5 the same settle is ~3%.
fall = AHREnvelope(attack=1.5, release=0.3, amount=1.0,
                   falling=True, release_amount=0.5)
fenv2 = fall.make()
engine.blocks.append(fenv2)
settle(0.05)
print("      falling: starts %.3f (3%% elapsed, want ~0.97)" % fenv2.value)
ck(fenv2.value > 0.9, "a falling envelope must START at its amount")
settle(2.0)
ck(abs(fenv2.value) < 0.06, "...and settle to 0 (%.3f)" % fenv2.value)
fall.start_release(fenv2)
settle(0.6)
print("      falling: released to %.3f (want 0.5)" % fenv2.value)
ck(abs(fenv2.value - 0.5) < 0.06,
   "...then release to release_amount, not to 0 (%.3f)" % fenv2.value)
engine.blocks.remove(fenv2)

mixer.voice[0].level = 0.25
print()
print("FAILURES: %d" % len(fails))
for f in fails:
    print("  -", f)
print("DONE")
