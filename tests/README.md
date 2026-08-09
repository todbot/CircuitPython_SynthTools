# synthlib tests

Plain scripts, no pytest. They exit non-zero on failure so they work under a
bare MicroPython as well as CPython — which matters, because this library
targets CircuitPython and adding a desktop-only test dependency would defeat
the point.

```sh
sh tests/run_tests.sh          # everything, under every interpreter found
python3 tests/test_wiring.py   # or run one directly
micropython tests/test_wiring.py
```

`tests/` is excluded from pre-commit (`exclude: 'docs/.*|tests/.*'` in
`.pre-commit-config.yaml`), so these files are exempt from ruff **and** from
the `reuse` hook — no SPDX headers needed here.

## Three tiers, and what each one actually proves

| | interpreter | ulab backend | catches |
|---|---|---|---|
| numeric | CPython | real numpy | DSP/array behaviour, int16 range |
| portability | MicroPython | pure-Python fallback | the CPython-isms in §7 |
| hardware | CircuitPython on device | real ulab | what synthio actually permits |

The split is from `CLAUDE-synthlib.md` §9. Real numpy is the only thing that
answers numeric questions honestly (it is how the int16 lerp overflow in §8
was pinned down). MicroPython is the only thing that catches the import and
`__dict__` bugs that CPython silently permits.

Both tiers currently produce **identical** envelope values, which is the main
evidence that the pure-Python fallback is faithful.

## Files

- `test_patch.py` — patch round-trip. Needs no stubs at all (`patch.py` imports
  only `json`), so it is the cheapest §7 canary: read-only instance `__dict__`,
  `dict.update` keywords, `amp_env` being a list rather than a tuple.
- `test_env_shapes.py` — the AHR envelope shape from `synthlib/waves.py`.
  Calls the **real** `fill_env_rise`, not a copy of it. There is one buffer and
  it holds nothing but a rise: the *hold* is what `once=True` already does after
  the last sample, and the *release* re-runs the same rising curve through a
  `CONSTRAINED_LERP` with swapped endpoints.
  Checks int16 range, endpoints, monotonicity, that `curve=1` stays
  bit-identical to a plain linear ramp, and — the regression guard for the
  retired hold segment — that a linear rise is *strictly* increasing, so a flat
  run anywhere means a plateau has crept back in.
- `test_wiring.py` — `Synth` against the synthio stubs: the cutoff modulation
  bus, block identity and sharing, in-place buffer rewrites, that global params
  stay one write *and stay live for sounding voices*, the release path, the
  clamp, and the `set_param` whitelist. Also that **the patch is not live
  state** — a knob turn must not reach it, `amp_env` must be copied rather than
  aliased in both directions, and `save_patch()` must commit everything
  including subclass params.
- `stubs/synthio.py` — no DSP. `Math`/`LFO` resolve nested blocks so `.value`
  is meaningful, which is what makes block-graph assertions possible. It
  implements only the five `MathOperation`s synthlib uses, with the arithmetic
  copied from the real synthio docs, and **raises on any other operation** —
  so reaching for a new op means adding it here first.
- `stubs/ulab/numpy.py` — real numpy under CPython; a small wrapper class
  under MicroPython. Not a `list` subclass: MicroPython's `list.__setitem__`
  rejects a non-list right-hand side, so slice assignment from another array
  would fail.

## Known coverage gap

**`WavetableSynth` is not tested on either tier.** There is no `adafruit_wave`
stub, so `synthlib/__init__.py`'s `try/except ImportError` swallows the import
and `WavetableSynth` is never even exported. `test_wiring.py` asserts that
graceful degradation explicitly — so the gap is visible rather than silent —
but covering the class itself needs an `adafruit_wave` stub plus a small WAV
fixture. `Wavetable.set_wave_pos`'s int16 lerp (§8) is the part that would
most repay it.

## The hardware tier

```sh
mkdir -p /Volumes/CIRCUITPY/synthlib
cp synthlib/*.py /Volumes/CIRCUITPY/synthlib/
cp examples/synth_setup.py /Volumes/CIRCUITPY/
dot_clean -m /Volumes/CIRCUITPY/          # see below
python3 tests/hw/run_on_device.py tests/hw/test_device.py \
        --port /dev/tty.usbmodem21301 --timeout 180
```

**The `dot_clean` is not optional housekeeping.** Recent macOS tags files with a
`com.apple.provenance` xattr, and FAT cannot store xattrs, so the copy leaves a
4 KB `._modulename.py` AppleDouble beside every module — ~32 KB of litter per
sync on a 1 MB flash. Neither `cp -X` nor `COPYFILE_DISABLE=1` prevents it
(`COPYFILE_DISABLE` only affects `tar`); `dot_clean -m` afterwards is what
actually works.

`run_on_device.py` drives a board over the serial REPL with `pyserial`, using the
raw REPL so the board's own `code.py` is only interrupted, never modified on
disk. It takes `--port` (default `/dev/tty.usbmodem11201` — **check
`ls /dev/tty.usbmodem*`, the number changes between boards and ports**) and
`--reboot`.

`test_device.py` needs `synthlib/` and `synth_setup.py` on the device, and it
mutes the mixer while it runs — it is checking the block graph, not listening.
180 s is not generous: the test sleeps its way through real envelope times.

Anything that only needs `synthio` — the arithmetic and behaviour probes below —
can be run as a standalone snippet through `run_on_device.py` with **no files
copied to the drive at all**. Prefer that when the question is about synthio
rather than about synthlib.

**This tier is not optional for synthio work.** It is the only thing that catches
what the C API actually permits. It has already found that `synthio.LFO.waveform`
is read-only, which made an earlier envelope design raise `AttributeError` at
every note-off — something both other tiers passed happily, because the stubs let
you assign anything.

It also carries **probes** — printed rather than asserted — for questions only a
board can answer. Measured on CircuitPython 10.3.0-alpha.3 / rp2040:

| probe | answer |
|---|---|
| negative `Biquad.frequency` | accepted, no exception, no crash — so the `MID` clamp is **defensive, not mandatory** |
| depth-4 block chain | one write lands at the deepest node within a single update; it does *not* propagate one level per update |
| `once=True` LFO after its last sample | holds forever (0.9999 at both 0.5 s and 1.5 s on a 0.2 s rise) — this is what made `fenv_hold` unreachable |
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
assignments real synthio rejects — that is exactly how the read-only
`LFO.waveform` slipped through. Treat them as checks on *synthlib's* logic, not
on synthio's contract; use the hardware tier for the latter.

Nothing here can tell you how it **sounds**. Glitches, clicks and zipper noise
need a listener: run the hardware tier with the mixer up, or play the board.

One known backend difference: real numpy silently wraps an out-of-range int16
store, while ulab raises `OverflowError`. The pure fallback raises, matching
ulab. Tests assert ranges explicitly rather than relying on either.
