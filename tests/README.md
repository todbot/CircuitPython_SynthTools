<!--
SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt

SPDX-License-Identifier: MIT
-->

# synthtools tests

Plain scripts, no pytest. They exit non-zero on failure so they work under a
bare MicroPython as well as CPython, even though this library is CircuitPython.
Some tests require actual CircuitPython hardware.

```sh
sh tests/run_tests.sh          # everything, under every interpreter found
python3 tests/test_wiring.py   # or run one directly
micropython tests/test_wiring.py
```

`tests/` is excluded from pre-commit's `exclude: 'docs/.*|tests/.*'`, so these
files are exempt from ruff. The `reuse` hook has `pass_filenames: false` and
lints the whole tree regardless, so **every file here still needs an SPDX
header**.

## Four ways to test

| | interpreter | ulab backend | catches |
|---|---|---|---|
| numeric | CPython | real numpy | DSP/array behaviour, int16 range |
| portability | MicroPython | pure-Python fallback | CPython-isms |
| hardware | CircuitPython on device | real ulab | what synthio actually permits |
| render | CircuitPython unix build + CPython | real ulab / real numpy | how a patch actually *sounds* (offline WAV) |

The render tier is `tests/render/` (`sh tests/render/run.sh`): it renders the
real synth classes to WAV with `audiocore.get_buffer` and measures peak / RMS /
THD+N. It needs a `coverage`-variant unix build and is not run by CI. See
`tests/render/README.md`.

MicroPython is the only thing that catches the import and
`__dict__` bugs that CPython silently permits.

Both tiers currently produce **identical** envelope values, which is the main
evidence that the pure-Python fallback is faithful.

## Files

- `test_patch.py` — patch round-trip. Needs no stubs at all (`patch.py` imports
  only `json`), so it is the cheapest §7 canary: read-only instance `__dict__`,
  `dict.update` keywords, `amp_env` being a list rather than a tuple.
- `test_env_shapes.py` — the AHR envelope shape from `synthtools/waves.py`.
  Calls the **real** `fill_env_rise`, not a copy of it. There is one buffer and
  it holds nothing but a rise: the *hold* is what `once=True` already does after
  the last sample, and the *release* re-runs the same rising curve through a
  `CONSTRAINED_LERP` with swapped endpoints.
  Checks int16 range, endpoints, monotonicity, that `curve=1` stays
  bit-identical to a plain linear ramp, that a linear rise is *strictly*
  increasing (the regression guard for the retired hold segment: a flat run
  means a plateau has crept back in), and that the release the shape implies is
  a real decay rather than a mirrored attack.
- `plot_env.py` — **not a test**: ASCII-plots the envelope over time for
  curves 1/2/3, attack and release, including a released-mid-rise case. It reads
  the real shared buffer and applies the real block arithmetic, so it cannot
  drift from what the synth plays. Run it when reasoning about envelope shape;
  it is how the mirrored-attack release below was found.
- `test_wiring.py` — `Synth` against the synthio stubs: the cutoff modulation
  bus, block identity and sharing, in-place buffer rewrites, that global params
  stay one write *and stay live for sounding voices*, the release path, the
  clamp, and the `set_param` whitelist. Also that **the patch is not live
  state**: a knob turn must not reach it, `amp_env` must be copied rather than
  aliased in both directions, and `save_patch()` must commit everything
  including subclass params.
- `test_fm_synth.py` — `FMSynth` against the synthio stubs: FM here is a baked
  phase-modulation CARRIER TABLE, not a live modulator on `note.bend` (synthio's
  Math/LFO blocks only update every 256 samples, far too slow to render real FM
  sidebands; see `fm_synth.py`'s module docstring). Checks that the table is
  ONE shared buffer every FM-on voice's waveform points at, that `fm_ratio`/
  `fm_index` rewrite it in place and reach voices already sounding, that
  `fm_ratio` always rounds to a non-negative integer, and that `fm_index` 0
  falls back to the plain `wave` oscillator at ordinary `Synth` cost. Plus the
  `fm_*` patch fields round-trip and stay out of the live patch until saved.
- `stubs/synthio.py` — no DSP. `Math`/`LFO` resolve nested blocks so `.value`
  is meaningful, which is what makes block-graph assertions possible. It
  implements only the five `MathOperation`s synthtools' engine uses, with the arithmetic
  copied from the real synthio docs, and **raises on any other operation**,
  so reaching for a new op means adding it here first.
- `stubs/ulab/numpy.py` — real numpy under CPython; a small wrapper class
  under MicroPython. Not a `list` subclass: MicroPython's `list.__setitem__`
  rejects a non-list right-hand side, so slice assignment from another array
  would fail.

## Test gotchas

- **Never test the release only at `fenv_curve = 1`.** At curve 1 the correct
release shape and a mirrored-attack one are algebraically identical (`1-t == 1-t`),
so the test proves nothing about curvature. A release that hung at the top and
then fell off a cliff at curve>=2 once passed all three tiers for exactly this
reason: both `test_wiring.py` and `tests/hw/test_device.py` set the curve to 2,
checked the *buffer contents*, then reset it to 1 **before** their release
sections. Both now release at curve=2 deliberately, and assert the envelope is
past half its height by halfway through the release.

## Known coverage gap

**`WavetableSynth` is not tested on either tier.** There is no `adafruit_wave`
stub, so `synthtools/__init__.py`'s `try/except ImportError` swallows the
`wavetable.py`/`wavetable_synth.py` imports and neither `Wavetable` nor
`WavetableSynth` is ever even exported. `test_wiring.py` asserts that
graceful degradation explicitly (so the gap is visible rather than silent)
but covering the class itself needs an `adafruit_wave` stub plus a small WAV
fixture. `Wavetable.set_wave_pos`'s int16 lerp (§8) is the part that would
most repay it.

## The hardware tier

This tier needs a board physically plugged in, and it **writes to the CIRCUITPY
drive**. Neither is a given: the board is often unplugged, and its serial port
moves between sessions; it has come up as both `usbmodem11201` and
`usbmodem21301`. Discover the port, never hardcode it:

```sh
ls /dev/tty.usbmodem*                     # whatever it is today
PORT=$(ls /dev/tty.usbmodem* | head -1)

mkdir -p /Volumes/CIRCUITPY/synthtools
cp synthtools/*.py /Volumes/CIRCUITPY/synthtools/
cp examples/synth_setup.py /Volumes/CIRCUITPY/
dot_clean -m /Volumes/CIRCUITPY/          # see below
python3 tests/hw/run_on_device.py tests/hw/test_device.py \
        --port "$PORT" --timeout 180
```

**The `dot_clean` is not optional housekeeping.** Recent macOS tags files with a
`com.apple.provenance` xattr, and FAT cannot store xattrs, so the copy leaves a
4 KB `._modulename.py` AppleDouble beside every module; ~32 KB of litter per
sync on a 1 MB flash. Neither `cp -X` nor `COPYFILE_DISABLE=1` prevents it
(`COPYFILE_DISABLE` only affects `tar`); `dot_clean -m` afterwards is what
actually works.

`run_on_device.py` drives a board over the serial REPL with `pyserial`, using the
raw REPL so the board's own `code.py` is only interrupted, never modified on
disk. It takes `--port` and `--reboot`. **Its default port,
`/dev/tty.usbmodem11201`, is a guess and is regularly wrong**: pass `--port`
explicitly.

`test_device.py` needs `synthtools/` and `synth_setup.py` on the device, and it
mutes the mixer while it runs: it is checking the block graph, not listening.
180 s is not generous: the test sleeps its way through real envelope times.

`test_display_cost.py` is the second file in this tier and answers a different
question: what a displayio UI costs on a small mono OLED. It needs `synthtools/`
but not `synth_setup.py`, and runs no audio at all, so nothing it measures can
be masked by or blamed on the synth. Its I2C pins are declared at the top for
the pico_test_synth wiring; change them for another board. It is mostly probes,
because the numbers move with the build, the bus speed and the panel. The
shapes it exists to establish, measured on 10.3.0-alpha.3 / rp2040 at 200 MHz
with the panel on I2C at 1 MHz:

| probe | answer |
|---|---|
| what does refresh cost scale with? | dirty **bytes**, ~0.03 ms each, plus ~0.6 ms fixed per area. A dirty rect's bytes are its width times its height rounded up to the panel's 8-row pages |
| how long is a full 128x64 frame? | **~31 ms**, not the ~9.5 ms quoted in older comments here and in pico_test_synth. No full repaint fits an 11.6 ms audio deadline |
| `bitmap_label` vs `adafruit_display_text.label` | label assigns text faster (2.5 ms against 4.2) but is a TileGrid that dirties one area per changed **glyph** and costs *more* RAM (1398 bytes against 1124). It loses on both counts |
| can scattered changes be collapsed into one full frame? | no; reassigning `display.root_group` does not mark anything dirty |
| does `refresh()` decline back-to-back? | no, `target_frames_per_second` defaults to `None` and there is no rate limit, so a UI may clear a dirty flag on the strength of it |

The consequence for anyone laying out a UI is that **width is the lever, not
element count**. An 8-character `terminalio` label is a 48x16 box, ~96 bytes,
~5 ms; a 6-pixel-wide gauge is 18 bytes and under 1 ms. That is why the whole
12-gauge `GaugeCluster` repaints in 6.8 ms, less than a single row of text, and
it is the measurement behind the old rule of thumb that no element should be
wider than half the screen. String formatting (~0.05 ms) and vectorio geometry
(~0.04 ms) are free beside a single label write.

`GaugeCluster` is the only display code `synthtools` itself ships, and section 6
is the only coverage it has.

Anything that only needs `synthio` (the arithmetic and behaviour probes below)
can be run as a standalone snippet through `run_on_device.py` with **no files
copied to the drive at all**. Prefer that when the question is about synthio
rather than about the engine in `synthtools/`.

**This tier is not optional for synthio work.** It is the only thing that catches
what the C API actually permits. It has already found that `synthio.LFO.waveform`
is read-only, which made an earlier envelope design raise `AttributeError` at
every note-off: something both other tiers passed happily, because the stubs let
you assign anything.

It also carries **probes** (printed rather than asserted) for questions only a
board can answer. Measured on CircuitPython 10.3.0-alpha.3 / rp2040:

| probe | answer |
|---|---|
| negative `Biquad.frequency` | accepted, no exception, no crash, so the `MID` clamp is **defensive, not mandatory** |
| depth-4 block chain | one write lands at the deepest node within a single update; it does *not* propagate one level per update |
| `once=True` LFO after its last sample | holds forever (0.9999 at both 0.5 s and 1.5 s on a 0.2 s rise); this is what made `fenv_hold` unreachable |
| `Math` with `c` defaulted | `c` defaults to **1.0**, so `Math(SUM, 3, 5).value == 9.0`, not 8.0 |
| `LFO.waveform = arr` | `AttributeError`; mutating the buffer in place is fine |

Two traps it pins down: the filter envelope only ticks while its Note is alive,
so a `fenv_release` longer than the amp envelope's release gets silently
truncated (give `amp_env` a long release when timing a filter release); and the
release *duration* test is what would catch a wrongly scaled `_rate_r`, which is
exactly what the retired hold segment used to require (0.48 s measured against a
0.50 s setting).

## What these cannot tell you

The CPython and MicroPython tiers render no audio, and the stubs accept
assignments real synthio rejects: that is exactly how the read-only
`LFO.waveform` slipped through. Treat them as checks on the *engine's* logic,
not on synthio's contract; use the hardware tier for the latter.

Nothing here can tell you how it **sounds**. Glitches, clicks and zipper noise
need a listener: run the hardware tier with the mixer up, or play the board.

One known backend difference: real numpy silently wraps an out-of-range int16
store, while ulab raises `OverflowError`. The pure fallback raises, matching
ulab. Tests assert ranges explicitly rather than relying on either.
