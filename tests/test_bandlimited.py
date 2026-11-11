# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Checks for the band-limited SAW_BL/SQU_BL tables in synthtools/waves.py
and the HEADROOM class attribute on SubtractiveSynth/FMSynth.

The spectral checks (nothing above each table's harmonic limit, no even
harmonics in the square) need real numpy's FFT, so they only run on the
CPython tier. The rest (peaks, which table a note picks, cache keys,
wiring into the synths) runs on both.

    python3 tests/test_bandlimited.py
    micropython tests/test_bandlimited.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/stubs")
sys.path.insert(0, _D + "/..")

import synthio  # noqa: E402
from synthtools import FMSynth, Patch, SubtractiveSynth  # noqa: E402
from synthtools.waves import (  # noqa: E402
    BL_MARGIN, BL_SIZE, _bl_cache, _bl_kmax, get_wave_2x, get_wave_bl,
    random_phase_wave,
)

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def in_table(w, t2x):
    """True if ``w`` is some window of the two-cycle table ``t2x``."""
    n = len(w)
    first = w[0]
    wl = list(w)
    for start in range(n):
        if t2x[start] == first and list(t2x[start : start + n]) == wl:
            return True
    return False


VOL = 28000

# --- the tables themselves ------------------------------------------------
for name in ("SAW_BL", "SQU_BL"):
    for sr in (22050, 44100):
        tabs = get_wave_bl(name, sr)
        ck(len(tabs) == 128, "%s/%d: one entry per midi note" % (name, sr))
        ck(get_wave_bl(name, sr) is tabs, "%s/%d: must be cached" % (name, sr))
        for m in range(128):
            ck(tabs[m] is tabs[(m // 12) * 12],
               "%s/%d: midi %d must share its octave's table" % (name, sr, m))
        for octave in range(11):
            t = tabs[min(127, octave * 12)]
            ck(len(t) == 2 * BL_SIZE, "%s/%d: tables are two cycles" % (name, sr))
            peak = max(max(t), -min(t))
            ck(peak <= VOL, "%s/%d oct %d: peak %d over volume" % (name, sr, octave, peak))
            ck(list(t[:BL_SIZE]) == list(t[BL_SIZE:]),
               "%s/%d oct %d: both cycles must match" % (name, sr, octave))
            # the harmonic limit: alias-free at the octave's top note plus
            # the margin, and not one harmonic duller than that allows
            kmax = _bl_kmax(octave, sr, BL_SIZE)
            top = hz(octave * 12 + 11 + BL_MARGIN)
            ck(kmax == 1 or kmax * top <= sr / 2,
               "%s/%d oct %d: kmax %d aliases at the top note" % (name, sr, octave, kmax))
            ck(kmax == BL_SIZE // 2 - 1 or kmax == 1 or (kmax + 1) * top > sr / 2,
               "%s/%d oct %d: kmax %d is needlessly dull" % (name, sr, octave, kmax))

ck(get_wave_bl("SAW_BL", 22050) is not get_wave_bl("SAW_BL", 44100),
   "a different sample rate must build a different set")
ck(_bl_kmax(5, 44100, BL_SIZE) > _bl_kmax(5, 22050, BL_SIZE),
   "a higher sample rate must allow more harmonics")

# --- spectra (real numpy only) --------------------------------------------
try:
    import numpy as rnp
except ImportError:
    rnp = None
if rnp is not None:
    for name in ("SAW_BL", "SQU_BL"):
        tabs = get_wave_bl(name, 22050)
        for octave in range(11):
            t = rnp.array(tabs[min(127, octave * 12)][:BL_SIZE], dtype=float)
            p = rnp.abs(rnp.fft.rfft(t)) ** 2
            kmax = _bl_kmax(octave, 22050, BL_SIZE)
            above = p[kmax + 1 :].sum() / p[1 : kmax + 1].sum()
            ck(above < 1e-8, "%s oct %d: %.1f dB above kmax"
               % (name, octave, 10 * rnp.log10(max(above, 1e-30))))
            if name == "SQU_BL":
                even = p[2 : kmax + 1 : 2].sum() / p[1 : kmax + 1 : 2].sum()
                ck(even < 1e-8, "SQU_BL oct %d: even harmonics present" % octave)

# --- random_phase_wave ----------------------------------------------------
w = random_phase_wave("SAW", midi_note=100, sample_rate=22050)
ck(len(w) == 256, "a plain name must ignore midi_note, got len %d" % len(w))
ck(in_table(w, get_wave_2x("SAW")), "a plain name must slice get_wave_2x()")
w = random_phase_wave("SAW_BL", midi_note=69, sample_rate=22050)
ck(len(w) == BL_SIZE, "a band-limited name is BL_SIZE long, got %d" % len(w))
ck(in_table(w, get_wave_bl("SAW_BL", 22050)[69]), "SAW_BL must slice its note's table")
w = random_phase_wave("SAW_BL", midi_note=130, sample_rate=22050)
ck(in_table(w, get_wave_bl("SAW_BL", 22050)[127]), "a note past 127 must use the top table")

# --- SubtractiveSynth -------------------------------------------------------
_bl_cache.clear()
sio = synthio.Synthesizer(sample_rate=22050)
s = SubtractiveSynth(sio, Patch(wave="SAW_BL", detune=1.0))
ck(("SAW_BL", BL_SIZE, 22050) in _bl_cache,
   "_recompile must warm the band-limited set so note-on never builds it")
tabs = get_wave_bl("SAW_BL", 22050)

s.note_on(60, 127)
n1 = s.voices[60][0]
ck(abs(n1.amplitude - SubtractiveSynth.HEADROOM) < 1e-9,
   "single osc amplitude must be HEADROOM at vel 127, got %r" % n1.amplitude)
ck(in_table(n1.waveform, tabs[60]), "osc1 must use its note's table")
s.all_notes_off()

s.detune = 1.5  # a fifth: 65 + 7 = 72 crosses into the next octave's table
ck(s._detune_semis == 7, "detune 1.5 must be 7 semitones, got %r" % s._detune_semis)
s.note_on(65, 127)
o1, o2 = s.voices[65]
ck(in_table(o1.waveform, tabs[65]), "detuned osc1 must use midi 65's table")
ck(in_table(o2.waveform, tabs[72]), "osc2 must pick its table from its own pitch")
ck(tabs[65] is not tabs[72], "test premise: 65 and 72 must be in different octaves")
ck(abs(o1.amplitude - 0.666 * SubtractiveSynth.HEADROOM) < 1e-9,
   "detuned osc amplitude must be 0.666 * HEADROOM, got %r" % o1.amplitude)
s.all_notes_off()

s.detune = 1.003
ck(s._detune_semis == 0, "a chorus-sized detune must stay inside the margin")
s.detune = 0.5
ck(s._detune_semis == 0, "a detune below unison must not shift the table")
s.detune = 1.0
s.load_patch(Patch(wave="SAW_BL", detune=2.0))
ck(s._detune_semis == 12, "_recompile must set _detune_semis, got %r" % s._detune_semis)

old = SubtractiveSynth.HEADROOM
SubtractiveSynth.HEADROOM = 0.25
s.load_patch(Patch(wave="SAW", detune=1.0))
s.note_on(60, 127)
ck(abs(s.voices[60][0].amplitude - 0.25) < 1e-9, "HEADROOM must be read per note-on")
s.all_notes_off()
SubtractiveSynth.HEADROOM = old

_bl_cache.clear()
s.wave = "SQU_BL"
ck(("SQU_BL", BL_SIZE, 22050) in _bl_cache, "the wave setter must warm the set")

# --- FMSynth ----------------------------------------------------------------
fm = FMSynth(sio, Patch(wave="SAW_BL", fm_index=0.0))
fm.note_on(81, 127)
n = fm.voices[81][0]
ck(in_table(n.waveform, tabs[81]), "FM-off must use the note's band-limited table")
ck(abs(n.amplitude - FMSynth.HEADROOM) < 1e-9, "FM amplitude must carry HEADROOM")
fm.all_notes_off()
fm.fm_index = 1.5
fm.note_on(81, 127)
n = fm.voices[81][0]
ck(n.waveform is fm._pm_wave, "FM-on must still use the shared PM table")
ck(abs(n.amplitude - FMSynth.HEADROOM) < 1e-9, "FM-on amplitude must carry HEADROOM")
fm.all_notes_off()

print()
if fails:
    print("FAILURES (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_bandlimited: all checks passed")
