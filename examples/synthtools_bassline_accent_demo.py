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
# A slide TIES the two steps into one held note, as the original does: the
# pitch glides and the envelopes keep running. That needs the gate held, so
# the loop below skips its note_off() whenever the NEXT step slides. Being
# monophonic, the synth steals its own sounding voice otherwise, so the loop
# still never has to track what is playing.

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


# --- the patch: same acid preset as synthtools_bassline_filter_demo.py --
patch = Patch(
    name="acid",
    synth_type="bassline",
    wave="SAW",
    filt_type="LPF",
    filt_f=1200,
    # filt_q up at 4.0: on this engine resonance also drives how DEEP an
    # accent sweeps and how fast it arrives, and at 1.8 the lag is ~9ms
    # and inaudible. accent_cutoff is scaled to match: the accent boost is
    # multiplied by (0.35 + 0.65*resonance), so 5268 at this filt_q lands
    # the same Hz that a flat 4000 used to.
    filt_q=4.0,
    envmod=0.75,
    # Decay far longer than a step, so the level is essentially flat for as
    # long as the gate is open. That is the stock 303 (its VCA envelope
    # decay is fixed near 3.5s, untouched by the Decay knob) and it is what
    # keeps a TIED note audible through its second step; at 0.25s a slide
    # landed on a note that had already faded out.
    amp_env=[0.003, 3.5, 0.0, 0.05],
    fenv_attack=0.09,
    fenv_release=0.05,
    fenv_curve=3,
    # what an accented step gets, on top of the resting patch above
    accent=0.6,
    accent_cutoff=5268,  # Hz added at full accent
    accent_q=0.8,  # resonance added at full accent
    amp_level=0.75,  # un-accented level, so accents have room to be louder
    slide_time=0.09,
    transpose=0,
)

synth = BasslineSynth(engine, patch)
# synthio directly, no fx chain: this demo is about the two per-step
# flags. The other two set fx_hpf_f and play synth.output instead.
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
# GATE also has to leave the filter sweep room: the envelope only runs
# while the note is held, so GATE*step must stay LONGER than `decay` or the
# sweep is cut off partway and envmod does less than its number suggests.
GATE = 0.9  # fraction of a step a note is held for

# note_on() re-aims the shared glide node on EVERY note-on, slide or not
# (a non-slide step passes glide=0.0, which snaps in ~1ms), so slide_time
# can never exceed roughly one step (~136ms here) and be heard in full: the
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
        step_millis = int(STEP_MS * step_scale[0])
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
