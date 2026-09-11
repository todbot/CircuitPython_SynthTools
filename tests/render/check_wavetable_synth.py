# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# check_wavetable_synth.py -- WavetableSynth correctness under a real
# CircuitPython unix build (real synthio, real adafruit_wave). Pass/fail,
# not measurement: for sound-quality/THD numbers see render_chords.py +
# analyze_renders.py; for Wavetable.set_wave_pos() lerp correctness see
# check_wavetable.py. This is the synth-level contract in between --
# construction, wave_pos/wave_lfo_range/wave_lfo_rate, set_param(), and
# save_patch()/load_patch().
#
#   micropython tests/render/check_wavetable_synth.py --wave-lib <dir with adafruit_wave.py>
#
# Run from the repo root. Exits non-zero on any failure.

import sys

_argv = sys.argv[1:]
for _i, _a in enumerate(_argv):
    if _a == "--wave-lib":
        sys.path.insert(0, _argv[_i + 1])
sys.path.insert(0, ".")

import synthio  # noqa: E402

from synthtools.patch import Patch  # noqa: E402
from synthtools.synth import Synth  # noqa: E402
from synthtools.wavetable_synth import WavetableSynth  # noqa: E402

WAV = "examples/wavetables/BRAIDS02.WAV"
WAV2 = "examples/wavetables/PLAITS02.WAV"

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)
        print("FAIL:", msg)


def build(**kw):
    eng = synthio.Synthesizer(sample_rate=44100, channel_count=1)
    p = Patch(synth_type="wavetable", wave_file=WAV, filt_type=None, **kw)
    return eng, WavetableSynth(eng, p)


def lfo_snapshot(syn):
    lfo = syn._wave_lfo_mid.a
    return (lfo.rate, lfo.scale, lfo.offset)


def is_silent(buf):
    return all(int(x) == 0 for x in buf)


# --- a freshly constructed synth is already audible ---------------------
# nothing should need update() or a second call before a note is audible.
eng, syn = build(wave_pos=4)
ck(
    not is_silent(syn._wavetable.waveform),
    "a freshly constructed WavetableSynth's buffer is all zero -- "
    "nothing seeds it via set_wave_pos() at construction",
)

# --- wave_pos / wave_lfo_range / wave_lfo_rate round-trip ----------------
syn.wave_pos = 7
ck(syn.wave_pos == 7, "wave_pos getter didn't return what was set")
syn.wave_lfo_range = 3
ck(syn.wave_lfo_range == 3, "wave_lfo_range getter didn't return what was set")
syn.wave_lfo_rate = 2.0
ck(syn.wave_lfo_rate == 2.0, "wave_lfo_rate getter didn't return what was set")

# --- update() actually moves the shared buffer ---------------------------
eng, syn = build(wave_pos=0)
n = syn.num_waves
eng, syn = build(wave_pos=0, wave_lfo_range=n - 1, wave_lfo_rate=5.0)
before = list(syn._wavetable.waveform)
for _ in range(20):
    syn.update()
after = list(syn._wavetable.waveform)
ck(before != after, "20 update() calls with a running sweep left the buffer unchanged")

# --- note_on()/note_off() basic sanity, through the public API only ------
eng, syn = build(wave_pos=0)
syn.note_on(48)
ck(
    48 in syn.voices and len(syn.voices[48]) == 1,
    "note_on(48) should leave exactly one Note in syn.voices[48]",
)
syn.note_off(48)
ck(48 not in syn.voices, "note_off(48) should remove the voice")

# --- set_param() reaches every WavetableSynth-specific param -------------
wt_only = [n for n in WavetableSynth._PARAMS if n not in Synth._PARAMS]
range_params = [n for n in wt_only if n not in ("wave_file", "wave_pos", "wave_lfo_rate")]
ck(
    len(range_params) == 1,
    "expected exactly one wave-position-range param in _PARAMS, found %r" % (range_params,),
)

eng, syn = build(wave_pos=0, wave_lfo_range=1)
for name, val in (("wave_pos", 20), ("wave_lfo_rate", 9.0)):
    before = lfo_snapshot(syn)
    try:
        syn.set_param(name, val)
    except Exception as e:
        ck(False, "set_param(%r, ...) raised %r" % (name, e))
        continue
    ck(lfo_snapshot(syn) != before, "set_param(%r, ...) had no effect on the live sweep" % name)

for name in range_params:
    before = lfo_snapshot(syn)
    try:
        syn.set_param(name, 55)
    except Exception as e:
        ck(False, "set_param(%r, ...) raised %r" % (name, e))
        continue
    ck(lfo_snapshot(syn) != before, "set_param(%r, ...) had no effect on the live sweep" % name)

# --- wave_file setter updates what a NEW note actually plays -------------
eng, syn = build(wave_pos=0)
old_wave = syn._wave
try:
    syn.wave_file = WAV2
except Exception as e:
    ck(False, "wave_file setter raised %r" % (e,))
else:
    ck(syn.wave_file == WAV2, "wave_file getter didn't reflect the new file")
    ck(
        syn._wave is not old_wave,
        "wave_file change left synth._wave pointing at the old file's buffer",
    )

# --- save_patch()/load_patch() round trip, no crash, no leaked blocks ----
eng, syn = build(wave_pos=5, wave_lfo_range=2, wave_lfo_rate=0.3)
n0 = len(eng.blocks)
patch = None
try:
    patch = syn.save_patch()
except Exception as e:
    ck(False, "save_patch() raised %r" % (e,))
else:
    ck(getattr(patch, "wave_file", None) == WAV, "save_patch() didn't preserve wave_file")

if patch is not None:
    try:
        syn.load_patch(patch)
    except Exception as e:
        ck(False, "load_patch() of a just-saved patch raised %r" % (e,))
n1 = len(eng.blocks)
ck(n1 == n0, "load_patch() added %d block(s) to engine.blocks (expected 0)" % (n1 - n0))

if fails:
    print("\n%d failure(s)" % len(fails))
    sys.exit(1)
print("\ncheck_wavetable_synth: all checks passed")
