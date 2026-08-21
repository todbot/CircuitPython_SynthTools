# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Integration checks for FMSynth against the synthio stubs.

Proves the FM design from fm_synth.py holds: that a per-voice audio-rate
modulator rides on note.bend, that its ratio and index are SHARED blocks
nested under it (so each knob is one write that stays live for sounding
voices), and that index 0 builds no per-voice node at all -- the plain-Synth
zero-allocation case.

    VOICE  note.bend = SUM(shared_bend_graph, fm_lfo)
           fm_lfo    = LFO(waveform = shared fm_wave,
                           rate     = PRODUCT(carrier_hz, fm_ratio_blk),
                           scale    = fm_index_blk, offset = 0)

No DSP: the stubs do not render audio.

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
ck(p.fm_ratio == 1.0, "default fm_ratio must be 1.0, got %r" % p.fm_ratio)
ck(p.fm_index == 0.0, "default fm_index must be 0 (FM off), got %r" % p.fm_index)
ck(p.fm_wave == "SIN", "default fm_wave must be SIN, got %r" % p.fm_wave)
ck("fm_index" in p.to_dict() and "fm_ratio" in p.to_dict() and "fm_wave" in p.to_dict(),
   "all three fm fields must appear in to_dict()")
ck(Patch.from_json(Patch(fm_ratio=3.0, fm_index=1.5, fm_wave="TRI").to_json()).fm_ratio == 3.0,
   "fm_ratio must survive a JSON round-trip")
ck(Patch.from_json('{"name":"old"}').fm_ratio == 1.0,
   "a legacy patch without fm fields must default to ratio 1, index 0")

# --- the whitelist and the FM defaults on the engine ---------------------
sio = synthio.Synthesizer()
s = FMSynth(sio, Patch(filt_f=1000, fenv_amount=3000,
                       fm_ratio=2.0, fm_index=1.0, fm_wave="SQU", wave="TRI"))
for name in ("fm_ratio", "fm_index", "fm_wave", "wave"):
    ck(name in s._PARAMS, "%s must be in the _PARAMS whitelist" % name)
ck(s.fm_ratio == 2.0, "synth.fm_ratio must read the patch through _recompile")
ck(s.fm_index == 1.0, "synth.fm_index must read the patch through _recompile")
ck(s.fm_wave == "SQU", "synth.fm_wave must read the patch through _recompile")
ck(s.wave == "TRI", "synth.wave must read the patch through _recompile")

# --- FM on: the voice graph ----------------------------------------------
# Shared blocks, made once in __init__: writing them later must not change
# identity, because a sounding voice holds references straight to them.
ratio_blk = s._fm_ratio_blk
index_blk = s._fm_index_blk
ck(ratio_blk is not None and index_blk is not None, "FM blocks must exist")
s.note_on(60, velocity=100)
n = s.voices[60][0]
ck(n.bend.operation == "SUM", "an FM voice's bend must be a SUM of the shared bend and the modulator")
ck(n.bend.a is s._bend, "the first SUM input must be the shared bend graph")
lfo = n.bend.b
ck(hasattr(lfo, "waveform") and hasattr(lfo, "scale"),
   "the second SUM input must be the modulator LFO")
ck(lfo.scale is s._fm_index_blk, "the LFO scale MUST BE the shared index block")
ck(lfo.rate.operation == "PRODUCT", "the LFO rate must be a PRODUCT")
ck(abs(lfo.rate.a - synthio.midi_to_hz(60)) < 1e-6,
   "the rate's first input must be the carrier frequency in Hz")
ck(lfo.rate.b is s._fm_ratio_blk, "the rate's second input MUST BE the shared ratio block")
ck(lfo.waveform is s._fm_wave, "the modulator must read the shared waveform buffer")
ck(lfo.offset == 0.0, "centred FM: offset must be 0 so the swing is +/-index")

# --- every voice gets its OWN modulator; the shared parts stay shared ------
s.note_on(64, velocity=80)
n2 = s.voices[64][0]
ck(n2.bend.operation == "SUM", "a second voice must also get a bend SUM")
ck(n2.bend.b is not lfo,
   "each voice must carry its OWN modulator LFO (rate bakes in its own pitch)")
ck(n2.bend.b.scale is s._fm_index_blk,
   "but that voice's LFO scale must still be the same shared index block")
ck(n2.bend.b.rate.b is s._fm_ratio_blk,
   "and its rate must still nest the same shared ratio block")

# --- ratio and index stay LIVE for a voice already sounding ---------------
ck(lfo.rate.b.a == 2.0, "before: ratio is 2.0")
ck(lfo.scale.a == 1.0, "before: index is 1.0")
s.fm_ratio = 4.0
ck(lfo.rate.b.a == 4.0, "one write to fm_ratio must reach the sounding voice")
s.fm_index = 1.5
ck(lfo.scale.a == 1.5, "one write to fm_index must reach the sounding voice")

# --- FM off: no per-voice node at all -------------------------------------
# index 0 is the plain-Synth cost case: note.bend is literally the shared
# graph, with no SUM and no per-voice LFO allocated.
s.all_notes_off()
s2 = FMSynth(sio, Patch(fm_index=0.0))
s2.note_on(64)
ck(s2.voices[64][0].bend is s2._bend,
   "fm_index 0 must leave note.bend as the SHARED graph, no extra node")
# --- set_param string interface -------------------------------------------
s.set_param("fm_ratio", 3.0)
ck(s.fm_ratio == 3.0, "set_param must reach the fm_ratio property")
s.set_param("fm_wave", "SAW")
ck(s.fm_wave == "SAW", "set_param must reach the fm_wave property")
try:
    s.set_param("no_such_fm_param", 1)
    fails.append("set_param must reject an unknown name")
except KeyError:
    pass

# --- patch is NOT live state; save_patch commits --------------------------
pat = Patch(name="fm", fm_ratio=2.0, fm_index=1.0, fm_wave="SIN", wave="TRI", filt_f=1000)
s3 = FMSynth(sio, pat)
s3.fm_ratio = 5.0
s3.fm_index = 0.25
s3.fm_wave = "ATRI"
s3.wave = "ASAW"
ck(pat.fm_ratio == 2.0, "a knob turn must NOT reach the patch")
ck(pat.wave == "TRI", "a subclass waveform turn must not reach the patch either")
ret = s3.save_patch()
ck(ret is pat, "save_patch() must return the loaded patch object")
ck(pat.fm_ratio == 5.0 and pat.fm_index == 0.25,
   "save_patch() must commit the fm fields")
ck(pat.fm_wave == "ATRI" and pat.wave == "ASAW",
   "save_patch() must commit the waveform fields too")

# reloading from a new patch reverts live state
p2 = Patch(name="other", fm_ratio=3.0, fm_index=2.0, fm_wave="SAW")
s3.load_patch(p2)
ck(s3.fm_ratio == 3.0 and s3.fm_index == 2.0,
   "load_patch must overwrite live FM state")

# --- a legacy patch with no fm fields must LOAD and PLAY -------------------
legacy = Patch.from_json('{"name":"old","filt_f":900,"wave":"SQU"}')
s3.load_patch(legacy)
ck(s3.fm_ratio == 1.0 and s3.fm_index == 0.0,
   "a pre-FM patch must load with FM off and ratio 1")
s3.note_on(60)
ck(60 in s3.voices, "a legacy patch must still play")
ck(s3.voices[60][0].bend is s3._bend,
   "and as FM is off it must use the shared bend with no extra node")

print()
if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_fm_synth: all checks passed")
s2.all_notes_off()