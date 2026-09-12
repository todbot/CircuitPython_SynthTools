# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthtools_bassline_filter_demo.py -- acid bassline: filter cutoff,
# envelope depth, decay time, and the oscillator waveform switch.
#
# Plays one 16-step pattern over and over, changing a single knob every few
# bars and printing what it changed, so you can hear each one on its own.
# One of three focused demos split out of a single, too-broad one; see
# synthtools_bassline_accent_demo.py (slide/accent) and
# synthtools_bassline_fx_demo.py (distortion/echo) for the rest. Runs the
# voice through BasslineSynth's owned extra filter stage (24 dB/octave, see
# fx_filter_stages below) so the squelch this demo is about is at its
# sharpest; that stage is set once and not itself swept.
#
# BasslineSynth is monophonic and takes the TB-303's two per-step flags
# (slide, accent); this demo's PATTERN uses them for an authentic feel but
# doesn't sweep either knob -- see synthtools_bassline_accent_demo.py for
# that.

import time

from synth_setup import knobA, mixer
from synth_setup import synth as engine

from synthtools import BasslineSynth, Patch

# --- the patch ----------------------------------------------------------
# The classic squelch is a big downward sweep from a bright starting point.
# envmod is a FRACTION of filt_f, not a number of Hz, so the sweep tracks
# the cutoff knob: 0.75 of 1200 Hz means the filter falls to 300 Hz, two
# octaves. Judge envmod in OCTAVES at the cutoff it will actually sit at,
# never in Hz: 0.2 of 1200 is only a third of an octave and you will not
# hear it.
patch = Patch(
    name="acid",
    synth_type="bassline",
    wave="SAW",  # "SQU" is the 303's other switch position
    filt_type="LPF",
    filt_f=1200,  # the PEAK the sweep starts from
    filt_q=1.8,  # squelch lives here; push it up toward 3-4
    envmod=0.75,
    # THE TWO NUMBERS THAT DECIDE WHETHER YOU HEAR envmod AT ALL.
    #
    # fenv_attack is the filter FALL time, and it must be shorter than the
    # gate (GATE * the current step's duration, and knobA sweeps that live --
    # see BPM_MIN/BPM_MAX below) or the sweep is cut off partway: at 0.28s it
    # only got 23% of the way down at this file's original fixed tempo, so
    # envmod=0.75 moved 0.74 octaves instead of 2.0, and envmod=0.2 moved
    # 0.16; i.e. nothing. At 0.09s the sweep completes inside the note across
    # nearly all of knobA's range; see the GATE comment for where it doesn't.
    #
    # The amp decay must be LONGER than that, so the note is still loud
    # while the cutoff falls. Equal times sound like one gesture (a
    # pluck), because loudness and brightness drop together and mask each
    # other. Sustain 0 means every step plucks; there is no held part.
    amp_env=[0.001, 0.25, 0.0, 0.02],
    fenv_attack=0.09,  # the FALL time (the sweep runs downward)
    fenv_release=0.05,
    # 3 gives the fast drop and long tail that reads as "analog". At 1 the
    # sweep is a straight line and sounds noticeably more synthetic.
    fenv_curve=2,
    # what an accented step gets, on top of the above -- see
    # synthtools_bassline_accent_demo.py; not swept here.
    accent=0.6,
    accent_cutoff=4000,
    accent_q=0.8,
    amp_level=0.75,
    slide_time=0.09,
    transpose=0,
    # A synthio.Note holds ONE Biquad, so the voice alone is 12 dB/octave;
    # one extra stage makes 24, where the squelch this demo is about really
    # lives. The stage tracks synth.filter's cutoff AND resonance on its
    # own, so it follows every filt_f/filt_q/envmod change below with
    # nothing to keep in sync by hand: see fx_filter_stages in
    # bassline_synth.py. (Distortion and echo are their own demo: see
    # synthtools_bassline_fx_demo.py.)
    fx_filter_stages=1,
)

synth = BasslineSynth(engine, patch)

try:
    mixer.voice[0].play(synth.output)  # replaces synth_setup's direct hookup
    print("filter: 24 dB/octave (1 extra stage)")
except ImportError as e:
    print("%s -- falling back to the bare voice filter (12 dB/oct)" % e)
    mixer.voice[0].play(synth.synthio)

# --- the pattern --------------------------------------------------------
# (midi_note, slide, accent), or None for a rest.
PATTERN = (
    (36, False, True),
    (36, False, False),
    (48, True, False),
    (36, False, False),
    (39, False, True),
    None,
    (36, False, False),
    (43, True, False),
    (36, False, True),
    (36, False, False),
    (29, True, False),  # the other slides go up; this one goes down
    (36, False, False),  # back to the root, not a big jump: lets the down-slide land
    (39, False, True),
    (36, False, False),
    None,
    (34, False, False),
)

# knobA sweeps bpm continuously across this range; see bpm_to_step() below.
BPM_MIN, BPM_MAX = 80, 160
# Long gate on purpose: the filter sweep only happens while the note is
# held, so a short gate truncates it. GATE*held must stay >= fenv_attack
# (0.09s), which holds up to 150 bpm (held 90ms, exactly fenv_attack) but
# not past it: at BPM_MAX=160, held is only 84ms, so the sweep gets ~93% of
# the way down at the fastest knob setting -- mild, not the ~23% seen
# elsewhere in this file with a badly mismatched fenv_attack, but real.
GATE = 0.9  # fraction of a step a note is held for


def bpm_to_step(bpm):
    return 60.0 / bpm / 4  # sixteenth notes


# Each entry is (label, function), applied for BARS_PER_CHANGE bars each.
BARS_PER_CHANGE = 2
CHANGES = (
    ("filt_f 1200, the resting cutoff", lambda: setattr(synth, "filt_f", 1200)),
    ("filt_f 500, darker, and the sweep shrinks with it", lambda: setattr(synth, "filt_f", 500)),
    ("filt_f 3500, brighter, and the sweep grows", lambda: setattr(synth, "filt_f", 3500)),
    ("filt_f 1200 again", lambda: setattr(synth, "filt_f", 1200)),
    ("envmod 0.2, barely any sweep", lambda: setattr(synth, "envmod", 0.2)),
    ("envmod 1.0, sweeps all the way shut", lambda: setattr(synth, "envmod", 1.0)),
    ("envmod 0.75", lambda: setattr(synth, "envmod", 0.75)),
    ("filt_q 3.6, squelch", lambda: setattr(synth, "filt_q", 3.6)),
    # 0.03 collapses inside ONE 11.6ms render block at this rig's 22050 Hz
    # (256-sample blocks), once fenv_curve=3's front-loaded shape is
    # accounted for: 1-(1-t)^3 is already 77% done after the first block,
    # 99% after the second. There is no "before" to contrast against --
    # the note's own amp attack (0.001s) is faster still -- so it just
    # sounds like the note starts already dark, not a click. 0.05 spreads
    # the same sweep across ~4 blocks (55/85/97/100%) and actually reads
    # as fast movement: see CLAUDE.md's "budget >=0.05s" filter-envelope
    # finding, which this value was violating.
    (
        "decay 0.05, a quick snap near the floor for a perceptible sweep",
        lambda: setattr(synth, "decay", 0.05),
    ),
    (
        "decay 0.50, longer than the gate, so it never finishes",
        lambda: setattr(synth, "decay", 0.50),
    ),
    ("decay 0.09", lambda: setattr(synth, "decay", 0.09)),
    ('wave "SQU", the other 303 switch position', lambda: setattr(synth, "wave", "SQU")),
    ('wave "SAW"', lambda: setattr(synth, "wave", "SAW")),
)

print("bassline filter demo: %d steps, knobA sweeps %d-%d bpm" % (len(PATTERN), BPM_MIN, BPM_MAX))

bar = 0
while True:
    for i, step in enumerate(PATTERN):
        # Named note_step, NOT step: the for-loop above already owns that
        # name for the current PATTERN entry, and shadowing it here once
        # cost a `TypeError: unsupported types for __mul__: 'tuple',
        # 'float'` two lines down, from `step * GATE` silently multiplying
        # the pattern tuple instead of a duration.
        bpm = BPM_MIN + (knobA.value / 65535) * (BPM_MAX - BPM_MIN)
        note_step = bpm_to_step(bpm)

        if i == 0:
            if bar % BARS_PER_CHANGE == 0:
                label, apply = CHANGES[(bar // BARS_PER_CHANGE) % len(CHANGES)]
                print("bpm:%d %s" % (bpm, label))
                apply()
            bar += 1

        if step is None:  # a rest
            time.sleep(note_step)
            continue

        note, slide, accent = step
        synth.note_on_step(note, slide=slide, accent=accent)
        time.sleep(note_step * GATE)
        synth.note_off(note)
        time.sleep(note_step * (1.0 - GATE))
