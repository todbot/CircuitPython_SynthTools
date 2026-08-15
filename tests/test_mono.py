# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Wiring checks for Synth's mono/glide mode and BasslineSynth.

Three things here are load-bearing and none of them is obvious:

1. MONO is a switch on Synth, not a subclass: any style can flip it and
   get one-voice stealing plus portamento. GLIDE is the third input of
   Synth's shared bend SUM, inert (0.0) while poly.
2. The 303's DECAY-ONLY filter envelope is Synth's ordinary rising AHR
   envelope with a NEGATIVE amount -- so the cutoff falls from filt_f while
   the key is still down, which AHR is documented as unable to do in its
   usual (positive) direction.
3. ACCENT must not contaminate the patch. It writes spare block inputs
   (_filt_sum.c, _filt_q_blk.b) so that filt_f/filt_q read back as the knob
   values and save_patch() stores knob positions, not accented ones.

Note the stub's LFO does NOT interpolate between waveform samples the way
real synthio does, so a 2-point ramp reads 0.0 until its phase reaches the
end. Nothing below depends on a partially-completed ramp's value.

    python3 tests/test_mono.py
    micropython tests/test_mono.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/stubs")
sys.path.insert(0, _D + "/..")

import synthio  # noqa: E402
from synthtools import BasslineSynth, Patch, SubtractiveSynth  # noqa: E402

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


def make(**kw):
    kw.setdefault("wave", "SAW")
    return BasslineSynth(synthio.Synthesizer(), Patch(**kw))


# --- glide occupies the bend SUM's third input ---------------------------
# Synth builds _bend = SUM(vib_lfo, bend_blk, glide). In poly nothing ever
# writes _glide.a, so the node is there but contributes nothing.

syn = make(filt_f=2000, envmod=0.5)
ck(syn._bend.c is syn._glide, "glide must occupy the shared bend SUM's third input")
ck(syn._glide.b == 0.0, "a glide must always END on the note's own pitch")
ck(syn._bend in syn.synthio.blocks, "the bend graph must stay rooted, so the glide LFO ticks")
ck(syn._glide_pos not in syn.synthio.blocks,
   "the glide LFO must NOT be rooted separately -- it is reachable through "
   "_bend, exactly like _vib_fade inside _vib_lfo.scale")

# a POLY synth carries the same node, silent and unwritten
poly = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0))
ck(poly.mono is False, "Synth must default to polyphonic")
ck(poly._glide.a == 0.0 and poly._glide.value == 0.0,
   "the glide node must contribute nothing until mono writes it")
poly.note_on(60)
poly.note_on(64)
ck(len(poly.voices) == 2, "a poly synth must still stack voices")
ck(poly._glide.a == 0.0, "a poly note-on must not aim the glide")

# two instances must not share one glide graph: these are blocks, so the
# class-attribute trick SubtractiveSynth uses for _wave_name cannot apply
other = make()
ck(other._glide is not syn._glide, "each instance needs its OWN glide blocks")

# --- mono is a SWITCH, so any style gets a monosynth ---------------------
# This is the whole reason it lives on Synth rather than in a subclass:
# SubtractiveSynth with mono set is a portamento lead, and no separate
# class had to exist for it.

lead = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0, glide_time=0.08))
lead.mono = True
lead.note_on(60)
lead.note_on(64)
ck(len(lead.voices) == 1 and 64 in lead.voices,
   "mono must steal the sounding voice whatever note it was, not only a "
   "re-press of the same one")
ck(abs(lead._glide.a - (60 - 64) / 12.0) < 1e-9,
   "a mono note-on must aim the glide from the previous note, got %r" % lead._glide.a)
ck(lead.voices[64][0].bend is lead._bend,
   "the voice must read the SHARED bend, which is what carries the glide")
lead.note_off(64)
ck(not lead.voices, "note_off must still work normally in mono")

# BasslineSynth is mono without being told
ck(BasslineSynth.mono is True, "a bassline synth is inherently monophonic")

# --- glide aims from the previous note, in octaves -----------------------

syn.all_notes_off()
syn.note_on_step(36)
ck(syn._glide.a == 0.0, "the first note ever has nothing to glide from")
syn.note_on_step(48, slide=True)
ck(abs(syn._glide.a - (-1.0)) < 1e-9,
   "gliding up an octave must start one octave BELOW the new note "
   "(bend units are octaves), got %r" % syn._glide.a)

# interrupting a glide must start the next one from where the pitch IS,
# not from the interrupted target -- the same structural continuity as
# AHREnvelope.start_release()'s `env.a = env.value`
mid = syn._glide.value
syn.note_on_step(60, slide=True)
ck(abs(syn._glide.a - ((48 - 60) / 12.0 + mid)) < 1e-9,
   "an interrupted glide must carry its in-flight value into the next one")

# --- the decay-only filter envelope --------------------------------------
# fenv_amount is NEGATIVE, so the ordinary rising AHR shape sweeps the
# cutoff DOWN from filt_f while the key is still held. This is the one
# gesture AHR is documented as unable to make in its positive direction.

syn = make(filt_f=4000, envmod=0.5, fenv_attack=0.2, fenv_curve=2)
ck(syn.fenv_amount == -2000.0,
   "envmod is a FRACTION of filt_f: 0.5 of 4000 must be -2000 Hz, got %r" % syn.fenv_amount)
syn.filt_f = 2000
ck(syn.fenv_amount == -1000.0, "moving the cutoff must move the sweep with it")
syn.envmod = 1.0
ck(syn.fenv_amount == -2000.0, "envmod must re-derive from the current filt_f")

syn.filt_f = 4000
syn.envmod = 0.5
syn.all_notes_off()
syn.note_on_step(36)
cutoff = syn.voices[36][0].filter.frequency
env = syn._fenvs[36]
env.c.phase = 0.0
top = cutoff.value
env.c.phase = 1.0
bottom = cutoff.value
ck(abs(top - 4000.0) < 1e-6, "the sweep must START at filt_f, got %r" % top)
ck(abs(bottom - 2000.0) < 1e-6, "the sweep must LAND at filt_f+amount, got %r" % bottom)
ck(bottom < top, "a 303 filter envelope must fall, not rise")

# envmod = 1.0 aims the sweep at 0 Hz, and the clamp is what catches it
syn = make(filt_f=1000, envmod=1.0, fenv_attack=0.1)
syn.note_on_step(36)
syn._fenvs[36].c.phase = 1.0
ck(syn.voices[36][0].filter.frequency.value == syn.FILT_F_MIN,
   "envmod=1.0 drives the cutoff to zero; FILT_F_MIN must clamp it")

# envmod = 0 must cost nothing at all, and accent must still revive it
syn = make(filt_f=3000, envmod=0.0)
syn.note_on_step(36)
ck(36 not in syn._fenvs, "envmod=0 must build no per-voice envelope node")
syn.note_on_step(38, accent=True)
ck(38 in syn._fenvs,
   "an accented step raises the depth off zero, so the node must exist -- "
   "the depth has to be written BEFORE the press or make() skips it")

# filt_type=None in mono: the voice gets no filter at all, and the cutoff
# property is the one place the two can disagree
nofilt = make(filt_type=None, envmod=0.75)
nofilt.note_on_step(36)
ck(nofilt.voices[36][0].filter is None, "filt_type=None must give the voice no filter")
ck(nofilt.filter is None,
   "...and nothing downstream can track a filter that does not exist")
nofilt.all_notes_off()

# --- accent must not contaminate the patch -------------------------------
# Every accent target is a shared block that Synth also reads back for
# save_patch(). Accent therefore writes SPARE inputs of those blocks.

syn = make(filt_f=2000, filt_q=1.4, envmod=0.6, accent=0.5,
           accent_cutoff=4000.0, accent_q=0.6, amp_level=0.8)
patch = syn.patch

syn.note_on_step(36, accent=False)
plain = syn.voices[36][0]
ck(plain.filter.frequency.value == 2000.0, "an un-accented step sits at filt_f")
ck(plain.filter.Q.value == 1.4, "an un-accented step sits at filt_q")
ck(plain.envelope.attack_level == 0.8, "an un-accented step plays at amp_level")

syn.note_on_step(38, accent=True)
acc = syn.voices[38][0]
ck(acc.filter.frequency.value == 4000.0,
   "accent must ADD accent_cutoff*accent Hz, got %r" % acc.filter.frequency.value)
ck(abs(acc.filter.Q.value - 1.7) < 1e-9,
   "accent must add accent_q*accent to the resonance, got %r" % acc.filter.Q.value)
ck(acc.envelope.attack_level == 1.0, "accent must raise the level")
ck(acc.envelope is not plain.envelope,
   "the accented Envelope must be a separate cached object, not a rebuild")

# ...and the knobs must still read back as the KNOBS
ck(syn.filt_f == 2000, "filt_f must read back clean during an accented note, got %r" % syn.filt_f)
ck(syn.filt_q == 1.4, "filt_q must read back clean during an accented note, got %r" % syn.filt_q)
ck(syn.envmod == 0.6, "envmod must read back clean during an accented note")

syn.save_patch()
ck(patch.filt_f == 2000 and patch.filt_q == 1.4,
   "save_patch() during an accented note must store the KNOB values, not the "
   "accented ones -- got filt_f=%r filt_q=%r" % (patch.filt_f, patch.filt_q))
ck(patch.fenv_amount == -1200.0,
   "fenv_amount is derived from envmod, so it must be saved un-accented "
   "(-0.6*2000), got %r" % patch.fenv_amount)
ck(patch.envmod == 0.6 and patch.accent == 0.5, "the 303 knobs must round-trip")

# an un-accented step must put every one of them back
syn.note_on_step(40, accent=False)
back = syn.voices[40][0]
ck(back.filter.frequency.value == 2000.0, "an un-accented step must clear the cutoff boost")
ck(back.filter.Q.value == 1.4, "an un-accented step must clear the resonance boost")
ck(back.envelope.attack_level == 0.8, "an un-accented step must clear the level boost")

# --- patch round-trip ----------------------------------------------------

syn = make(filt_f=1800, envmod=0.7, accent=0.3, slide_time=0.08,
           transpose=-12, amp_level=0.7, glide_time=0.05, wave="SQU")
p2 = Patch.from_json(syn.save_patch().to_json())
again = BasslineSynth(synthio.Synthesizer(), p2)
for name in ("filt_f", "envmod", "accent", "slide_time", "transpose",
             "amp_level", "glide_time", "wave", "fenv_amount"):
    ck(getattr(again, name) == getattr(syn, name),
       "%s must survive a save/load round-trip: %r != %r"
       % (name, getattr(again, name), getattr(syn, name)))

# a patch written before any of these fields existed must still load
legacy = BasslineSynth(synthio.Synthesizer(), Patch.from_json('{"name":"old","filt_f":900}'))
ck(legacy.envmod == 0.5 and legacy.accent == 0.5 and legacy.wave == "SAW",
   "an older patch must load on defaults rather than raising")
ck(legacy.glide_time == 0.0, "glide_time must default to no portamento")

# --- set_param covers the new knobs --------------------------------------

syn = make()
for name in ("glide_time", "envmod", "decay", "accent", "wave",
             "accent_cutoff", "accent_q", "slide_time", "transpose", "amp_level"):
    ck(name in syn._PARAMS, "%s must be reachable via set_param()" % name)
syn.set_param("envmod", 0.9)
ck(syn.envmod == 0.9, "set_param must reach the property")
ck("mono" not in syn._PARAMS,
   "mono is a plain attribute like push_env, NOT a patch field -- listing it "
   "in _PARAMS without a matching _decompile() line is the silent-save trap")

# decay is the FILTER fall time only. Tying it to the amp decay as well
# (an earlier version did) makes envmod nearly inaudible: the note fades
# at the same rate the cutoff falls, so the sweep is masked by the
# amplitude and the pair just reads as a pluck.
syn.decay = 0.3
ck(syn.fenv_attack == 0.3, "decay must set the filter fall time")
ck(syn.decay == 0.3, "decay must read back what was written")
before = syn.amp_env[1]
syn.decay = 0.05
ck(syn.amp_env[1] == before,
   "decay must NOT touch the amp envelope -- the amp has to be able to "
   "outlive the sweep, which is what makes the sweep audible")

if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_mono: all checks passed")
