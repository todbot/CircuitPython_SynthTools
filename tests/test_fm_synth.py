# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Integration checks for FMSynth against the synthio stubs.

Proves the design in fm_synth.py holds: FM here is a baked phase-modulation
CARRIER TABLE (sin(theta + index*sin(ratio*theta))), not a live audio-rate
modulator on note.bend -- synthio's Math/LFO blocks only update once every
256 samples (172 Hz), which aliases any modulator above ~86 Hz, so a
bend-based design cannot render real FM sidebands at any setting. See the
module docstring in fm_synth.py for the full reasoning.

This file checks: the table is ONE shared buffer that every FM-on voice's
waveform points at (not a per-voice copy), that fm_ratio/fm_index rewrite it
in place and reach voices already sounding, that fm_index 0 falls back to
the plain `wave` oscillator at ordinary Synth cost, and that fm_ratio always
rounds to a non-negative integer even from float/patch input.

No DSP: the stubs do not resample or render audio, so this cannot check the
table's actual waveform content -- only identity and wiring. Correctness of
fill_pm_wave() itself (sideband placement, wrap continuity) is a numeric
question for real numpy, not these stubs; sanity-check it in the scratchpad
with an FFT if the formula changes.

    python3 tests/test_fm_synth.py
    micropython tests/test_fm_synth.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/stubs")
sys.path.insert(0, _D + "/..")

import synthio  # noqa: E402
import synthtools  # noqa: E402
from synthtools import Patch, FMSynth  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


# --- Patch defaults and JSON round-trip ----------------------------------
p = Patch()
ck(p.fm_ratio == 1, "default fm_ratio must be 1, got %r" % p.fm_ratio)
ck(p.fm_index == 0.0, "default fm_index must be 0 (FM off), got %r" % p.fm_index)
ck("fm_index" in p.to_dict() and "fm_ratio" in p.to_dict(),
   "both fm fields must appear in to_dict()")
ck(Patch.from_json(Patch(fm_ratio=3, fm_index=1.5).to_json()).fm_ratio == 3,
   "fm_ratio must survive a JSON round-trip")
ck(Patch.from_json('{"name":"old"}').fm_ratio == 1,
   "a legacy patch without fm fields must default to ratio 1, index 0")
# a legacy patch with the OLD fm_wave field must still load without error
ck(Patch.from_json('{"name":"old","fm_wave":"SQU"}').fm_ratio == 1,
   "a patch with the removed fm_wave field must still load (inert extra)")

# --- the whitelist and the FM defaults on the engine ---------------------
sio = synthio.Synthesizer()
s = FMSynth(sio, Patch(filt_f=1000, fenv_amount=3000,
                       fm_ratio=2, fm_index=1.0, wave="TRI"))
for name in ("fm_ratio", "fm_index", "wave"):
    ck(name in s._PARAMS, "%s must be in the _PARAMS whitelist" % name)
ck("fm_wave" not in s._PARAMS, "fm_wave must be gone: sine-carrier/sine-modulator only")
ck(s.fm_ratio == 2, "synth.fm_ratio must read the patch through _recompile")
ck(s.fm_index == 1.0, "synth.fm_index must read the patch through _recompile")
ck(s.wave == "TRI", "synth.wave must read the patch through _recompile")

# --- fm_ratio always rounds to a non-negative integer --------------------
s.fm_ratio = 3.6
ck(s.fm_ratio == 4, "fm_ratio must round to the nearest integer, got %r" % s.fm_ratio)
s.fm_ratio = -2
ck(s.fm_ratio == 0, "fm_ratio must clamp to non-negative, got %r" % s.fm_ratio)
s.fm_ratio = 2  # restore for the rest of the checks below

# --- FM on: the shared table, not a per-voice node ------------------------
pm_wave = s._pm_wave
ck(pm_wave is not None, "the shared PM table must exist")
s.note_on(60, velocity=100)
n = s.voices[60][0]
ck(n.waveform is pm_wave, "an FM-on voice's waveform must be the shared PM table")
ck(n.bend is s._bend, "FM no longer touches bend at all -- must be the plain shared bend")

# --- every FM-on voice shares the SAME table object -----------------------
s.note_on(64, velocity=80)
n2 = s.voices[64][0]
ck(n2.waveform is pm_wave, "a second voice must point at the SAME shared table")
ck(n2.waveform is n.waveform, "both voices' waveform must be identical, not copies")

# --- ratio/index rewrite the table in place, reaching sounding voices -----
before = list(pm_wave)
s.fm_index = 2.5
after = list(pm_wave)
ck(before != after, "changing fm_index must rewrite the shared table's contents")
ck(n.waveform is pm_wave and n2.waveform is pm_wave,
   "the rewrite must happen IN PLACE -- both sounding voices keep the same buffer identity")

# --- FM off: falls back to the plain oscillator, no PM table involved -----
s.all_notes_off()
s2 = FMSynth(sio, Patch(fm_index=0.0, wave="SQU"))
s2.note_on(64)
ck(s2.voices[64][0].waveform is not s2._pm_wave,
   "fm_index 0 must use the plain `wave` oscillator, not the PM table")

# --- set_param string interface -------------------------------------------
s.set_param("fm_ratio", 3)
ck(s.fm_ratio == 3, "set_param must reach the fm_ratio property")
try:
    s.set_param("no_such_fm_param", 1)
    fails.append("set_param must reject an unknown name")
except KeyError:
    pass

# --- patch is NOT live state; save_patch commits --------------------------
pat = Patch(name="fm", fm_ratio=2, fm_index=1.0, wave="TRI", filt_f=1000)
s3 = FMSynth(sio, pat)
s3.fm_ratio = 5
s3.fm_index = 0.25
s3.wave = "ASAW"
ck(pat.fm_ratio == 2, "a knob turn must NOT reach the patch")
ck(pat.wave == "TRI", "a subclass waveform turn must not reach the patch either")
ret = s3.save_patch()
ck(ret is pat, "save_patch() must return the loaded patch object")
ck(pat.fm_ratio == 5 and pat.fm_index == 0.25,
   "save_patch() must commit the fm fields")
ck(pat.wave == "ASAW", "save_patch() must commit the waveform field too")

# reloading from a new patch reverts live state
p2 = Patch(name="other", fm_ratio=3, fm_index=2.0)
s3.load_patch(p2)
ck(s3.fm_ratio == 3 and s3.fm_index == 2.0,
   "load_patch must overwrite live FM state")

# --- a legacy patch with no fm fields must LOAD and PLAY -------------------
legacy = Patch.from_json('{"name":"old","filt_f":900,"wave":"SQU"}')
s3.load_patch(legacy)
ck(s3.fm_ratio == 1 and s3.fm_index == 0.0,
   "a pre-FM patch must load with FM off and ratio 1")
s3.note_on(60)
ck(60 in s3.voices, "a legacy patch must still play")
ck(s3.voices[60][0].waveform is not s3._pm_wave,
   "and as FM is off it must use the plain oscillator, not the PM table")

print()
if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_fm_synth: all checks passed")
s2.all_notes_off()
