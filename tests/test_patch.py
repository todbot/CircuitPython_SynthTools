# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Patch round-trip checks -- the one module that needs no stubs at all.

patch.py imports only `json`, so this runs on a bare interpreter and is
the cheapest place to catch the MicroPython idiom bugs listed in
CLAUDE-synthlib.md section 7 (read-only instance __dict__, dict.update
keywords).

    python3 tests/test_patch.py
    micropython tests/test_patch.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/../synthtools")   # direct: skips synthtools/__init__

from patch import Patch, save_patches, load_patches  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


p = Patch()
ck(p.name == "init", "default name")
ck(p.fenv_curve == 1, "default fenv_curve should be linear")
ck(isinstance(p.amp_env, list),
   "amp_env must be a list, not a tuple: JSON round-trips it as a list and a "
   "tuple would make a fresh patch behave differently from a reloaded one")

# in-place stage edit, the reason amp_env is a list
p.amp_env[0] = 0.5
ck(p.amp_env[0] == 0.5, "amp_env must support in-place stage assignment")

# unknown kwargs must land in __dict__ and survive -- this is the setattr
# loop standing in for self.__dict__.update(kw), which raises TypeError on
# CircuitPython because the instance __dict__ is a read-only mapping
p2 = Patch(wave_file="/wt.wav", wave_pos=3.5, synth_type="wavetable")
ck(p2.wave_file == "/wt.wav", "unknown kwargs must be settable")
r = Patch.from_json(p2.to_json())
ck(r.wave_file == "/wt.wav" and r.wave_pos == 3.5,
   "style-specific fields must round-trip without subclassing")

p3 = Patch(wave_pos_max=5.5, wave_lfo_rate=1.25, wave_lfo_shape="saw",
           wave_lfo_once=True, wave_lfo_vel=0.75)
r3 = Patch.from_json(p3.to_json())
ck(r3.wave_pos_max == 5.5 and r3.wave_lfo_rate == 1.25
   and r3.wave_lfo_shape == "saw" and r3.wave_lfo_once is True
   and r3.wave_lfo_vel == 0.75,
   "wave-LFO fields must round-trip without subclassing, like wave_pos/wave_file")

legacy2 = Patch.from_json('{"name":"old","filt_f":900}')
ck(not hasattr(legacy2, "wave_pos_max"),
   "a patch saved before the wave-position LFO existed must simply lack "
   "the field -- WavetableSynth._recompile()'s getattr(p, 'wave_pos_max', "
   "wave_pos) supplies the off default, same as wave_pos/wave_file today")

ck(p.filt_vel == 0, "default filt_vel should be 0 (velocity changes nothing)")
ck(p.fenv_vel == 0.0, "default fenv_vel should be 0.0")
ck(p.filt_lfo_amount == 0, "default filt_lfo_amount should be 0 (LFO off)")
ck(p.vib_delay == 0.0, "default vib_delay should be 0 (vibrato immediate)")
ck(p.penv_amount == 0.0 and p.penv_out_amount == 0.0,
   "both pitch-envelope amounts should default to 0 = off")
ck(not hasattr(p, "fenv_hold"),
   "fenv_hold was retired: with once=True the LFO already holds its last "
   "sample forever, so a hold segment was unreachable")

full = Patch(name="curvy", fenv_curve=3, filt_f=1234, fenv_amount=2500,
             filt_vel=-2000, fenv_vel=0.6,
             filt_lfo_rate=2.5, filt_lfo_amount=800,
             vib_delay=1.5, penv_amount=-0.4, penv_time=0.08,
             penv_out_amount=0.25, penv_out_time=0.3)
back = Patch.from_json(full.to_json())
for k in ("name", "fenv_curve", "filt_f", "fenv_amount", "detune", "filt_type",
          "filt_vel", "fenv_vel", "filt_lfo_rate", "filt_lfo_amount",
          "vib_delay", "penv_amount", "penv_time",
          "penv_out_amount", "penv_out_time"):
    ck(getattr(back, k) == getattr(full, k), "field %r must round-trip" % k)
ck(back.filt_vel == -2000, "filt_vel is signed: negative must survive")
ck(back.penv_amount == -0.4,
   "penv_amount is signed too: negative means bending UP into the note")

# every field added over time must default cleanly on an older patch file
legacy = Patch.from_json('{"name":"old","filt_f":900}')
ck(legacy.fenv_curve == 1,
   "a patch saved before fenv_curve existed must load with the default")
ck(legacy.filt_vel == 0 and legacy.fenv_vel == 0.0,
   "a patch saved before the velocity params existed must default to no response")
ck(legacy.filt_lfo_amount == 0 and legacy.filt_lfo_rate == 0.5,
   "a patch saved before the filter LFO existed must default to off")
ck(legacy.penv_amount == 0.0 and legacy.penv_out_amount == 0.0,
   "a patch saved before the pitch envelope existed must default to off")

# ...and a field that has since been REMOVED must not break loading. The
# setattr loop keeps it as an inert extra; the engine simply ignores it.
retired = Patch.from_json('{"name":"old","fenv_hold":0.25,"filt_f":900}')
ck(retired.fenv_hold == 0.25 and retired.filt_f == 900,
   "a retired field must load as a harmless extra rather than raising")

ck(Patch.from_dict(full.to_dict()).name == "curvy", "to_dict/from_dict round-trip")

if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_patch: all checks passed")
