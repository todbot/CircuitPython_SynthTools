# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# render_chords.py -- RENDER SIDE, runs under a CircuitPython "unix" build.
#
#   cd <repo> && micropython tests/render/render_chords.py \
#       --wave-lib <dir with adafruit_wave.py> --outdir tests/render/out
#
# Builds a real WavetableSynth on a real synthio.Synthesizer, presses chords,
# and pulls PCM offline via audiocore.get_buffer() (available because the
# coverage build sets CIRCUITPY_AUDIOCORE_DEBUG=1). Writes one WAV per case
# plus manifest.json for the CPython-side analyzer. No audio hardware, no
# audiofilewriter (not compiled into this build, and it is paced by a
# real-time pump the unix port does not run).
#
# Paths come in on argv, not an env var: os.getenv() truncates long values on
# this unix build.

import json
import os
import sys

_here = __file__.rsplit("/", 1)[0]
_argv = sys.argv[1:]
_wave_lib = None
for _i, _a in enumerate(_argv):
    if _a == "--wave-lib":
        _wave_lib = _argv[_i + 1]
if _wave_lib:
    sys.path.insert(0, _wave_lib)
sys.path.insert(0, _here)   # wavhdr
sys.path.insert(0, ".")     # synthtools (run from repo root)

import audiocore  # noqa: E402, I001
import audiomixer  # noqa: E402
import synthio  # noqa: E402
import ulab.numpy as np  # noqa: E402
from synthtools.patch import Patch  # noqa: E402  direct import: dodge __init__ lazy trap
from synthtools.wavetable_synth import WavetableSynth  # noqa: E402
from wavhdr import write_wav  # noqa: E402

WT_DIR = "examples/wavetables"
DEFAULT_WT = WT_DIR + "/BRAIDS02.WAV"
# fast attack, no decay, held full: worst case with no envelope confound
STEADY_ENV = [0.005, 0.0, 1.0, 0.05]
STOCK_ENV = [0.01, 0.10, 0.8, 0.35]      # Patch default
RENDER_FRAMES = 32768                    # ~0.74 s @ 44100
# BRAIDS02's full-scale frame: worst case for the limiter (see FINDINGS section 6)
WAVE_POS = 4


def build(sr, ch, wave_file, wave_pos, filt_type, filt_q, env):
    eng = synthio.Synthesizer(sample_rate=sr, channel_count=ch)
    p = Patch(
        synth_type="wavetable",
        wave_file=wave_file,
        wave_pos=wave_pos,
        wave_pos_max=0,        # <= wave_pos: the wave-LFO sweep is off, update() is a no-op
        wave_lfo_vel=0.0,
        filt_type=filt_type,
        filt_q=filt_q,
        amp_env=list(env),
        vib_depth=0.0,
        penv_amount=0.0,
        penv_out_amount=0.0,
        fenv_amount=0,
        filt_lfo_amount=0,
        filt_vel=0,
        filt_track=0.0,
    )
    return eng, WavetableSynth(eng, p)


def scale_wavetable(syn, factor):
    """Attenuate the shared wave buffer in place (identity preserved: the
    Notes hold it by reference). Simulates load-time normalization."""
    if factor == 1.0:
        return
    buf = syn._wavetable.waveform
    src = np.frombuffer(bytes(buf), dtype=np.int16)
    buf[:] = np.array(src * factor, dtype=np.int16)


def render(eng, n_frames, ch):
    got = 0
    chunks = []
    while got < n_frames:
        gbr, mv = audiocore.get_buffer(eng)
        if gbr == 2:
            raise RuntimeError("audiocore.get_buffer error")
        chunks.append(bytes(mv))
        got += len(mv) // ch
        if gbr == 0:
            break
    pcm = b"".join(chunks)
    return pcm[: n_frames * ch * 2]


def vel_for_amp(amp):
    return max(1, min(127, int(round(127 * amp))))


# --- chord shapes -------------------------------------------------------------
CHORDS = {
    1: (45,),
    2: (45, 52),
    3: (45, 52, 57),
    4: (45, 52, 57, 64),
    5: (45, 52, 57, 64, 69),
    6: (45, 52, 57, 64, 69, 76),
}
SPREAD = {3: (31, 50, 70), 6: (26, 43, 58, 71, 83, 94)}


def case(cid, group, notes, note_amp=1.0, wt_scale=1.0, mixer_level=0.25,
         sr=44100, ch=1, wave_file=DEFAULT_WT, wave_pos=WAVE_POS,
         filt_type=None, filt_q=1.1, env=None, raw_notes=False,
         through_mixer=False, wt_headroom=None):
    return dict(id=cid, group=group, notes=list(notes), note_amp=note_amp,
                wt_scale=wt_scale, mixer_level=mixer_level, sr=sr, ch=ch,
                wave_file=wave_file, wave_pos=wave_pos, filt_type=filt_type,
                filt_q=filt_q, env=list(env or STEADY_ENV), raw_notes=raw_notes,
                through_mixer=through_mixer, wt_headroom=wt_headroom)


def build_cases():
    cs = []

    # 1. mechanism: peak/rms/crest vs voice count, filter OFF and stock LPF
    for n, notes in CHORDS.items():
        cs.append(case("mech_n%d" % n, "mech", notes, filt_type=None))
        cs.append(case("mech_lpf_n%d" % n, "mech_lpf", notes, filt_type="LPF"))
    for n, notes in SPREAD.items():
        cs.append(case("mech_spread_n%d" % n, "spread", notes, filt_type=None))
    # stock default patch (stock env + LPF), the user's real-world case
    for n in (3, 4, 5):
        cs.append(case("stock_n%d" % n, "stock", CHORDS[n], filt_type="LPF", env=STOCK_ENV))

    # 2. notional pre-limiter peak: render provably-linear, analyzer scales back by 1/wt_scale
    for n, notes in CHORDS.items():
        s = 1.0 / (2 * n)
        cs.append(case("notional_n%d" % n, "notional", notes, wt_scale=s, filt_type=None))

    # 3. per-note hard-clip path: single note, resonance sweep
    for q in (0.7, 1.1, 2.0, 4.0, 6.0):
        cs.append(case("q_%s" % str(q).replace(".", "p"), "q", CHORDS[1],
                       filt_type="LPF", filt_q=q))

    # 4. aliasing A/B: same triad at the rig rate vs 44100, filter off (exposes highs)
    cs.append(case("alias_44100", "alias", CHORDS[3], sr=44100, ch=1, filt_type=None))
    cs.append(case("alias_22050", "alias", CHORDS[3], sr=22050, ch=1, filt_type=None))

    # 5. mitigations, N = 3/4/5 (+ n1 loudness anchor)
    import math
    for n in (1, 3, 4, 5):
        notes = CHORDS[n]
        cs.append(case("mit_base_n%d" % n, "mit", notes, filt_type=None))
        cs.append(case("mit_wt50_n%d" % n, "mit", notes, wt_scale=0.5, filt_type=None))
        cs.append(case("mit_wt35_n%d" % n, "mit", notes, wt_scale=0.35, filt_type=None))
        cs.append(case("mit_head50_n%d" % n, "mit", notes, note_amp=0.5, filt_type=None))
        cs.append(case("mit_sqrtn_n%d" % n, "mit", notes, note_amp=1.0 / math.sqrt(n),
                       filt_type=None))
        # mixer-only control: identical bus render, analyzer applies level 0.5
        cs.append(case("mit_mixer_n%d" % n, "mit", notes, mixer_level=0.5, filt_type=None))
        # recommended combo: wavetable at 0.5 + mixer makeup to 0.5
        cs.append(case("mit_combo_n%d" % n, "mit", notes, wt_scale=0.5, mixer_level=0.5,
                       filt_type=None))

    # 6. verify audiomixer.Mixer's own int16 stage: same bus through a REAL
    #    Mixer at the recommended makeup gain, vs the analyzer's scalar model
    for n in (4, 6):
        cs.append(case("mixchk_scalar_n%d" % n, "mixchk", CHORDS[n],
                       wt_scale=0.5, mixer_level=0.5, filt_type=None))
        cs.append(case("mixchk_real_n%d" % n, "mixchk", CHORDS[n],
                       wt_scale=0.5, mixer_level=0.5, filt_type=None,
                       through_mixer=True))

    # 7. the SHIPPED fix: real _make_notes path, WavetableSynth.WT_HEADROOM
    #    1.0 (old) vs 0.5 (new) with the 0.25 -> 0.5 mixer makeup
    for n in (3, 4, 5):
        cs.append(case("ship_raw_n%d" % n, "ship", CHORDS[n],
                       filt_type=None, wt_headroom=1.0, mixer_level=0.25))
        cs.append(case("ship_fixed_n%d" % n, "ship", CHORDS[n],
                       filt_type=None, wt_headroom=0.5, mixer_level=0.5))

    return cs


def run_case(c):
    eng, syn = build(c["sr"], c["ch"], c["wave_file"], c["wave_pos"],
                     c["filt_type"], c["filt_q"], c["env"])
    scale_wavetable(syn, c["wt_scale"])
    vel = vel_for_amp(c["note_amp"])
    if c["raw_notes"]:
        f0 = synthio.midi_to_hz(c["notes"][0])
        eng.press([synthio.Note(f0, waveform=syn._wave, amplitude=c["note_amp"])
                   for _ in c["notes"]])
    elif c["wt_headroom"] is not None:
        # exercise the shipped _make_notes path: no amplitude override
        WavetableSynth.WT_HEADROOM = c["wt_headroom"]
        for n in c["notes"]:
            syn.note_on(n, 127)
        WavetableSynth.WT_HEADROOM = 0.5
    else:
        for n in c["notes"]:
            syn.note_on(n, vel)
        # exact amplitude, bypassing velocity/127 quantization
        for notes in syn.voices.values():
            for note in notes:
                note.amplitude = c["note_amp"]
    src = eng
    if c["through_mixer"]:
        mix = audiomixer.Mixer(voice_count=1, sample_rate=c["sr"],
                               channel_count=c["ch"], bits_per_sample=16,
                               samples_signed=True, buffer_size=2048)
        mix.voice[0].play(eng)
        mix.voice[0].level = c["mixer_level"]
        src = mix
    return render(src, RENDER_FRAMES, c["ch"])


def main():
    outdir = "tests/render/out"
    only = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--outdir":
            outdir = args[i + 1]
            i += 2
        elif args[i] == "--only":
            only = args[i + 1]
            i += 2
        elif args[i] == "--wave-lib":
            i += 2
        else:
            i += 1

    try:
        os.mkdir(outdir)
    except OSError:
        pass

    cases = build_cases()
    if only:
        cases = [c for c in cases if c["id"] == only or c["group"] == only]

    manifest = []
    for c in cases:
        pcm = run_case(c)
        path = outdir + "/" + c["id"] + ".wav"
        write_wav(path, pcm, c["sr"], c["ch"])
        c["frames"] = len(pcm) // (c["ch"] * 2)
        manifest.append(c)
        print("%-18s notes=%-22s sr=%d wt_scale=%.4f -> %s"
              % (c["id"], c["notes"], c["sr"], c["wt_scale"], path))

    with open(outdir + "/manifest.json", "w") as f:
        json.dump(manifest, f)
    print("wrote %d cases + manifest.json to %s" % (len(manifest), outdir))


main()
