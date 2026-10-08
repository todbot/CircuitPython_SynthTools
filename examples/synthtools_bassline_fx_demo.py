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
    # decay far longer than a step, as the stock 303's fixed ~3.5s VCA
    # decay is: the level stays flat for the gate, so a TIED note is still
    # audible on its second step. See synthtools_bassline_accent_demo.py.
    amp_env=[0.003, 3.5, 0.0, 0.05],
    fenv_attack=0.09,
    fenv_release=0.05,
    fenv_curve=3,
    accent=0.6,
    accent_cutoff=5268,
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
    # The 303's thin bass is its small coupling capacitors between filter
    # and VCA, not its filter. Without this the voice sounds "too big" and
    # never quite reads as a 303; 0 or lower is the Devil Fish "fat" mod.
    fx_hpf_f=80,
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
