# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# synthtools_swarm_demo.py -- the Dewanatron Swarmatron gesture: eight
# oscillators on one pitch, pulled apart and back under a held drone.
#
# Copy flat onto CIRCUITPY beside synth_setup.py and the synthtools/ package,
# then either rename it code.py or, from the serial REPL:
#
#     import synthtools_swarm_demo
#
# The real instrument has two ribbons (one for pitch, one for the swarm
# span) and "taffy pulling" the two together is what it is for. There are
# only two knobs on this breadboard, so phase 2 below plays that gesture
# automatically; wire knobA to swarm_spread if you have the hardware.
#
# --- the polyphony budget ---------------------------------------------
# synth.max_polyphony is 24 on rp2040 (measured; the synthio stub docstring
# still claims 12 and is out of date). A swarm costs swarm_count Notes per
# key, each with its own Biquad (filters hold state, so they cannot be
# shared) and one Math for its bend. So:
#
#     swarm_count 8, mono  ->  8 Notes, 16 while a steal overlaps the
#                              releasing swarm with the new one
#     swarm_count 8, poly  ->  24 at THREE keys, i.e. the whole budget
#
# Hence SwarmSynth is mono by default. If you want chords, drop
# swarm_count to 4 first, THEN set synth.mono = False.
#
# --- why it is quiet --------------------------------------------------
# Eight detuned oscillators beat, so their peaks periodically DO line up.
# Each Note is amplitude velocity/127/swarm_count so that worst case still
# tops out at 1.0 instead of 8.0. Make the level back up at the mixer,
# which is what the line below does.

import time

from synth_setup import mixer
from synth_setup import synth as engine

from synthtools import Patch, SwarmSynth

mixer.voice[0].level = 0.8  # see "why it is quiet" above

# A slow, sustained drone patch: the swarm IS the timbre, so the filter is
# mostly out of the way and the amp envelope is long enough that the spread
# has time to move while the note is still loud.
# fmt: off
patch = Patch(name="swarm", synth_type="swarm", wave="SAW",
              swarm_count=8, swarm_spread=0.008, swarm_drift=0.003,
              filt_type="LPF", filt_f=2200, filt_q=0.7,
              amp_env=[0.6, 0.2, 0.9, 1.2],
              vib_rate=0.0, vib_depth=0.0)
# fmt: on

synth = SwarmSynth(engine, patch)
synth.glide_time = 0.35  # the pitch ribbon's glissando, roughly

print("swarm demo: %d oscillators, mono=%s" % (synth.swarm_count, synth.mono))


def sweep(param, start, end, seconds, steps=60):
    """Ramp one live parameter, in Python, over `seconds`.

    Every write is ONE write into a shared block that reaches all eight
    sounding oscillators: that is the design claim this demo exists to
    show. Sweeping SubtractiveSynth's `detune` the same way would loop over
    every live Note on every step.
    """
    for i in range(steps + 1):
        setattr(synth, param, start + (end - start) * i / steps)
        time.sleep(seconds / steps)


while True:
    # --- 1. the swarm itself: unison opening out to a chorus -----------
    # Held throughout, so you hear the spread MOVE rather than hearing
    # eight separately-tuned notes start.
    print("1: unison -> chorus, on a held drone")
    synth.swarm_spread = 0.0
    # glide=0 on every SECTION-OPENING note. mono keeps _last_midi across
    # silence (it is never cleared by note_off) so without this the
    # first note of a section slides in from the previous section's pitch,
    # audibly: 5 semitones here and again entering section 3. Slides within
    # a section are wanted; slides across a two-second gap are not.
    # (glide=0 does not SKIP the glide, it runs it in 1ms: inside one
    # 5.8ms block, so it never renders.)
    synth.note_on(43, velocity=110, glide=0)  # G2
    time.sleep(1.0)
    sweep("swarm_spread", 0.0, 0.02, 4.0)  # 0 -> +/-24 cents
    time.sleep(1.0)
    sweep("swarm_spread", 0.02, 0.0, 3.0)
    time.sleep(0.5)

    # --- 2. taffy pull: span and pitch moving together ------------------
    # Dewanatron's own word for it. The spread opens out to an equidistant
    # chord spread over octaves while the root walks: glide_time makes
    # each step a slide rather than a jump, so the whole cluster smears.
    print("2: taffy pull; span opening while the root walks")
    for i, note in enumerate((43, 46, 50, 53, 55, 62)):
        synth.note_on(note, velocity=110)
        sweep("swarm_spread", 0.02 + i * 0.12, 0.02 + (i + 1) * 0.12, 1.6)
    time.sleep(1.0)
    # ...and collapse the octave-wide cluster back to a single pitch
    sweep("swarm_spread", 0.5, 0.0, 5.0)
    synth.note_off(53)
    time.sleep(2.0)

    # --- 3. drift is what stops a fixed fan sounding like a chorus -----
    # Same spread both times: first with every oscillator frozen at its
    # exact ratio, then wandering. The second one breathes.
    print("3: drift off, then on; same spread both times")
    synth.swarm_spread = 0.012
    for drift in (0.0, 0.008):
        synth.swarm_drift = drift
        print("   drift %.3f" % drift)
        synth.note_on(48, velocity=110, glide=0)  # section opener, see above
        time.sleep(5.0)
        synth.note_off(48)
        time.sleep(1.5)
    synth.swarm_drift = 0.003

    # --- 4. oscillator count, from a solo to the full swarm ------------
    # swarm_count applies at the NEXT note-on, so each step is its own note.
    print("4: 1, 2, 4, 8 oscillators")
    synth.swarm_spread = 0.015
    for count in (1, 2, 4, 8):
        synth.swarm_count = count
        synth.note_on(48, velocity=110, glide=0)  # section opener, see above
        time.sleep(2.2)
        synth.note_off(48)
        time.sleep(0.6)
    synth.swarm_count = 8
