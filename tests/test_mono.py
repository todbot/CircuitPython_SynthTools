# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Wiring checks for Synth's mono/glide mode and BasslineSynth.

Three things here are load-bearing and none of them is obvious:

1. MONO is a switch on Synth, not a subclass: any style can flip it and
   get one-voice stealing plus portamento. GLIDE is the third input of
   Synth's shared bend SUM, inert (0.0) while poly.
2. The 303's DECAY-ONLY filter envelope is Synth's ordinary rising AHR
   envelope with a NEGATIVE amount, so the cutoff falls from filt_f while
   the key is still down, which AHR is documented as unable to do in its
   usual (positive) direction.
3. ACCENT must not contaminate the patch. It writes spare block inputs
   (_filt_sum.c, _filt_q_blk.b) so that filt_f/filt_q read back as the knob
   values and save_patch() stores knob positions, not accented ones.

Note the stub's LFO does NOT interpolate between waveform samples the way
real synthio does, so a 2-point ramp reads 0.0 until its phase reaches the
end. Nothing below depends on a partially-completed ramp's value; where a
ramp has to have ARRIVED (the accent lag) settled() says so explicitly.

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


def settled(s):
    """Run the accent lag out to its end, and return the synth.

    The lag is a one-shot ramp, and the stub LFO does NOT interpolate: it
    reads waveform[0], i.e. 0.0, for every phase below 1.0. So anything
    reading an accented cutoff has to put the lag where it will actually be
    a few tens of milliseconds into the note, or it reads the un-accented
    value and proves nothing. See BasslineSynth.ACCENT_LAG.
    """
    s._accent_lag.phase = 1.0
    return s


# --- glide occupies the bend SUM's third input ---------------------------
# Synth builds _bend = SUM(vib_lfo, bend_blk, glide). In poly nothing ever
# writes _glide.a, so the node is there but contributes nothing.

syn = make(filt_f=2000, envmod=0.5)
ck(syn._bend.c is syn._glide, "glide must occupy the shared bend SUM's third input")
ck(syn._glide.b == 0.0, "a glide must always END on the note's own pitch")
ck(syn._bend in syn.synthio.blocks, "the bend graph must stay rooted, so the glide LFO ticks")
ck(
    syn._glide_pos not in syn.synthio.blocks,
    "the glide LFO must NOT be rooted separately: it is reachable through "
    "_bend, exactly like _vib_fade inside _vib_lfo.scale",
)

# a POLY synth carries the same node, silent and unwritten
poly = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0))
ck(poly.mono is False, "Synth must default to polyphonic")
ck(
    poly._glide.a == 0.0 and poly._glide.value == 0.0,
    "the glide node must contribute nothing until mono writes it",
)
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
ck(
    len(lead.voices) == 1 and 64 in lead.voices,
    "mono must steal the sounding voice whatever note it was, not only a re-press of the same one",
)
ck(
    abs(lead._glide.a - (60 - 64) / 12.0) < 1e-9,
    "a mono note-on must aim the glide from the previous note, got %r" % lead._glide.a,
)
ck(
    lead.voices[64][0].bend is lead._bend,
    "the voice must read the SHARED bend, which is what carries the glide",
)
lead.note_off(64)
ck(not lead.voices, "note_off must still work normally in mono")

# BasslineSynth is mono without being told
ck(BasslineSynth.mono is True, "a bassline synth is inherently monophonic")

# --- glide aims from the previous note, in octaves -----------------------

syn.all_notes_off()
syn.note_on_step(36)
ck(syn._glide.a == 0.0, "the first note ever has nothing to glide from")
syn.note_on_step(48, slide=True)
ck(
    abs(syn._glide.a - (-1.0)) < 1e-9,
    "gliding up an octave must start one octave BELOW the new note "
    "(bend units are octaves), got %r" % syn._glide.a,
)

# interrupting a glide must start the next one from where the pitch IS,
# not from the interrupted target: the same structural continuity as
# AHREnvelope.start_release()'s `env.a = env.value`
mid = syn._glide.value
syn.note_on_step(60, slide=True)
ck(
    abs(syn._glide.a - ((48 - 60) / 12.0 + mid)) < 1e-9,
    "an interrupted glide must carry its in-flight value into the next one",
)

# --- a slide TIES: it retunes the sounding voice, it does not re-press ----
# Neither step above called note_off(), so both took the tie path. A real
# 303 holds the gate across a slid step and the two become one note; only
# the pitch moves.

tie = make(filt_f=2000, envmod=0.6, slide_time=0.09)
tie.note_on_step(36)
first = tie.voices[36]
presses = len(tie.synthio.pressed)
tie.note_on_step(48, slide=True)
ck(
    48 in tie.voices and 36 not in tie.voices,
    "a tie must re-key the voice to the new note, got %r" % (list(tie.voices),),
)
ck(
    tie.voices[48] is first,
    "a tie must keep the SAME Note objects: pressing new ones is exactly "
    "the retrigger a tie exists to avoid",
)
ck(
    len(tie.synthio.pressed) == presses
    and all(n is o for n, o in zip(tie.synthio.pressed, first)),
    "the voice the synthesizer is sounding must be untouched: a release "
    "followed by a press of a new Note leaves the count the same but "
    "swaps the object, which is the retrigger being fixed here",
)
ck(
    abs(tie.voices[48][0].frequency - synthio.midi_to_hz(48)) < 1e-6,
    "the tied voice must be RETUNED to the new pitch, got %r"
    % tie.voices[48][0].frequency,
)
ck(
    48 in tie._fenvs and 36 not in tie._fenvs,
    "the filter envelope must be re-keyed too, or note_off() cannot "
    "release it and it leaks",
)
tie_env = tie._fenvs[48]
tie.note_on_step(55, slide=True)
ck(
    tie._fenvs[55] is tie_env,
    "the tie must leave the filter envelope RUNNING, not build a new one: "
    "the sweep carries on through a slid step",
)

# transpose has to reach the retune the same way it reaches _make_notes()
tr = make(filt_f=2000, transpose=-12)
tr.note_on_step(48)
tr.note_on_step(50, slide=True)
ck(
    abs(tr.voices[50][0].frequency - synthio.midi_to_hz(50 - 12)) < 1e-6,
    "a tied retune must apply transpose, got %r" % tr.voices[50][0].frequency,
)

# ...but only while the previous step is still sounding. A sequencer that
# releases first gets the old press-and-glide, which is what keeps the
# note_off() freeze below meaningful.
untied = make(filt_f=2000, slide_time=0.09)
untied.note_on_step(36)
untied.note_off(36)
untied.note_on_step(48, slide=True)
ck(
    48 in untied.voices and len(untied.voices) == 1,
    "a slide with nothing sounding must fall back to pressing the note",
)
ck(
    untied.voices[48] is not None and 48 in untied._fenvs,
    "...with its own fresh envelope, since there was none to carry on",
)

# --- the decay-only filter envelope --------------------------------------
# fenv_amount is NEGATIVE, so the ordinary rising AHR shape sweeps the
# cutoff DOWN from filt_f while the key is still held. This is the one
# gesture AHR is documented as unable to make in its positive direction.

syn = make(filt_f=4000, envmod=0.5, fenv_attack=0.2, fenv_curve=2)
ck(
    syn.fenv_amount == -2000.0,
    "envmod is a FRACTION of filt_f: 0.5 of 4000 must be -2000 Hz, got %r" % syn.fenv_amount,
)
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
ck(
    syn.voices[36][0].filter.frequency.value == syn.FILT_F_MIN,
    "envmod=1.0 drives the cutoff to zero; FILT_F_MIN must clamp it",
)

# envmod = 0 must cost nothing at all, and accent must still revive it
syn = make(filt_f=3000, envmod=0.0)
syn.note_on_step(36)
ck(36 not in syn._fenvs, "envmod=0 must build no per-voice envelope node")
syn.note_on_step(38, accent=True)
ck(
    38 in syn._fenvs,
    "an accented step raises the depth off zero, so the node must exist; "
    "the depth has to be written BEFORE the press or make() skips it",
)

# filt_type=None in mono: the voice gets no filter at all, and the cutoff
# property is the one place the two can disagree
nofilt = make(filt_type=None, envmod=0.75)
nofilt.note_on_step(36)
ck(nofilt.voices[36][0].filter is None, "filt_type=None must give the voice no filter")
ck(nofilt.filter is None, "...and nothing downstream can track a filter that does not exist")
nofilt.all_notes_off()

# --- accent must not contaminate the patch -------------------------------
# Every accent target is a shared block that Synth also reads back for
# save_patch(). Accent therefore writes SPARE inputs of those blocks.

# filt_q sits at Q_MAX so _q_norm() is exactly 1.0 and the resonance factor
# on the sweep depth drops out: the boost is then plain accent_cutoff*sweep,
# which is a number this can assert against.
syn = make(
    filt_f=2000,
    filt_q=BasslineSynth.Q_MAX,
    envmod=0.6,
    accent=0.5,
    accent_cutoff=4000.0,
    accent_q=0.6,
    amp_level=0.8,
)
patch = syn.patch

syn.note_on_step(36, accent=False)
plain = syn.voices[36][0]
ck(plain.filter.frequency.value == 2000.0, "an un-accented step sits at filt_f")
ck(plain.filter.Q.value == BasslineSynth.Q_MAX, "an un-accented step sits at filt_q")
ck(plain.envelope.attack_level == 0.8, "an un-accented step plays at amp_level")
ck(syn.decay == patch.fenv_attack, "an un-accented step falls in `decay` seconds")

syn.note_on_step(38, accent=True)
settled(syn)  # the accent arrives through a lag; see settled()
acc = syn.voices[38][0]
# snapshot as NUMBERS: mono shares one cutoff node and one Q block, so
# reading them again after a later step reads that later step's values
acc_hz = acc.filter.frequency.value
acc_q = acc.filter.Q.value
ck(
    abs(acc.filter.frequency.value - (2000.0 + 4000.0 * 0.5)) < 1e-6,
    "accent must ADD accent_cutoff * the sweep, and one accent from rest "
    "charges the sweep to exactly `accent`, got %r" % acc.filter.frequency.value,
)
ck(
    abs(acc.filter.Q.value - (BasslineSynth.Q_MAX + 0.6 * 0.5)) < 1e-9,
    "accent must add accent_q * the sweep to the resonance, got %r" % acc.filter.Q.value,
)
ck(acc.envelope.attack_level == 1.0, "accent must raise the level")
ck(
    acc.envelope is not plain.envelope,
    "the accented Envelope must be a separate cached object, not a rebuild",
)
ck(
    syn._fenv.attack == BasslineSynth.ACCENT_FALL,
    "an accented step's filter envelope must fall in the fixed ACCENT_FALL "
    "time, not the Decay knob's: that short fall is most of why an accent "
    "reads as pluckier rather than just louder, got %r" % syn._fenv.attack,
)
ck(
    syn.decay == patch.fenv_attack,
    "...while `decay` still reads back the KNOB, not the accented value: "
    "reading the block here is the silent-save trap, got %r" % syn.decay,
)

# --- the accent sweep is an accumulator, not a latch ----------------------
# The real accent circuit's capacitor does not discharge between steps, so
# a run of accents climbs and the steps after it fade back.

st = make(filt_f=2000, filt_q=BasslineSynth.Q_MAX, accent=0.5, accent_cutoff=4000.0)
peaks = []
for n in range(4):
    st.note_on_step(36 + n, accent=True)
    peaks.append(settled(st).voices[36 + n][0].filter.frequency.value)
    st.note_off(36 + n)
ck(
    all(b > a for a, b in zip(peaks, peaks[1:])),
    "four accented steps in a row must give four RISING cutoff peaks, got %r" % (peaks,),
)
ck(
    st._accent_sweep <= st.accent_sweep_max + 1e-9,
    "...saturating at accent_sweep_max rather than climbing forever, got %r"
    % st._accent_sweep,
)

after = []
for n in range(2):
    st.note_on_step(50 + n, accent=False)
    # an un-accented step does not retrigger the lag, so it stays out at
    # the end where the last accent left it: leftover charge still reaches
    # the filter, which is the decay half of the staircase
    after.append(st.voices[50 + n][0].filter.frequency.value)
    st.note_off(50 + n)
ck(
    peaks[-1] > after[0] > after[1] > 2000.0,
    "the steps after must DECAY back toward filt_f, not snap to it: the "
    "latch-and-drop this replaces did neither, got %r" % (after,),
)
ck(
    st.accent_sweep_decay == 0.55 and "accent_sweep_decay" in st._PARAMS,
    "the sweep's decay is an ordinary knob-able patch field",
)
ck(
    not hasattr(st.save_patch(), "accent_sweep"),
    "the sweep itself is PERFORMANCE state: saving it would make a patch "
    "load sound different depending on what was played before it",
)

# --- the accent LAG: resonance decides how fast the accent arrives -------
# Clockwise resonance routes the accent pulse through a lag circuit, and
# that upward ramp into the note is the acid "wow". It has to be a BLOCK in
# the graph, not a number, because a number cannot ramp.

lag = make(filt_f=2000, filt_q=BasslineSynth.Q_MAX, accent=0.8, accent_cutoff=4000.0)
ck(
    lag._filt_sum.c is lag._accent_lag,
    "the accent must reach the cutoff through the lag, in the spare third "
    "input of the sum Synth already built",
)
ck(
    lag._accent_lag not in lag.synthio.blocks,
    "the lag must NOT be rooted separately: it is reachable through "
    "_filt_base, which Synth already rooted, and a nested LFO ticks",
)
ck(
    lag._accent_lag.scale == lag._acc_hz * lag._accent_sweep,
    "the boost must ride the LFO's own scale, not a PRODUCT block: two "
    "extra Math nodes in the graph cost real render time for nothing",
)
lag.note_on_step(36, accent=True)
ck(
    lag._accent_lag.phase == 0.0,
    "an accented step must RESTART the lag, so the swell happens per note",
)
arriving = lag.voices[36][0].filter.frequency.value
arrived = settled(lag).voices[36][0].filter.frequency.value
ck(
    arrived > arriving,
    "the accent must RAMP in rather than jump: %r -> %r" % (arriving, arrived),
)
# resonance sets the ramp's length, and at the bottom there is no lag at all
fast = make(filt_f=2000, filt_q=BasslineSynth.Q_MIN, accent=0.8)
ck(
    fast._accent_lag.rate > lag._accent_lag.rate,
    "anti-clockwise resonance must make the accent a direct pulse (a much "
    "faster ramp), got %r vs %r" % (fast._accent_lag.rate, lag._accent_lag.rate),
)
# ...but a KNOB turn must not restart the swell under a sounding note
settled(lag)
lag.accent_cutoff = 5000.0
ck(
    lag._accent_lag.phase == 1.0,
    "a knob turn must not retrigger the lag: _refresh_accent() is on the "
    "knob path, _strike_accent() is the per-step one",
)

# ...and the knobs must still read back as the KNOBS
ck(syn.filt_f == 2000, "filt_f must read back clean during an accented note, got %r" % syn.filt_f)
ck(
    syn.filt_q == BasslineSynth.Q_MAX,
    "filt_q must read back clean during an accented note, got %r" % syn.filt_q,
)
ck(syn.envmod == 0.6, "envmod must read back clean during an accented note")

knob_fall = syn.decay
syn.save_patch()
ck(
    patch.filt_f == 2000 and patch.filt_q == BasslineSynth.Q_MAX,
    "save_patch() during an accented note must store the KNOB values, not the "
    "accented ones, got filt_f=%r filt_q=%r" % (patch.filt_f, patch.filt_q),
)
ck(
    patch.fenv_amount == -1200.0,
    "fenv_amount is derived from envmod, so it must be saved un-accented "
    "(-0.6*2000), got %r" % patch.fenv_amount,
)
ck(
    patch.fenv_attack == knob_fall,
    "fenv_attack must be saved un-accented too, or an accented note at save "
    "time pins the Decay knob at ACCENT_FALL forever, got %r" % patch.fenv_attack,
)
ck(patch.envmod == 0.6 and patch.accent == 0.5, "the 303 knobs must round-trip")

# an un-accented step must put every one of them back, though the cutoff
# and resonance decay toward the knob rather than snapping (see the sweep
# section above); only the per-step ones are instant.
syn.note_on_step(40, accent=False)
back = syn.voices[40][0]
ck(
    2000.0 < back.filter.frequency.value < acc_hz,
    "an un-accented step must DECAY the cutoff boost, not clear it, got %r"
    % back.filter.frequency.value,
)
ck(
    BasslineSynth.Q_MAX < back.filter.Q.value < acc_q,
    "...and likewise the resonance boost, got %r" % back.filter.Q.value,
)
ck(back.envelope.attack_level < 1.0, "an un-accented step must drop the level boost")
ck(
    syn._fenv.attack == knob_fall,
    "...and the fall time must go straight back to the knob: it is a "
    "per-step switch, not something the sweep carries",
)

# --- patch round-trip ----------------------------------------------------

syn = make(
    filt_f=1800,
    envmod=0.7,
    accent=0.3,
    slide_time=0.08,
    transpose=-12,
    amp_level=0.7,
    glide_time=0.05,
    wave="SQU",
)
p2 = Patch.from_json(syn.save_patch().to_json())
again = BasslineSynth(synthio.Synthesizer(), p2)
for name in (
    "filt_f",
    "envmod",
    "accent",
    "slide_time",
    "transpose",
    "amp_level",
    "glide_time",
    "wave",
    "fenv_amount",
):
    ck(
        getattr(again, name) == getattr(syn, name),
        "%s must survive a save/load round-trip: %r != %r"
        % (name, getattr(again, name), getattr(syn, name)),
    )

# a patch written before any of these fields existed must still load
legacy = BasslineSynth(synthio.Synthesizer(), Patch.from_json('{"name":"old","filt_f":900}'))
ck(
    legacy.envmod == 0.5 and legacy.accent == 0.5 and legacy.wave == "SAW",
    "an older patch must load on defaults rather than raising",
)
ck(legacy.glide_time == 0.0, "glide_time must default to no portamento")

# --- set_param covers the new knobs --------------------------------------

syn = make()
for name in (
    "glide_time",
    "envmod",
    "decay",
    "accent",
    "wave",
    "accent_cutoff",
    "accent_q",
    "slide_time",
    "transpose",
    "amp_level",
):
    ck(name in syn._PARAMS, "%s must be reachable via set_param()" % name)
syn.set_param("envmod", 0.9)
ck(syn.envmod == 0.9, "set_param must reach the property")
ck(
    "mono" not in syn._PARAMS,
    "mono is a plain attribute like push_env, NOT a patch field, listing it "
    "in _PARAMS without a matching _decompile() line is the silent-save trap",
)

# decay is the FILTER fall time only. Tying it to the amp decay as well
# (an earlier version did) makes envmod nearly inaudible: the note fades
# at the same rate the cutoff falls, so the sweep is masked by the
# amplitude and the pair just reads as a pluck.
syn.decay = 0.3
ck(syn.fenv_attack == 0.3, "decay must set the filter fall time")
ck(syn.decay == 0.3, "decay must read back what was written")
before = syn.amp_env[1]
syn.decay = 0.05
ck(
    syn.amp_env[1] == before,
    "decay must NOT touch the amp envelope: the amp has to be able to "
    "outlive the sweep, which is what makes the sweep audible",
)

# --- keyboard tracking on the ONE shared mono cutoff node ----------------
# BasslineSynth reuses a single cutoff node across notes, re-aiming its
# spare .b/.c inputs. That makes a STALE slot the real hazard: turning
# filt_track off must actually clear the offset, not leave the last note's
# tracking baked into the node every note after.
bt = BasslineSynth(
    synthio.Synthesizer(),
    Patch(filt_type="LPF", filt_f=1000, filt_q=1.0, fenv_amount=0, filt_vel=0, filt_track=1.0),
)
bt.note_on(72, velocity=80)  # below accent_velocity: accent writes
cut = bt._cutoff  # _filt_sum.c and would move the base
ck(
    abs(cut.value - 2000.0) < 0.01,
    "mono full tracking an octave up must double the cutoff, got %r" % cut.value,
)
bt.note_off(72)

bt.filt_track = 0.0  # knob to zero...
bt.note_on(72, velocity=80)  # ...then press the SAME note again
ck(
    abs(cut.value - 1000.0) < 0.01,
    "with filt_track 0 the shared node must be CLEARED to filt_f, not keep "
    "the previous note's tracking offset: want 1000, got %r" % cut.value,
)
bt.note_off(72)

# and it still reaches a sounding mono voice
bt.filt_track = 1.0
bt.note_on(72, velocity=80)
ck(abs(cut.value - 2000.0) < 0.01, "sanity before the live write")
bt.filt_track = 0.5
ck(
    abs(cut.value - 1500.0) < 0.01,
    "filt_track must move the sounding mono voice: want 1500, got %r" % cut.value,
)
bt.note_off(72)

# --- a glide must NOT drag the releasing previous note ------------------
# The stolen notes share the bend graph, and _aim_glide points it at the
# NEW note's starting pitch; offset by the interval. Without freezing,
# the still-audible old note is yanked that far too, in the WRONG
# direction: stepping up 43 -> 46 dropped the sounding 43 three semitones
# BELOW itself before climbing back (measured on rp2040 as 98.0 -> 81.7 Hz).
# With a slow attack on the new note that tail is the loudest thing there,
# so an upward step sounded like it went down.
gl = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0, glide_time=0.35))
gl.mono = True
gl.note_on(43)
old = list(gl.voices[43])
before = old[0].bend.value
gl.note_on(46)  # step UP a minor third
after = old[0].bend
ck(
    not hasattr(after, "value"),
    "a stolen note's bend must be FROZEN to a plain number, not left on the "
    "shared graph the glide is about to move",
)
ck(
    abs(after - before) < 1e-9,
    "the frozen tail must hold exactly where it was: %r -> %r" % (before, after),
)
ck(
    gl.voices[46][0].bend is gl._bend,
    "the NEW note must still ride the live shared bend and glide normally",
)
ck(gl._glide.a < 0, "...gliding UP into 46, i.e. starting flat")

# with no portamento nothing is frozen, the tail keeps vibrato and wheel
nog = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0, glide_time=0.0))
nog.mono = True
nog.note_on(43)
old2 = list(nog.voices[43])
nog.note_on(46)
ck(
    old2[0].bend is nog._bend,
    "glide_time 0 must leave the tail on the shared bend, there is no drag "
    "to prevent, and freezing would needlessly kill its vibrato",
)

# the per-note glide override counts as portamento too
ov = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0, glide_time=0.0))
ov.mono = True
ov.note_on(43)
old3 = list(ov.voices[43])
ov.note_on(46, glide=0.3)
ck(
    not hasattr(old3[0].bend, "value"),
    "note_on(glide=...) must freeze the tail even when glide_time is 0",
)

# --- mono is a PATCH field, and survives a round trip --------------------
# It used to be a live-only attribute, so a mono lead saved and reloaded
# came back polyphonic, with its glide_time intact but inert, since
# glide does nothing in poly. Half of a coupled pair was being stored.

lead = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0, glide_time=0.2))
lead.mono = True
saved = lead.save_patch()
ck(saved.mono is True, "save_patch() must record mono; got %r" % (saved.mono,))
back = SubtractiveSynth(synthio.Synthesizer(), Patch.from_dict(saved.to_dict()))
ck(back.mono is True, "a saved mono lead must reload mono; got %r" % (back.mono,))
back.note_on(48)
back.note_on(60)
ck(back._glide.a != 0, "reloaded mono lead must actually glide")

# explicitly poly round-trips as poly
poly = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0))
ck(poly.mono is False, "SubtractiveSynth defaults poly")
ck(poly.save_patch().mono is False, "an explicit False must be stored")

# --- the class default must win when the patch does not say -------------
# Patch.mono is None ("unspecified"). Resolving that to False rather than
# to the style's own default would load every pre-existing 303 patch as
# polyphonic and silently stop it being a 303.
ck(Patch().mono is None, "Patch.mono should default to None, not a bool")

bass = BasslineSynth(synthio.Synthesizer(), Patch(synth_type="bassline"))
ck(
    bass.mono is True,
    "a patch with no mono key must leave BasslineSynth monophonic; got %r" % (bass.mono,),
)

# ...but an explicit False in the patch still overrides the class
odd = BasslineSynth(synthio.Synthesizer(), Patch(synth_type="bassline", mono=False))
ck(odd.mono is False, "an explicit patch mono=False must override the style")

# and mono stays OUT of _PARAMS: structural, like the fx_*_on switches
ck(
    "mono" not in SubtractiveSynth._PARAMS,
    "mono must not be in _PARAMS, a CC should not flip mono/poly mid-phrase",
)

# --- a RELEASED tail must not be dragged by the next glide ---------------
# Measured on rp2040 before this was fixed: play 48, note_off it, glide to
# 36, and the still-ringing 48 was thrown up to midi 57.9, above both
# notes, before sliding back. note_on()'s steal-freeze cannot catch it,
# because note_off() has already popped it out of self.voices.
seq = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0, glide_time=0.3))
seq.mono = True
seq.note_on(48)
tail = list(seq.voices[48])[0]
seq.note_off(48)  # what a sequencer loop does first
ck(
    not hasattr(tail.bend, "value"),
    "note_off must freeze the bend of a note it releases, or a later glide "
    "drags the still-sounding tail",
)
frozen = tail.bend
seq.note_on(36)  # aims the shared bend at +1.0
ck(tail.bend == frozen, "a released tail's pitch must not move when the next note glides")
ck(seq._glide.a != 0, "...while the new note still glides normally")

# with no portamento there is nothing to drag, so keep the tail's vibrato
nofz = SubtractiveSynth(synthio.Synthesizer(), Patch(detune=1.0, glide_time=0.0))
nofz.mono = True
nofz.note_on(48)
t2 = list(nofz.voices[48])[0]
nofz.note_off(48)
ck(
    hasattr(t2.bend, "value"),
    "glide_time 0: leave the tail on the shared bend, freezing would only "
    "cost it vibrato for no benefit",
)

# --- BasslineSynth's own note_off() freeze, keyed on slide_time ----------
# It never sets self._glide_time (note_on_step() always passes an explicit
# per-note glide= override instead), so Synth.note_off()'s own guard is
# always false here; BasslineSynth needs its OWN freeze against slide_time.
bass_seq = BasslineSynth(synthio.Synthesizer(), Patch(synth_type="bassline", slide_time=0.3))
bass_seq.note_on_step(48)
bass_tail = list(bass_seq.voices[48])[0]
bass_seq.note_off(48)  # what a step sequencer does before the next note_on
ck(
    not hasattr(bass_tail.bend, "value"),
    "BasslineSynth.note_off() must freeze the bend of a note it releases, "
    "even though self._glide_time is never set",
)
bass_frozen = bass_tail.bend
bass_seq.note_on_step(36, slide=True)
ck(bass_tail.bend == bass_frozen, "a released BasslineSynth tail must not move when the next step slides")
ck(bass_seq._glide.a != 0, "...while the new note still glides normally")

if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_mono: all checks passed")
