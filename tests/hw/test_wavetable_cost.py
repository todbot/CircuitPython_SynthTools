# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# What the wavetable-position LFO sweep actually costs on rp2040.
#
# Mostly PROBES, printed rather than asserted: the numbers move with the
# CircuitPython build, the flash and ulab. What they are for is deciding
# whether the sweep (WavetableSynth.update()) is safe to run every loop pass
# under polyphony -- the reference point is DEADLINE_MS below, the audio
# refill window.
#
# The rewrite this measures: Wavetable preloads the whole file at
# construction (WT_PRELOAD, ~32 KB) and caches wave_b - wave_a per wave-pair,
# so a frac-only sweep step is an in-place ulab blend with no file I/O.
#
# Needs synthtools/ and /wavetables/PLAITS02.WAV on the device. Audio is
# brought up (an I2S DAC on the pico_test_synth pins) so update() is timed
# against a real 5-voice render; mute your speakers.
#
#     PORT=$(ls /dev/tty.usbmodem* | head -1)
#     python3 tests/hw/run_on_device.py tests/hw/test_wavetable_cost.py \
#             --port "$PORT" --timeout 120
#
# Runs at TWO audio configs (see AUDIO_CONFIGS): mono / 4096, which
# examples/synth_setup.py selects on rp2040 (~46 ms deadline), and the
# harsher stereo / 2048 that pico_test_synth.Hardware ships and other
# platforms get (~11.6 ms). The difference is the whole story below.
#
# First run, CircuitPython 10.3.0 / rp2040 / Pi Pico @ 200 MHz, PLAITS02.WAV
# (64 waves x 256). Re-measure before trusting:
#
#   * Wavetable(preload=True): build ~12 ms, holds ~35 KB.
#   * set_wave_pos() frac-only ~1.5 ms, on a wave crossing ~3.0 ms.
#   * preload=False adds ~2 ms of file I/O on a crossing (frac-only unchanged).
#
# update() every loop pass, 5-note chord + sweep: worst ~16-18 ms at either
# config. That MISSES the deadline ~9% of passes at stereo / 2048 and NEVER
# at mono / 4096 (which has ~25 ms of margin). The spike is a stop-the-world
# GC pause -- gc.collect() is ~7-8 ms with WavetableSynth's ~30 KB-heavier
# resident heap vs ~2 ms for a bare one-Note wavetable scan, which sweeps the
# same file the same way and never ticks. set_wave_pos()'s ~2 KB/call only
# sets how OFTEN GC fires, not the pause length. See CLAUDE.md "The wavetable
# sweep can tick the audio on rp2040".

import gc
import time

import audiobusio
import audiomixer
import board
import synthio

from synthtools import Patch, WavetableSynth
from synthtools.wavetable import Wavetable

WAV = "/wavetables/PLAITS02.WAV"

# pico_test_synth wiring; change for another board.
i2s_bck_pin, i2s_lck_pin, i2s_dat_pin = board.GP20, board.GP21, board.GP22
SAMPLE_RATE = 22050

# (channels, buffer_bytes). First is what examples/synth_setup.py selects
# on rp2040; second is pico_test_synth.Hardware and every other platform.
AUDIO_CONFIGS = ((1, 4096), (2, 2048))


def deadline_ms(ch, buf):
    return 1000.0 * (buf / 2) / (SAMPLE_RATE * ch * 2)


MS = 1000000.0
fails = []


def ck(cond, msg):
    print(("  ok  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def timeit(n, fn):
    t0 = time.monotonic_ns()
    for i in range(n):
        fn(i)
    return (time.monotonic_ns() - t0) / n / MS


def worst(n, fn):
    m = 0
    for i in range(n):
        t0 = time.monotonic_ns()
        fn(i)
        m = max(m, time.monotonic_ns() - t0)
    return m / MS


print("%d Hz;  configs: %s" % (SAMPLE_RATE, AUDIO_CONFIGS))

# --- 1. construction cost + RAM ---
gc.collect()
free0 = gc.mem_free()
t0 = time.monotonic_ns()
wt = Wavetable(WAV)  # preload=True
build_ms = (time.monotonic_ns() - t0) / MS
gc.collect()
freed = free0 - gc.mem_free()
print("\nWavetable(preload=True): build %.1f ms, holds %d bytes  (num*size*2 = %d)"
      % (build_ms, freed, wt.num_waves * 256 * 2))
ck(wt.w is None, "preload=True closes the file (w is None)")

# --- 2. set_wave_pos cost: frac-only vs wave crossing ---
wt.set_wave_pos(10.5)  # prime the cache at i=10
first = wt.waveform
frac_only = timeit(40, lambda i: wt.set_wave_pos(10.2 + 0.5 * (i % 2)))  # stays in i=10
# force a crossing every call: alternate i=10 and i=20 pairs
crossing = timeit(40, lambda i: wt.set_wave_pos(10.5 if i % 2 else 20.5))
print("\nset_wave_pos()  frac-only  %.2f ms" % frac_only)
print("set_wave_pos()  crossing   %.2f ms" % crossing)
ck(wt.waveform is first, "waveform identity holds across set_wave_pos()")

# int16 range at a high-amplitude zero straddle
wt.set_wave_pos(30.5)
lo = min(int(x) for x in wt.waveform)
hi = max(int(x) for x in wt.waveform)
ck(-32768 <= lo <= hi <= 32767, "buffer in int16 range after a straddle (%d..%d)" % (lo, hi))

# --- 3. preload=False comparison ---
gc.collect()
lazy = Wavetable(WAV, preload=False)
lz_frac = timeit(30, lambda i: lazy.set_wave_pos(10.2 + 0.5 * (i % 2)))
lz_cross = timeit(30, lambda i: lazy.set_wave_pos(10.5 if i % 2 else 20.5))
print("\npreload=False   frac-only  %.2f ms   crossing  %.2f ms  (file I/O adder)"
      % (lz_frac, lz_cross))
same = True
for p in (0.0, 5.25, 12.5, 40.75):
    wt.set_wave_pos(p)
    lazy.set_wave_pos(p)
    same = same and list(wt.waveform) == list(lazy.waveform)
ck(same, "preload=True and preload=False buffers are bit-identical")

# free both standalone tables: WavetableSynth below preloads its own, and a
# 32 KB contiguous read will OOM on a Pico if these are still around
wt = None
lazy = None
gc.collect()

# --- 4. update() under a real 5-voice chord, at each audio config ---
#
# PROBE, not asserted: the worst update() here is a stop-the-world GC pause,
# and whether it misses a refill is a property of the audio config, not a
# regression. gc.collect() below is the number that matters -- it tracks
# resident heap, and WavetableSynth's is ~30 KB over a bare one-Note scan.
def probe_config(ch, buf):
    dl = deadline_ms(ch, buf)
    audio = audiobusio.I2SOut(bit_clock=i2s_bck_pin, word_select=i2s_lck_pin, data=i2s_dat_pin)
    mixer = audiomixer.Mixer(sample_rate=SAMPLE_RATE, channel_count=ch, buffer_size=buf)
    engine = synthio.Synthesizer(sample_rate=SAMPLE_RATE, channel_count=ch)
    audio.play(mixer)
    mixer.voice[0].play(engine)
    mixer.voice[0].level = 0.0  # silent: this is a timing probe

    patch = Patch(name="t", synth_type="wavetable", wave_file=WAV, wave_pos=0,
                  wave_lfo_rate=0.15, wave_lfo_shape="saw", wave_lfo_once=False,
                  amp_env=[0.05, 0.0, 1.0, 0.2])
    syn = WavetableSynth(engine, patch)
    syn.wave_pos_max = syn.num_waves - 1
    for note in (45, 52, 57, 60, 64):
        syn.note_on(note)
    time.sleep(0.2)  # let the render settle

    gc.collect()
    g0 = time.monotonic_ns()
    gc.collect()
    gc_ms = (time.monotonic_ns() - g0) / MS

    t_end = time.monotonic() + 6.0
    mx_ms = 0.0
    over = 0
    n = 0
    while time.monotonic() < t_end:
        t0 = time.monotonic_ns()
        syn.update()
        dt = (time.monotonic_ns() - t0) / MS
        mx_ms = max(mx_ms, dt)
        if dt > dl:
            over += 1
        n += 1
        time.sleep(0.012)
    syn.all_notes_off()
    print("  %d ch / %d B  deadline %.1f ms:  gc.collect %.1f ms,  update worst %.1f ms,"
          "  %d/%d over" % (ch, buf, dl, gc_ms, mx_ms, over, n))

    syn = None
    patch = None
    engine.release_all()
    audio.deinit()
    mixer.deinit()
    gc.collect()


print("\nupdate() every loop pass, held 5-note chord, 6 s window per config:")
for _ch, _buf in AUDIO_CONFIGS:
    probe_config(_ch, _buf)

gc.collect()
print("\nmem_free at end:", gc.mem_free())
if fails:
    print("\n%d FAILURE(S)" % len(fails))
    raise SystemExit(1)
print("\ntest_wavetable_cost: probes printed, assertions passed")
