# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthtools_bassline_fx_demo.py -- acid bassline: BasslineSynth's owned
# effects chain (extra filter stage, distortion, echo).
#
# Plays one 16-step pattern over and over, changing a single knob every few
# bars and printing what it changed, so you can hear each one on its own.
# One of three focused demos split out of a single, too-broad one; see
# synthtools_bassline_filter_demo.py (filter/envmod/decay) and
# synthtools_bassline_accent_demo.py (slide/accent) for the rest, including
# why the patch fields below are set the way they are.
#
# BasslineSynth also owns a specialized effects chain (filter -> distortion
# -> echo): an extra resonant filter stage, LOFI-mode distortion, and a
# tempo-related echo. The three fx_*_on/fx_filter_stages switches are
# STRUCTURAL and set once below; only the LIVE knobs (fx_drive, fx_drive_mix,
# fx_delay_ms, fx_delay_mix, fx_delay_decay) move during the demo.

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
    accent=0.6,
    accent_cutoff=4000,
    accent_q=0.8,
    amp_level=0.75,
    slide_time=0.09,
    transpose=0,
    # --- BasslineSynth's own effects chain, if this build has
    # audiofilters. A synthio.Note holds ONE Biquad, so the voice alone
    # is 12 dB/octave; one extra stage makes 24, where the squelch really
    # lives. The stage tracks synth.filter's cutoff AND resonance on its
    # own, so it follows the sweep and the accent with nothing to keep in
    # sync by hand: see fx_filter_stages in bassline_synth.py.
    fx_filter_stages=1,
    # Distortion and echo, same chain, needing audiodelays too. Both exist
    # from the start but sit at mix 0 -- silent, same as not being there --
    # until the CHANGES rotation below brings each in on its own.
    fx_distortion_on=True,
    fx_drive=0.35,  # set_drive() maps 0..1; LOFI mode's own "drive" doesn't
    fx_drive_mix=0.0,
    fx_echo_on=True,
    fx_delay_ms=273,  # an 8th note at 110 bpm: 60000/110/4*2, on the step grid
    fx_delay_mix=0.0,
    fx_delay_decay=0.35,  # feedback: how many repeats you hear
)

# audiodelays.Echo allocates its whole delay line up front, sized by
# max_delay_ms (not fx_delay_ms), and needs it as an int: FX_MAX_DELAY_MS's
# class default is 1000, which is 44100 bytes at this rig's 22050 Hz mono
# and MemoryError'd here with ~112 KB free (other things -- the synth
# graph, the extra filter stage, the distortion buffer -- are already
# holding some of that). This demo never asks for more than 350 ms, so
# cap the buffer there with room to spare, the same
# set-on-the-subclass-before-constructing pattern as SubtractiveSynth's
# FILT_F_MAX.
BasslineSynth.FX_MAX_DELAY_MS = 500

synth = BasslineSynth(engine, patch)

try:
    mixer.voice[0].play(synth.output)  # replaces synth_setup's direct hookup
    print("fx chain: +1 filter stage (24 dB/oct), distortion, echo")
except (ImportError, MemoryError) as e:
    # _build_fx() is atomic: missing EITHER audiofilters or audiodelays, or
    # failing to allocate the echo buffer, drops the whole chain, not just
    # the piece that needed it.
    print("%s -- falling back to the bare voice filter" % e)
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

BPM = 110
STEP = 60.0 / BPM / 4  # sixteenth notes
GATE = 0.9  # fraction of a step a note is held for

# Each entry is (label, function), applied for BARS_PER_CHANGE bars each.
BARS_PER_CHANGE = 2
CHANGES = (
    # --- distortion: fx_drive_mix is the switch, fx_drive is the amount ---
    ("fx_drive_mix 0.0, distortion built but silent", lambda: setattr(synth, "fx_drive_mix", 0.0)),
    ("fx_drive_mix 0.6, LOFI grit mixed in", lambda: setattr(synth, "fx_drive_mix", 0.6)),
    ("fx_drive 0.8, same mix, more grit", lambda: setattr(synth, "fx_drive", 0.8)),
    ("fx_drive_mix 0.0, distortion off again", lambda: setattr(synth, "fx_drive_mix", 0.0)),
    # --- echo: fx_delay_mix is the switch, ms/decay shape the repeats -----
    (
        "fx_delay_mix 0.35, echo in, synced to an 8th note",
        lambda: setattr(synth, "fx_delay_mix", 0.35),
    ),
    ("fx_delay_decay 0.6, repeats trail longer", lambda: setattr(synth, "fx_delay_decay", 0.6)),
    (
        "fx_delay_ms 350, off the grid, echoes drift against the pattern",
        lambda: setattr(synth, "fx_delay_ms", 350),
    ),
    (
        "fx_delay_ms 273, back on the 8th-note grid",
        lambda: setattr(synth, "fx_delay_ms", 273),
    ),
    ("fx_delay_decay 0.35", lambda: setattr(synth, "fx_delay_decay", 0.35)),
    ("fx_delay_mix 0.0, echo off", lambda: setattr(synth, "fx_delay_mix", 0.0)),
)

print("bassline fx demo: %d steps at %d bpm" % (len(PATTERN), BPM))

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
