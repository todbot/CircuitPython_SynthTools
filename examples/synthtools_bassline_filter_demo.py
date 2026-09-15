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
# BARE voice, 12 dB/octave: the owned extra filter stage would sharpen the
# squelch, but an audiofilters.Filter costs enough rp2040 CPU to swing the
# step timing by +/-11ms, and a demo about envelope shape needs a steady
# grid more than it needs a steeper slope. See the patch below.
#
# BasslineSynth is monophonic and takes the TB-303's two per-step flags
# (slide, accent); this demo's PATTERN uses them for an authentic feel but
# doesn't sweep either knob -- see synthtools_bassline_accent_demo.py for
# that.

import microcontroller

# 200 MHz, up from the 125 MHz boot default. The main loop shares the CPU
# with the audio renderer, so the headroom shows up as steadier step
# timing, not just as spare cycles. Set BEFORE synth_setup is imported:
# rp2040's I2S clock is derived from sys_clk, so changing it afterwards
# would move the sample rate out from under the audio that is already
# running. Same placement as synthtools_wavetable_chords.py.
microcontroller.cpu.frequency = 200_000_000

import time

from synth_setup import mixer
from synth_setup import synth as engine

from synthtools import BasslineSynth, Patch

try:
    from supervisor import ticks_ms
except ImportError:  # desktop CPython, for a syntax check

    def ticks_ms():
        """stand-in for supervisor.ticks_ms"""
        return time.monotonic_ns() // 1_000_000


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
    # filt_q up at 4.0: on this engine resonance also drives how DEEP an
    # accent sweeps and how fast it arrives, and at 1.8 the lag is ~9ms
    # and inaudible. accent_cutoff is scaled to match: the accent boost is
    # multiplied by (0.35 + 0.65*resonance), so 5268 at this filt_q lands
    # the same Hz that a flat 4000 used to.
    filt_q=4.0,  # squelch lives here
    envmod=0.75,
    # THE TWO NUMBERS THAT DECIDE WHETHER YOU HEAR envmod AT ALL.
    #
    # fenv_attack is the filter FALL time, and it must be shorter than the
    # gate (GATE * the step, 123ms here) or the sweep is cut off partway: at
    # 0.28s it only got 23% of the way down, so envmod=0.75 moved 0.74
    # octaves instead of 2.0, and envmod=0.2 moved 0.16; i.e. nothing. At
    # 0.09s the sweep completes comfortably inside the note.
    #
    # The amp decay must be LONGER than that, so the note is still loud
    # while the cutoff falls. Equal times sound like one gesture (a
    # pluck), because loudness and brightness drop together and mask each
    # other. Longer than a whole step, in fact: the stock 303's VCA decay
    # is fixed near 3.5s whatever the Decay knob says, which keeps the
    # level flat for the length of the gate and keeps a TIED note audible
    # through its second step.
    amp_env=[0.003, 3.5, 0.0, 0.05],
    fenv_attack=0.09,  # the FALL time (the sweep runs downward)
    fenv_release=0.05,
    # 3 gives the fast drop and long tail that reads as "analog". At 1 the
    # sweep is a straight line and sounds noticeably more synthetic.
    fenv_curve=2,
    # what an accented step gets, on top of the above -- see
    # synthtools_bassline_accent_demo.py; not swept here.
    accent=0.6,
    accent_cutoff=5268,
    accent_q=0.8,
    amp_level=0.75,
    slide_time=0.09,
    transpose=0,
    # NO fx chain here, and that is a timing decision, not a taste one.
    # An audiofilters.Filter costs enough rp2040 CPU to displace the main
    # loop: measured on this rig at 130bpm, steps land within 5ms of the
    # grid playing synth.synthio, and swing +/-11ms the moment a Filter is
    # in the chain (a bigger fx buffer makes it worse, not better). This
    # demo is about the VOICE's own filter, so it takes the steady timing
    # and leaves the extra stages and the post-filter high-pass to
    # synthtools_bassline_fx_demo.py.
    fx_hpf_f=0,
    fx_filter_stages=0,
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
    (36, True, False),
    (43, False, False),
    (36, False, False),
    (36, False, True),
    (41, True, True),
    (36, False, False),
    (48, False, True),
    (36, True, False),
    (34, False, False),
    (36, False, False),
    (43, False, True),
)

BPM = 110
STEP_MS = int(60_000 / BPM / 4)  # sixteenth notes, in ms
# Long gate on purpose: the filter sweep only happens while the note is
# held, so a short gate truncates it. GATE*held must stay >= fenv_attack
# (0.09s): here held is 123ms, comfortably clear. A knobA bpm sweep used to
# live here, but a tempo that moves while you are trying to judge envelope
# shape is one variable too many, and above ~150bpm the gate stops clearing
# fenv_attack anyway.
GATE = 0.9  # fraction of a step a note is held for


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
    # down from the patch's 4.0, not up: it also thins the accent, since
    # resonance drives the accent sweep's depth on this engine
    ("filt_q 1.8, less squelch and a milder accent", lambda: setattr(synth, "filt_q", 1.8)),
    ("filt_q 4.0", lambda: setattr(synth, "filt_q", 4.0)),
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

print("bassline filter demo: %d steps at %d bpm" % (len(PATTERN), BPM))

# The loop schedules off monotonic_ns and ACCUMULATES the step interval
# rather than sleeping for it. Sleeping drifts: the note_on/note_off work
# (~5.7ms on an rp2040) lands on top of every sleep, so a 113ms step ran at
# 119ms, about 5% slow, and nothing ever caught it back up. Accumulating
# step_at absorbs the work instead. The 1ms sleep keeps the poll from
# spinning flat out and competing with the audio render.
#
# It also has to be one flat loop rather than a for-loop over PATTERN: a
# step that TIES into the next one holds its gate open past its own step,
# so the note-off has to be scheduled independently of where the sequence
# has got to.

# Timing follows the house sequencer idiom (trig_sequencer.py): poll as
# fast as possible on ticks_ms, accumulate the step interval so the work
# in a step is absorbed rather than added to it, and RESYNC if a stall put
# us a whole step behind instead of burst-firing to catch up.
#
# ticks_ms, not time.monotonic_ns: past boot monotonic_ns exceeds 2**30, so
# every call allocates a bigint -- measured 21us and ~0.5 bytes a call
# against 13us and none, which at poll rates is real GC churn, and a GC
# pause lands as a late step.
#
# It also has to be one flat loop rather than a for-loop over PATTERN: a
# step that TIES into the next one holds its gate open past its own step,
# so the note-off has to be scheduled independently of where the sequence
# has got to.

bar = 0
i = 0
sounding = None
gate_off_at = None
next_step = ticks_ms()

while True:
    now = ticks_ms()

    if gate_off_at is not None and now - gate_off_at >= 0:
        synth.note_off(sounding)
        sounding = gate_off_at = None

    if now - next_step >= 0:
        step_millis = STEP_MS
        if i == 0:
            if bar % BARS_PER_CHANGE == 0:
                label, apply = CHANGES[(bar // BARS_PER_CHANGE) % len(CHANGES)]
                print("  %s" % label)
                apply()
            bar += 1

        step = PATTERN[i]
        if step is not None:
            note, slide, accent = step
            synth.note_on_step(note, slide=slide, accent=accent)
            sounding = note
            # A slid step TIES to the one before it, and can only do that
            # while that one is still sounding. So hold the gate open across
            # the whole step whenever the NEXT one slides; releasing would
            # leave the tie with nothing to tie to and it would retrigger.
            nxt = PATTERN[(i + 1) % len(PATTERN)]
            hold = nxt is not None and nxt[1]
            gate_off_at = None if hold else now + int(step_millis * GATE)

        i = (i + 1) % len(PATTERN)
        next_step += step_millis
        if next_step < now:  # a stall put us a whole step behind: resync
            next_step = now + step_millis
