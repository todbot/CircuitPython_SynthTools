# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthtools_bassline_accent_demo.py -- acid bassline: the two per-step
# 303 flags, accent and slide.
#
# Plays one 16-step pattern over and over, changing a single knob every few
# bars and printing what it changed, so you can hear each one on its own.
# One of three focused demos split out of a single, too-broad one; see
# synthtools_bassline_filter_demo.py (filter/envmod/decay) and
# synthtools_bassline_fx_demo.py (distortion/echo) for the rest, including
# why the patch fields below are set the way they are.
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

# --- the patch: same acid preset as synthtools_bassline_filter_demo.py --
patch = Patch(
    name="acid",
    synth_type="bassline",
    wave="SAW",
    filt_type="LPF",
    filt_f=1200,
    filt_q=1.8,
    envmod=0.75,
    amp_env=[0.001, 0.25, 0.0, 0.02],
    fenv_attack=0.09,
    fenv_release=0.05,
    fenv_curve=3,
    # what an accented step gets, on top of the resting patch above
    accent=0.6,
    accent_cutoff=4000,  # Hz added at full accent
    accent_q=0.8,  # resonance added at full accent
    amp_level=0.75,  # un-accented level, so accents have room to be louder
    slide_time=0.09,
    transpose=0,
)

synth = BasslineSynth(engine, patch)
mixer.voice[0].play(synth.synthio)  # replaces synth_setup's direct hookup

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

BPM = 110
STEP = 60.0 / BPM / 4  # sixteenth notes
GATE = 0.9  # fraction of a step a note is held for

# note_on() re-aims the shared glide node on EVERY note-on, slide or not
# (a non-slide step passes glide=0.0, which snaps in ~1ms), so slide_time
# can never exceed roughly one STEP (~136ms here) and be heard in full: the
# next note-on always cuts it off first. The "lazy slide" CHANGES entry
# below needs actual room, so it widens step_scale for its own window
# instead of raising slide_time past that ceiling. A mutable single-element
# list so the CHANGES closures can rebind it; the main loop reads it fresh
# every step.
step_scale = [1.0]


def _lazy_slide_on():
    synth.slide_time = 0.3
    step_scale[0] = 3.0  # ~409ms/step: room for a slide_time of 0.3 to finish


def _lazy_slide_off():
    synth.slide_time = 0.09
    step_scale[0] = 1.0


# Each entry is (label, function), applied for BARS_PER_CHANGE bars each.
BARS_PER_CHANGE = 2
CHANGES = (
    ("accent 0.0, accented steps stop standing out", lambda: setattr(synth, "accent", 0.0)),
    ("accent 1.0, and now they really do", lambda: setattr(synth, "accent", 1.0)),
    ("accent 0.6", lambda: setattr(synth, "accent", 0.6)),
    (
        "slide_time 0.005, slides become almost instant",
        lambda: setattr(synth, "slide_time", 0.005),
    ),
    (
        "slide_time 0.3, step time x3: room for a real lazy slide",
        _lazy_slide_on,
    ),
    ("slide_time 0.09, step time normal again", _lazy_slide_off),
)

print("bassline accent/slide demo: %d steps at %d bpm" % (len(PATTERN), BPM))

bar = 0
while True:
    for i, step in enumerate(PATTERN):
        if i == 0:
            if bar % BARS_PER_CHANGE == 0:
                label, apply = CHANGES[(bar // BARS_PER_CHANGE) % len(CHANGES)]
                print("  %s" % label)
                apply()
            bar += 1

        cur_step = STEP * step_scale[0]
        if step is None:  # a rest
            time.sleep(cur_step)
            continue

        note, slide, accent = step
        synth.note_on_step(note, slide=slide, accent=accent)
        time.sleep(cur_step * GATE)
        synth.note_off(note)
        time.sleep(cur_step * (1.0 - GATE))
