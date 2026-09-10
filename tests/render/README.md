<!--
SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt

SPDX-License-Identifier: MIT
-->

# Offline render tier

Renders the real synth classes to WAV **without hardware** and measures the
result, so a patch's actual sound can be checked in CI-adjacent conditions.
Built to diagnose `WavetableSynth` distortion on 3+ note chords; see
`FINDINGS.md` for that result.

## How it works

- **Render side** (`render_chords.py`) runs under a CircuitPython *unix* build.
  It builds a real `WavetableSynth` on a real `synthio.Synthesizer`, presses
  chords, and pulls PCM with `audiocore.get_buffer()` in a loop (no real-time,
  no audio device). `get_buffer` is only exposed when the build sets
  `CIRCUITPY_AUDIOCORE_DEBUG=1`, i.e. the `coverage` variant.
- **Analysis side** (`analyze_renders.py`) runs under desktop CPython
  (`numpy` + stdlib `wave`). It computes peak / RMS / crest / clip counts and a
  THD+N proxy against a provably-linear reference render, writes `FINDINGS.md`
  and `metrics.json`.
- `wavhdr.py` is a 44-byte PCM WAV reader/writer (`struct` only) shared by both.

`audiofilewriter` is deliberately **not** used: it is not compiled into the unix
build, and it records via a real-time background pump the unix port does not
run. `audiocore.get_buffer` is the correct offline primitive.

## Running

```sh
sh tests/render/run.sh
```

Needs two things it locates by convention, both overridable:

| | env var | default |
|---|---|---|
| CircuitPython unix binary (`coverage` variant) | `MICROPYTHON` (or `--mp <path>`) | `~/projects/adafruit/circuitpython-claudetest/ports/unix/build-coverage/micropython` |
| directory holding `adafruit_wave.py` (pure Python) | `ADAFRUIT_WAVE_DIR` | `~/projects/adafruit/circuitpython-claudetest/frozen/Adafruit_CircuitPython_Wave` |

`adafruit_wave` is put on `sys.path` from that directory rather than vendored:
the frozen copy is PSF-2.0 and `reuse lint` has no matching `LICENSES/` file.
Nothing is added to `tests/stubs/`, so `tests/test_wiring.py`'s
"graceful degradation when `adafruit_wave` is absent" checks are unaffected.

```sh
# one case / one group, into a scratch dir
"$MICROPYTHON" tests/render/render_chords.py --wave-lib "$ADAFRUIT_WAVE_DIR" \
    --only mit --outdir /tmp/r
python3 tests/render/analyze_renders.py --outdir /tmp/r --findings /tmp/r/FINDINGS.md
```

## Outputs

- `tests/render/FINDINGS.md` - tracked.
- `tests/render/out/*.wav`, `out/manifest.json`, `out/metrics.json` -
  regenerable, gitignored.

## Caveats

- The unix `coverage` build has `CIRCUITPY_SYNTHIO_MAX_CHANNELS = 14`; rp2040
  has 24. synthio's mix-down knee (`+-28000`) is identical, but the compression
  slope above it is steeper on rp2040, so THD+N figures here are an optimistic
  lower bound. Confirm conclusions on a board.
- The synthio stub used by the other test tiers has no DSP; only this tier and
  real hardware can measure sound.
- `out/` is gitignored. If it exists locally, `pre-commit run --all-files` will
  flag the generated WAVs for missing SPDX headers &mdash; harmless, and CI (a
  clean checkout) never sees them. `rm -rf tests/render/out` to silence it.
