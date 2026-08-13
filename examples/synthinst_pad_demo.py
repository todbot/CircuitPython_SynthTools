# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthinst_pad_demo.py -- slow filter sweeps under sustained chords.
#
# Copy flat onto CIRCUITPY beside synth_setup.py and the synthtools/ package,
# then either rename it code.py or, from the serial REPL:
#
#     import synthinst_pad_demo
#
# The third of the three: synthinst_fenv_demo.py is the filter as a plucky
# attack gesture, synthinst_pitch_demo.py is everything reaching note.bend,
# and this one is the filter moving SLOWLY under held chords -- where the
# envelope's shape and the filter LFO actually become audible as motion
# rather than as a transient.
#
# --- the polyphony budget ---------------------------------------------
# synth.max_polyphony is 24 on rp2040 (measured; the synthio stub docstring
# still claims 12 and is out of date). SubtractiveSynth spends TWO Notes
# per key whenever detune != 1.0, and releasing notes hold their slots
# until the amp envelope finishes -- and with a 2.6s release, chords here
# DO overlap. So:
#
#     4-note chord, detune on  ->  8 Notes, 16 while two chords overlap
#     5-note chord, detune on  -> 10 Notes, 20 while two chords overlap
#
# Both fit. Detune stays on, which matters on a pad -- two slightly
# mistuned saws per key is most of what makes it sound wide. Go past
# 5-note chords and the arithmetic is worth redoing.
#
# --- slow is a different regime ---------------------------------------
# The plucky demo had to fight the ~30ms floor (synthio updates blocks
# every 256 samples, so a 0.02s attack is a click, not a sweep). Nothing
# here goes near that. The opposite constraint applies instead: AHR holds
# at PEAK for as long as the key is down, so a slow attack only reads if
# the chord is held LONGER than fenv_attack. Every hold below is at least
# twice its attack.

import time

from synth_setup import synth as engine
from synthtools import Patch, SubtractiveSynth

patch = Patch(
    name="slowpad",
    wave="SAW",
    detune=1.004,        # two Notes per key -- see the polyphony note above
    filt_type="LPF",
    # A low floor and real resonance. Resonance is what makes a slow sweep
    # audible as MOVEMENT -- at filt_q 0.7 a slow sweep just sounds like a
    # tone control being turned, with no character to track.
    filt_f=180,
    filt_q=1.9,
    fenv_amount=5000,
    fenv_attack=2.5,
    fenv_release=2.5,
    fenv_curve=1,
    filt_lfo_rate=0.5,
    filt_lfo_amount=0,
    # Pad amp envelope. The release (2.6) must OUTLAST fenv_release, or the
    # voice is freed part-way down and the filter sweep is cut short --
    # it sounds like a broken envelope but is just the note ending.
    amp_env=[0.35, 0.3, 0.85, 2.6],
)

synth = SubtractiveSynth(engine, patch)

Am = (45, 52+12, 57, 60)     # A2 E4 A3 C4
G = (43, 50, 55, 59)      # G2 D3 G3 B3


def chord(label, notes=Am, secs=6.0, vels=None, tail=2.8):
    """Press a chord, hold it, release it, and let the tail finish.

    `tail` has to cover the amp release or the next chord stacks on top of
    a still-sounding one and eats the polyphony budget.
    """
    print(label)
    for i, n in enumerate(notes):
        synth.note_on(n, velocity=vels[i] if vels else 105)
    time.sleep(secs)
    for n in notes:
        synth.note_off(n)
    time.sleep(tail)


def stagger(label, notes=Am, gap=0.9, secs=5.0, tail=2.8):
    """Enter the notes one at a time, then hold and release together."""
    print(label)
    for n in notes:
        synth.note_on(n, velocity=105)
        time.sleep(gap)
    time.sleep(secs)
    for n in notes:
        synth.note_off(n)
    time.sleep(tail)


while True:
    print()
    print("=== the envelope as slow motion ===")

    # 1. reference: filter parked, nothing moves
    synth.fenv_amount = 0
    chord("fenv_amount=0      -- static filter, dull and unmoving", secs=2)

    # 2. the classic slow swell. Held 6s against a 2.5s attack, so you hear
    #    the sweep finish and then sit at the top for a while.
    synth.fenv_amount = 5000
    synth.fenv_attack = 2.5
    chord("fenv_attack=2.5    -- slow swell up to 5180 Hz, then holds")

    # 3. slower still, and held longer to contain it
    synth.fenv_attack = 5.0
    chord("fenv_attack=5.0    -- a very slow open, held 7s", secs=6.0)
    synth.fenv_attack = 2.5

    # 4. the release half. fenv_release 2.5 under an amp release of 2.6:
    #    the filter closes as the chord fades, which is most of what makes
    #    a pad sound like it is being played rather than switched off.
    synth.fenv_release = 2.5
    chord("fenv_release=2.5   -- listen past the key release, it closes down",
          secs=4.0, tail=3.5)

    # 5. curve. On a plucky note this is nearly inaudible; over 2.5s it is
    #    obvious. 1 is a straight line; 3 snaps open early then eases into
    #    the top, and drops away fast on release with a long tail.
    synth.fenv_curve = 3
    chord("fenv_curve=3       -- same times, front-loaded: opens early",
          secs=6.0, tail=3.5)
    synth.fenv_curve = 1

    print()
    print("=== the filter LFO as slow motion ===")

    # 6. a very slow LFO is the other way to get movement, and unlike the
    #    envelope it never stops. 0.08 Hz is a 12.5s cycle, so a 12s chord
    #    gets about one full sweep up and back.
    #    Remember the LFO is ADDITIVE: filt_f is the FLOOR and it opens
    #    0..amount upward, so put the floor low and let amount do the work.
    synth.fenv_amount = 0
    synth.filt_lfo_rate = 0.1
    synth.filt_lfo_amount = 2000
    chord("filt_lfo 2000 @ 0.1Hz -- one slow sweep up and back, no envelope",
          secs=12.0)

    # 7. both at once. The envelope opens it on the attack, the LFO keeps
    #    it moving afterwards -- they SUM on one cutoff, so the envelope's
    #    5000 raises the floor the LFO wobbles around.
    synth.fenv_amount = 3000
    synth.filt_lfo_amount = 2500
    synth.filt_lfo_rate = 0.12
    chord("fenv + slow LFO    -- envelope opens it, LFO keeps it breathing",
          secs=12.0)
    synth.filt_lfo_amount = 0
    synth.fenv_amount = 5000

    print()
    print("=== the envelope is PER VOICE, not per synth ===")

    # 8. Same chord, but each note struck at a different velocity, with
    #    fenv_vel at 1.0 so depth tracks velocity. Each voice sweeps to a
    #    different brightness and they pull apart as the chord opens.
    #    A single global envelope could not do this.
    synth.fenv_vel = 1.0
    chord("fenv_vel=1.0       -- one chord, four velocities, four sweeps",
          vels=(40, 70, 100, 127), secs=8.0)
    synth.fenv_vel = 0.0

    # 9. The same point in time rather than in depth: notes entering 0.9s
    #    apart each start their OWN envelope from zero, so the chord opens
    #    as a staircase instead of all at once.
    stagger("staggered entry   -- each voice sweeps on its own clock")

    print()
    print("=== a whole progression, everything on ===")

    # 10. what it is all for
    synth.fenv_amount = 4500
    synth.fenv_attack = 1.8
    synth.fenv_release = 2.2
    synth.fenv_curve = 2
    synth.filt_lfo_amount = 1200
    synth.filt_lfo_rate = 0.1
    for label, notes in (("Am", Am), ("G", G), ("Am", Am), ("G", G)):
        chord("  %s" % label, notes=notes, secs=5.0, tail=2.0)
    synth.filt_lfo_amount = 0
    synth.fenv_attack = 2.5
    synth.fenv_release = 2.5
    synth.fenv_curve = 1

    # Nothing above touched `patch`. To keep the current sound:
    #   synth.save_patch().save("/slowpad.json")   # needs storage.remount()
