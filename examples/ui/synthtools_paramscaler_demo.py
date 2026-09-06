# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthtools_paramscaler_demo.py -- two knobs editing four parameters,
# with ParamScaler doing the takeover.
#
# Copy flat onto CIRCUITPY beside synth_setup.py and the synthtools/
# package, then either rename it code.py or, from the REPL:
#
#     import synthtools_paramscaler_demo
#
# --- what this is for -------------------------------------------------
#
# Two pots, four parameters, so each pot edits two things depending on the
# page. The moment you turn a page, the pot is in the wrong place: it is
# still where you left it for the last parameter, and the new parameter's
# value is somewhere else entirely. Every solution to this is a trade:
#
#   JUMP    apply the pot immediately. The value leaps the instant you
#           touch it -- fine for a mixer, awful for a filter cutoff.
#   PICKUP  ignore the pot until it passes the value. Nothing leaps, but
#           the pot is dead until it crosses, which can be most of a turn
#           with no feedback at all.
#   SCALE   what ParamScaler does, and what a Deluge calls it. The value
#           always moves when you turn, but by an amount scaled so pot and
#           value converge and hit the end stops together.
#
# --- what to watch ----------------------------------------------------
#
# Set cutoff low with knobA -- low, but not against the stop, or there is
# nothing left for it to move. Tap the button to page 2, run knobA to the
# top, tap back to page 1. knobA is now at the top while cutoff is still
# low: a maximal mismatch. Now turn knobA down. Cutoff starts moving on
# the first count, gently, because it has little room left below it, and
# lands exactly on its minimum as the pot reaches its stop. Nothing
# jumped and nothing was dead.
#
# Turn knobA back up instead and the opposite happens: cutoff climbs fast,
# because the pot is near the top of its travel while the value has the
# whole range to cover, and the two arrive at the maximum together.
#
# The printout shows both positions on one line, `k` for the pot and `V`
# for the value, so the catch-up is visible without a screen:
#
#     p1 cutoff    1421 Hz  [-----V--------k-------]

import time

from synth_setup import keys, knobA, knobB, mixer
from synth_setup import synth as engine

from synthtools import ParamScaler, Patch, SubtractiveSynth

# ParamScaler works in 0-255, the resolution a knob is really worth; the
# pots read 0-65535, and 65535/256 is 255.
ADC_TO_255 = 1 / 256

# A raw AnalogIn never sits still, and ParamScaler is driven by DELTAS, so
# that noise is not harmless: its step is scaled by the runway on the side
# the knob moved toward, which makes the two directions asymmetric and turns
# symmetric noise into a RATCHET that walks the value onto the pot. The
# scaler's own deadband stops it, but only if the noise reaching it is
# smaller than the deadband -- so filter here as well. This is the same
# integer-domain EMA pico_test_synth's Hardware.read_pots() uses: it costs
# no float work and its lag is invisible at human knob speeds.
#
# 3, not 2. Measured against the scaler's 1-count deadband: an eighth-weight
# EMA holds an untouched value perfectly still through +/-2 counts of raw
# ADC noise, where a quarter-weight one starts leaking at +/-2. Realistic
# rp2040 noise is well under that (a 12-bit ADC at +/-5 LSB is +/-0.3
# counts of 255), so this is margin, not a tight fit.
KNOB_SHIFT = 3  # new reading gets 1/8 weight

# name, min, max, format, the SubtractiveSynth attribute it drives
# fmt: off
PARAMS = (
    ("cutoff",  100.0, 6000.0, "%6.0f Hz", "filt_f"),
    ("reso",      0.6,    6.0, "%6.1f   ", "filt_q"),
    ("attack",    0.0,    1.5, "%6.2f s ", "attack_time"),
    ("release",  0.02,    2.0, "%6.2f s ", "release_time"),
)
# fmt: on
NUM_KNOBS = 2
NUM_PAGES = len(PARAMS) // NUM_KNOBS

patch = Patch(
    name="scaler demo",
    wave="SAW",
    detune=1.0,
    filt_type="LPF",
    filt_f=1200,
    filt_q=1.4,
    amp_env=[0.01, 0.1, 0.7, 0.4],
)
synth = SubtractiveSynth(engine, patch)
mixer.voice[0].level = 0.6


_knob_filt = [knobA.value, knobB.value]


def read_knobs():
    """Both pots in ParamScaler's units, low-pass filtered."""
    for i, knob in enumerate((knobA, knobB)):
        # integer EMA on the raw 0-65535 reading; one multiply at the end
        _knob_filt[i] += (knob.value - _knob_filt[i]) >> KNOB_SHIFT
    return (_knob_filt[0] * ADC_TO_255, _knob_filt[1] * ADC_TO_255)


def to_param(i, scaled):
    """0-255 -> the parameter's own range."""
    _, vmin, vmax, _, _ = PARAMS[i]
    return vmin + (vmax - vmin) * scaled / 255


def to_scaled(i, val):
    """A parameter's value -> 0-255, for seeding a scaler."""
    _, vmin, vmax, _, _ = PARAMS[i]
    return 255 * (val - vmin) / (vmax - vmin)


# One scaler per PARAMETER, not per knob: each remembers where its pot was
# when that parameter was last on screen, and its own catch-up state.
# Seeded from the patch, so the demo starts consistent with what is
# actually sounding.
knobs = read_knobs()
scalers = []
for i in range(len(PARAMS)):
    attr = PARAMS[i][4]
    scalers.append(ParamScaler(to_scaled(i, getattr(synth, attr)), knobs[i % NUM_KNOBS]))

page = 0


def apply_page():
    """Push the current page's two scalers onto the synth."""
    for j in range(NUM_KNOBS):
        i = page * NUM_KNOBS + j
        setattr(synth, PARAMS[i][4], to_param(i, scalers[i].val))


def bar(knob, val, width=22):
    """One line showing where the pot is (k) and where the value is (V)."""
    cells = [" "] * width
    cells[min(int(knob * (width - 1) / 255), width - 1)] = "k"
    vi = min(int(val * (width - 1) / 255), width - 1)
    cells[vi] = "V" if cells[vi] == " " else "*"  # * = caught up
    return "[" + "".join(c if c != " " else "-" for c in cells) + "]"


def show():
    line = "p%d " % (page + 1)
    for j in range(NUM_KNOBS):
        i = page * NUM_KNOBS + j
        name, _, _, fmt, attr = PARAMS[i]
        line += "%-8s" % name + fmt % getattr(synth, attr)  # live, off the synth
        line += " " + bar(knobs[j], scalers[i].val) + "  "
    print(line)


print("paramscaler demo -- k is the pot, V is the value, * is caught up")
print("tap the button for the next page of two parameters")
apply_page()
show()

# something to listen to while you turn things
ARP = (36, 48, 43, 55)
step = 0
next_note = time.monotonic()
held = None
last_show = 0.0

while True:
    now = time.monotonic()

    if now >= next_note:
        next_note = now + 0.22
        if held is not None:
            synth.note_off(held)
        held = ARP[step % len(ARP)]
        synth.note_on(held, 100)
        step += 1

    if ev := keys.events.get():
        if ev.pressed:
            page = (page + 1) % NUM_PAGES
            # The two scalers coming on screen have stale knob memory --
            # their pots have been moving for the OTHER page. reset()
            # re-bases each to where its pot is now and drops the 1:1
            # lock, keeping the value. Without this the first update()
            # after a page turn reads one huge bogus delta.
            pots = read_knobs()
            for j in range(NUM_KNOBS):
                scalers[page * NUM_KNOBS + j].reset(knob_pos=pots[j])
            print()
            show()

    knobs = read_knobs()
    for j in range(NUM_KNOBS):
        scalers[page * NUM_KNOBS + j].update(knobs[j])
    apply_page()

    if now - last_show > 0.1:
        last_show = now
        show()
