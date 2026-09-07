# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthtools_bassline_demo.py -- acid bassline with synthtools BasslineSynth
#
# Plays one 16-step pattern over and over, changing a single knob every few
# bars and printing what it changed, so you can hear each one on its own.
#
# BasslineSynth is monophonic and takes the TB-303's two per-step flags:
#
#   slide   glide the pitch into this step from the one before
#   accent  a louder, brighter, more resonant step
#
# Note a slide glides but still retriggers the envelopes; a real 303 ties
# the two steps into one held note. Being monophonic, the synth steals its
# own sounding voice, so the loop below never has to track what is playing.

import time

from synth_setup import mixer
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
    # gate (here 0.9 * a 115ms step = 104ms) or the sweep is cut off
    # partway: at 0.28s it only got 23% of the way down, so envmod=0.75
    # moved 0.74 octaves instead of 2.0, and envmod=0.2 moved 0.16; i.e.
    # nothing. At 0.09s the sweep completes inside the note.
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
    fenv_curve=3,
    # what an accented step gets, on top of the above
    accent=0.6,
    accent_cutoff=4000,  # Hz added at full accent
    accent_q=0.8,  # resonance added at full accent
    amp_level=0.75,  # un-accented level, so accents have room to be louder
    slide_time=0.09,
    transpose=0,
    # --- BasslineSynth's own effects chain, if this build has
    # audiofilters. A synthio.Note holds ONE Biquad, so the voice alone
    # is 12 dB/octave; one extra stage makes 24, where the squelch really
    # lives. The stage tracks synth.filter's cutoff AND resonance on its
    # own, so it follows the sweep and the accent with nothing to keep in
    # sync by hand: see fx_filter_stages in bassline_synth.py.
    fx_filter_stages=1,
)

synth = BasslineSynth(engine, patch)

try:
    mixer.voice[0].play(synth.output)  # replaces synth_setup's direct hookup
    print("filter: 24 dB/octave (1 extra stage)")
except ImportError:
    print("no audiofilters in this build; 12 dB/octave, voice filter only")
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
    (51, True, False),
    (48, False, False),
    (39, False, True),
    (36, False, False),
    None,
    (34, False, False),
)

BPM = 130
STEP = 60.0 / BPM / 4  # sixteenth notes
# Long gate on purpose: the filter sweep only happens while the note is
# held, so a short gate truncates it. 0.9 leaves the sweep (0.09s) room to
# finish inside the note (0.104s).
GATE = 0.9  # fraction of a step a note is held for

# Each entry is (label, function), applied for BARS_PER_CHANGE bars each.
BARS_PER_CHANGE = 2
CHANGES = (
    ("filt_f 1200, the resting cutoff", lambda: setattr(synth, "filt_f", 1200)),
    ("filt_f 500, darker, and the sweep shrinks with it", lambda: setattr(synth, "filt_f", 500)),
    ("filt_f 2500, brighter, and the sweep grows", lambda: setattr(synth, "filt_f", 2500)),
    ("filt_f 1200 again", lambda: setattr(synth, "filt_f", 1200)),
    ("envmod 0.2, barely any sweep", lambda: setattr(synth, "envmod", 0.2)),
    ("envmod 1.0, sweeps all the way shut", lambda: setattr(synth, "envmod", 1.0)),
    ("envmod 0.75", lambda: setattr(synth, "envmod", 0.75)),
    ("filt_q 3.6, squelch", lambda: setattr(synth, "filt_q", 3.6)),
    ("decay 0.03, sweep snaps shut, almost a click", lambda: setattr(synth, "decay", 0.03)),
    (
        "decay 0.30, longer than the gate, so it never finishes",
        lambda: setattr(synth, "decay", 0.30),
    ),
    ("decay 0.09", lambda: setattr(synth, "decay", 0.09)),
    ("accent 0.0, accented steps stop standing out", lambda: setattr(synth, "accent", 0.0)),
    ("accent 1.0, and now they really do", lambda: setattr(synth, "accent", 1.0)),
    ("accent 0.6", lambda: setattr(synth, "accent", 0.6)),
    (
        "slide_time 0.005, slides become almost instant",
        lambda: setattr(synth, "slide_time", 0.005),
    ),
    ("slide_time 0.2, long, lazy slides", lambda: setattr(synth, "slide_time", 0.2)),
    ("slide_time 0.09", lambda: setattr(synth, "slide_time", 0.09)),
    ('wave "SQU", the other 303 switch position', lambda: setattr(synth, "wave", "SQU")),
    ('wave "SAW"', lambda: setattr(synth, "wave", "SAW")),
)

print("bassline demo: %d steps at %d bpm" % (len(PATTERN), BPM))

bar = 0
while True:
    for i, step in enumerate(PATTERN):
        if i == 0:
            if bar % BARS_PER_CHANGE == 0:
                label, apply = CHANGES[(bar // BARS_PER_CHANGE) % len(CHANGES)]
                print("  %s" % label)
                apply()
            bar += 1

        if step is None:  # a rest
            time.sleep(STEP)
            continue

        note, slide, accent = step
        synth.note_on_step(note, slide=slide, accent=accent)
        time.sleep(STEP * GATE)
        synth.note_off(note)
        time.sleep(STEP * (1.0 - GATE))
