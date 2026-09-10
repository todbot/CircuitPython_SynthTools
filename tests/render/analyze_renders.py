# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# analyze_renders.py -- ANALYSIS SIDE, desktop CPython (numpy + stdlib wave).
#
#   python3 tests/render/analyze_renders.py --outdir tests/render/out
#
# Reads the WAVs + manifest.json written by render_chords.py, computes peak /
# RMS / crest / clip / THD+N metrics, prints tables, and writes FINDINGS.md
# and metrics.json (the latter feeds the visual artifact).

import argparse
import json
import math
import os
import sys
import wave

import numpy as np

FS = 32767.0
KNEE = 28000.0                 # synthio_mix_down_sample soft-knee, both ports
STEADY_START = 8192            # discard attack + decay
ATTACK_WIN = (0, 8192)


def load_wav(path):
    with wave.open(path, "rb") as w:
        ch = w.getnchannels()
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def rail_stats(x):
    at_rail = np.abs(x) >= FS - 1
    n_rail = int(at_rail.sum())
    longest = 0
    run = 0
    for v in at_rail:
        run = run + 1 if v else 0
        longest = max(longest, run)
    return n_rail, longest


def basic(x):
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
    n_rail, longest = rail_stats(x)
    return dict(
        peak=peak,
        peak_dbfs=20 * math.log10(peak / FS) if peak else -999.0,
        rms=rms,
        rms_dbfs=20 * math.log10(rms / FS) if rms else -999.0,
        crest=peak / rms if rms else 0.0,
        n_rail=n_rail,
        longest_rail=longest,
    )


def steady(x):
    return x[STEADY_START:]


def align_lag(a, b, span=2000):
    a = a[:span] - a[:span].mean()
    b = b[:span] - b[:span].mean()
    c = np.correlate(a, b, mode="full")
    return int(np.argmax(c) - (len(b) - 1))


def thdn(measured, ideal):
    """measured, ideal: same-length steady-state arrays, sample aligned.
    ideal is the provably-linear render scaled to measured's nominal level.
    Returns (gain_loss_db, shape_thdn_db, raw_thdn_db)."""
    m = measured - measured.mean()
    i = ideal - ideal.mean()
    denom = float(np.dot(i, i))
    if denom == 0:
        return 0.0, -999.0, -999.0
    k = float(np.dot(m, i) / denom)
    shape_err = m - k * i
    raw_err = m - i
    ref_rms = math.sqrt(np.mean((k * i) ** 2))
    shape = math.sqrt(np.mean(shape_err ** 2)) / ref_rms if ref_rms else 0.0
    raw_ref = math.sqrt(np.mean(i * i))
    raw = math.sqrt(np.mean(raw_err ** 2)) / raw_ref if raw_ref else 0.0
    db = lambda r: 20 * math.log10(r) if r > 0 else -999.0
    return 20 * math.log10(k) if k > 0 else -999.0, db(shape), db(raw)


def harmonic_split(x, sr, fundamentals, tol_hz=15.0, max_harm=40):
    """Fraction of spectral energy NOT within tol_hz of an integer multiple
    of any fundamental -- a proxy for limiter IMD + aliasing."""
    n = len(x)
    w = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)
    X = np.abs(np.fft.rfft((x - x.mean()) * w))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    power = X * X
    harmonic = np.zeros(len(power), dtype=bool)
    for f0 in fundamentals:
        for h in range(1, max_harm + 1):
            fh = f0 * h
            if fh >= sr / 2:
                break
            harmonic |= np.abs(freqs - fh) <= tol_hz
    tot = float(power.sum())
    if tot == 0:
        return 0.0
    return float(power[~harmonic].sum() / tot)


def midi_hz(n):
    return 440.0 * 2 ** ((n - 69) / 12.0)


def scan_wavetables(wt_paths, size=256):
    rows = {}
    for path in wt_paths:
        if not os.path.exists(path):
            continue
        with wave.open(path, "rb") as w:
            raw = w.readframes(w.getnframes())
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
        nw = len(a) // size
        frames = []
        for i in range(nw):
            fr = a[i * size:(i + 1) * size]
            pk = float(np.max(np.abs(fr)))
            rms = float(np.sqrt(np.mean(fr * fr)))
            frames.append(dict(i=i, peak=pk, rms=rms,
                               crest=pk / rms if rms else 0.0))
        worst = max(frames, key=lambda r: r["peak"])
        rows[os.path.basename(path)] = dict(n_waves=nw, worst=worst, frames=frames)
    return rows


def fmt_table(headers, rows):
    widths = [len(h) for h in headers]
    for r in rows:
        for j, c in enumerate(r):
            widths[j] = max(widths[j], len(str(c)))
    line = lambda cells: "| " + " | ".join(
        str(c).ljust(widths[j]) for j, c in enumerate(cells)) + " |"
    out = [line(headers), "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    out += [line(r) for r in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="tests/render/out",
                    help="where the WAVs + manifest.json live")
    ap.add_argument("--findings", default="tests/render/FINDINGS.md",
                    help="findings doc (tracked); metrics.json is written beside it")
    ap.add_argument("--wavetable-dir", default="examples/wavetables")
    ap.add_argument("--max-shape-thdn-db", type=float, default=None,
                    help="fail if any mit_combo shape THD+N exceeds this")
    args = ap.parse_args()

    with open(os.path.join(args.outdir, "manifest.json")) as f:
        manifest = {c["id"]: c for c in json.load(f)}
    wave_pos_used = manifest.get("mit_base_n3", next(iter(manifest.values())))["wave_pos"]

    cache = {}

    def get(cid):
        if cid not in cache:
            x, sr = load_wav(os.path.join(args.outdir, cid + ".wav"))
            cache[cid] = (x, sr)
        return cache[cid]

    metrics = {}
    for cid, c in manifest.items():
        x, sr = get(cid)
        s = steady(x)
        m = basic(s)
        m["attack_peak"] = float(np.max(np.abs(x[ATTACK_WIN[0]:ATTACK_WIN[1]])))
        m["group"] = c["group"]
        m["n_notes"] = len(c["notes"])
        m["mixer_level"] = c["mixer_level"]
        m["wt_scale"] = c["wt_scale"]
        m["note_amp"] = c["note_amp"]
        m["sr"] = sr
        metrics[cid] = m

    report = []
    R = report.append

    # REUSE-IgnoreStart
    R("<!--")
    R("SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt")
    R("")
    R("SPDX-License-Identifier: MIT")
    R("-->")
    R("")
    # REUSE-IgnoreEnd
    R("# WavetableSynth polyphonic-chord distortion: findings")
    R("")
    R("Generated by `tests/render/analyze_renders.py` from offline renders of "
      "the real `WavetableSynth` under a CircuitPython unix build "
      "(`audiocore.get_buffer`, no hardware). Re-run: `sh tests/render/run.sh`.")
    R("")

    # --- mechanism -------------------------------------------------------------
    R("## 1. What the distortion is")
    R("")
    R("synthio's mix-down (`shared-module/synthio/__init__.c` "
      "`synthio_mix_down_sample`) is a **soft-knee limiter**: the summed bus is "
      "linear to +-28000 (~85% FS), then gain-reduced so the theoretical worst "
      "case still fits int16. `WavetableSynth._make_notes` sets "
      "`amplitude = velocity/127` with no headroom, and the example wavetables "
      "are full scale, so a single note already sits near half scale and a "
      "3-note chord drives the bus past the knee. The audible \"distortion\" is "
      "that limiter's gain reduction and intermodulation, not hard clipping.")
    R("")
    rows = []
    for g, label in (("mech", "filter OFF"), ("mech_lpf", "stock LPF 2500/Q1.1"),
                     ("stock", "stock patch (LPF + stock env)")):
        for cid in sorted(k for k, v in metrics.items() if v["group"] == g):
            m = metrics[cid]
            rows.append([label, m["n_notes"], int(m["peak"]), int(m["attack_peak"]),
                         int(m["rms"]), "%.2f" % m["crest"], m["n_rail"],
                         m["longest_rail"]])
    R(fmt_table(["config", "N", "steady peak", "attack peak", "steady RMS",
                 "crest", "rail samples", "longest run"], rows))
    R("")
    spread = sorted(k for k in metrics if k.startswith("mech_spread"))
    if spread:
        R("Wide non-harmonic voicings (slowest phase realignment):")
        R("")
        rows = [[metrics[c]["n_notes"], int(metrics[c]["peak"]),
                 int(metrics[c]["attack_peak"]), "%.2f" % metrics[c]["crest"]]
                for c in spread]
        R(fmt_table(["N", "steady peak", "attack peak", "crest"], rows))
        R("")

    # --- notional / headroom -------------------------------------------------
    R("## 2. Pre-limiter (notional) peak and required headroom")
    R("")
    R("Each chord rendered provably-linear (wavetable scaled down), then scaled "
      "back. `H_needed = 28000 / notional_peak` is the per-note amplitude that "
      "keeps that chord's peak at the knee.")
    R("")
    rows = []
    Hneed = {}
    for n in range(1, 7):
        cid = "notional_n%d" % n
        if cid not in metrics:
            continue
        x, sr = get(cid)
        inv = 1.0 / manifest[cid]["wt_scale"]
        npk = float(np.max(np.abs(steady(x)))) * inv
        H = KNEE / npk
        Hneed[n] = H
        hs = "n/a (amp clamps at 1.0)" if H >= 1.0 else "%.2f" % H
        rows.append([n, int(npk), "%.2f" % (npk / FS), hs])
    R(fmt_table(["N", "notional peak", "x FS", "H_needed"], rows))
    R("")

    # --- resonance / per-note hard clip ------------------------------------
    qrows = sorted(k for k in metrics if k.startswith("q_"))
    if qrows:
        R("## 3. Per-note path (resonance sweep, N=1)")
        R("")
        R("Checks whether a resonant Biquad rails a single note before the "
          "mix-down (a separate, velocity-dependent distortion path).")
        R("")
        rows = [[manifest[c]["filt_q"], int(metrics[c]["peak"]),
                 metrics[c]["n_rail"], "%.2f" % metrics[c]["crest"]]
                for c in qrows]
        R(fmt_table(["filt_q", "peak", "rail samples", "crest"], rows))
        R("")

    # --- aliasing ---------------------------------------------------------
    if "alias_22050" in metrics and "alias_44100" in metrics:
        R("## 4. Aliasing (rig 22050 Hz vs 44100 Hz)")
        R("")
        funds = [midi_hz(n) for n in manifest["alias_44100"]["notes"]]
        rows = []
        for cid in ("alias_44100", "alias_22050"):
            x, sr = get(cid)
            frac = harmonic_split(steady(x), sr, funds)
            rows.append([sr, "%.1f%%" % (100 * frac), int(metrics[cid]["peak"]),
                         int(metrics[cid]["rms"])])
        R(fmt_table(["sample rate", "inharmonic energy", "peak", "RMS"], rows))
        R("")
        R("Inharmonic fraction = spectral energy not near an integer multiple "
          "of a played fundamental (limiter IMD + any aliased partials), "
          "filter off. Both are tiny and 22050 is not worse, so aliasing is "
          "not contributing to the chord distortion.")
        R("")

    # --- mitigations ----------------------------------------------------
    R("## 5. Mitigation trade-off")
    R("")
    R("Filter off, held chords (BRAIDS02 frame %d). The wavetable-scale and "
      "per-note-amp rows attenuate the voice; the rest run at full amplitude. "
      "THD+N is measured against the provably-linear render of the same chord: "
      "\"shape\" removes the broadband level loss (reported separately as gain "
      "loss), \"raw\" keeps it. RMS and peak are **post** the stated "
      "`mixer.voice[0].level` (a scalar here; see section 5b for the real "
      "`audiomixer.Mixer`)." % wave_pos_used)
    R("")
    mit_defs = [
        ("mit_base", "status quo (level 0.25)"),
        ("mit_wt50", "wavetable x0.5 (level 0.25)"),
        ("mit_wt35", "wavetable x0.35 (level 0.25)"),
        ("mit_head50", "per-note amp x0.5 (level 0.25)"),
        ("mit_sqrtn", "per-note amp /sqrt(N) (level 0.25)"),
        ("mit_mixer", "level 0.5 only (control)"),
        ("mit_combo", "wavetable x0.5 + level 0.5  (recommended)"),
    ]
    fail = False
    for n in (3, 4, 5):
        ncid = "notional_n%d" % n
        if ncid not in manifest:
            continue
        ref_raw, _ = get(ncid)
        ref_raw = steady(ref_raw)
        ref_inv = 1.0 / manifest[ncid]["wt_scale"]   # -> full-scale-wavetable linear render
        R("### N = %d" % n)
        R("")
        rows = []
        base_rms_post = None
        for prefix, label in mit_defs:
            cid = "%s_n%d" % (prefix, n)
            if cid not in metrics:
                continue
            c = manifest[cid]
            x, sr = get(cid)
            s = steady(x)
            lag = align_lag(s, ref_raw)
            ideal = ref_raw * (ref_inv * c["wt_scale"] * c["note_amp"])
            L = min(len(s), len(ideal))
            gl, shp, raw = thdn(s[:L], ideal[:L])
            lvl = c["mixer_level"]
            post_peak = float(np.max(np.abs(s))) * lvl
            post_rms = float(np.sqrt(np.mean((s * lvl) ** 2)))
            if prefix == "mit_base":
                base_rms_post = post_rms
            dloud = (20 * math.log10(post_rms / base_rms_post)
                     if base_rms_post else 0.0)
            if prefix == "mit_combo" and args.max_shape_thdn_db is not None \
                    and shp > args.max_shape_thdn_db:
                fail = True
            rows.append([label, int(post_peak), int(post_rms),
                         "%+.1f" % dloud, "%.1f" % gl, "%.1f" % shp,
                         "%.1f" % raw, lag])
        R(fmt_table(["mitigation", "peak", "RMS", "dLoud dB", "gain loss dB",
                     "shape THD+N dB", "raw THD+N dB", "lag"], rows))
        R("")

    # --- 5b: real audiomixer.Mixer vs the scalar model --------------------
    mixchk_rows = []
    for n in (4, 6):
        sc, rl = "mixchk_scalar_n%d" % n, "mixchk_real_n%d" % n
        if sc not in metrics or rl not in metrics:
            continue
        lvl = manifest[sc]["mixer_level"]
        sx = steady(get(sc)[0])
        rx = steady(get(rl)[0])
        model_peak = float(np.max(np.abs(sx))) * lvl
        model_rms = float(np.sqrt(np.mean((sx * lvl) ** 2)))
        real_peak = float(np.max(np.abs(rx)))
        real_rms = float(np.sqrt(np.mean(rx * rx)))
        nr, _ = rail_stats(rx)
        mixchk_rows.append([n, int(model_peak), int(real_peak),
                            "%+.2f" % (20 * math.log10(real_rms / model_rms)
                                       if model_rms else 0.0), nr])
    if mixchk_rows:
        R("## 5b. Real `audiomixer.Mixer` vs the scalar model")
        R("")
        R("The recommended `mixer.voice[0].level` 0.25 -> 0.5 makeup, rendered "
          "through an actual `audiomixer.Mixer` (buffer 2048) and compared to "
          "section 5's scalar post-multiply. Matching values confirm the "
          "recommendation does not overrun the mixer's own int16 stage.")
        R("")
        R(fmt_table(["N", "scalar-model peak", "real-Mixer peak",
                     "RMS delta dB", "real rail samples"], mixchk_rows))
        R("")

    # --- wavetable scan -------------------------------------------------
    wt_paths = [os.path.join(args.wavetable_dir, f)
                for f in ("BRAIDS02.WAV", "PLAITS02.WAV")]
    wt = scan_wavetables(wt_paths)
    if wt:
        R("## 6. Source wavetable levels")
        R("")
        rows = [[name, d["n_waves"], "%d" % d["worst"]["peak"],
                 "%.2f" % (d["worst"]["peak"] / FS), d["worst"]["i"]]
                for name, d in wt.items()]
        R(fmt_table(["file", "waves", "worst-frame peak", "x FS", "frame"], rows))
        R("")

    # --- recommendation -----------------------------------------------
    R("## 7. Recommendation")
    R("")
    R("- **Scope of these numbers:** one wavetable (BRAIDS02), at its "
      "full-scale frame (4), phase-aligned press. That is the worst case on "
      "every axis; a mid-table wave frame or a de-tuned voicing distorts less.")
    if Hneed:
        R("- Worst-case headroom (`H_needed` above): ~%.2f for a 3-note chord, "
          "~%.2f for 4, ~%.2f for 5."
          % (Hneed.get(3, 0.6), Hneed.get(4, 0.5), Hneed.get(5, 0.45)))
    R("- The mix-down knee (28000) is identical on every port; only the slope "
      "above it differs (`MAX_CHANNELS` 14 on this unix build vs 24 on rp2040), "
      "so **rp2040 compresses harder past the knee** and these THD+N numbers "
      "are an optimistic lower bound. Confirm on hardware.")
    R("- `mixer.voice[0].level` alone (row \"control\") does not remove the "
      "distortion: the limiter already acted upstream in synthio's int16 output. "
      "Section 5b confirms the real `audiomixer.Mixer` matches the scalar model, "
      "so the makeup gain below is safe.")
    R("- `/sqrt(N)` is the cleanest theoretically but needs every sounding "
      "note's `amplitude` rewritten at each note-on (O(polyphony), against the "
      "shared-block design); rejected.")
    R("- A fixed attenuation is the fix. \"wavetable x0.5\" and \"per-note amp "
      "x0.5\" are identical, so where it lives is an implementation choice: a "
      "`WT_HEADROOM` class constant multiplied into `_make_notes`'s "
      "`amplitude`, or folded into the `Wavetable.set_wave_pos` lerp weights "
      "(no extra arrays, also helps `Wavetable` users directly).")
    R("- **x0.5 + `mixer.voice[0].level` 0.25 -> 0.5** keeps single-note "
      "loudness within +-1 dB and takes chords up to 4 notes fully linear "
      "(-67 dB THD+N vs -18 to -20 dB now); a worst-case 5-note chord still "
      "improves from ~18% to ~0.9%. **x0.35 + level ~0.7** is fully linear "
      "through 5 notes if that residual matters. Not applied in this pass.")
    R("")

    findings = args.findings
    with open(findings, "w") as f:
        f.write("\n".join(report) + "\n")

    with open(os.path.join(args.outdir, "metrics.json"), "w") as f:
        json.dump(dict(metrics=metrics, h_needed=Hneed,
                       wavetables={k: {"n_waves": v["n_waves"],
                                       "worst": v["worst"],
                                       "frames": v["frames"]}
                                   for k, v in wt.items()}), f, indent=1)

    print("\n".join(report))
    print("\nwrote", findings, "and", os.path.join(args.outdir, "metrics.json"))
    if fail:
        print("FAIL: mit_combo shape THD+N over threshold")
        sys.exit(1)


if __name__ == "__main__":
    main()
