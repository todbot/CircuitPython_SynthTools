# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# What a displayio UI actually costs on a small mono OLED.
#
# Mostly PROBES, printed rather than asserted: the numbers move with the
# CircuitPython build, the bus speed and the panel, so pinning them would
# only produce a test that fails on the next alpha. What they are for is
# sizing a UI before writing it. The reference point is the audio deadline
# in the header below: anything a UI does on the same loop pass as the
# mixer refill has to fit inside it, and most of what follows does not.
#
# Needs synthtools/ on the device. No audio: this measures the display
# alone, so nothing here can be masked by, or blamed on, the synth.
#
#     PORT=$(ls /dev/tty.usbmodem* | head -1)
#     python3 tests/hw/run_on_device.py tests/hw/test_display_cost.py \
#             --port "$PORT" --timeout 120
#
# Findings from a first run on CircuitPython 10.3.0-alpha.3 / rp2040 at
# 200 MHz, SSD1306 128x64 on I2C at 1 MHz. Re-measure before trusting the
# numbers; they are here for the SHAPE of the costs:
#
#   * A refresh costs roughly 0.6 ms per dirty area plus 0.03 ms per byte
#     sent, a byte being one 8-row page column: a dirty rect costs its
#     width times its height rounded up to a page boundary. For anything
#     text-sized the per-byte term dominates, so the lever is keeping
#     elements NARROW, not keeping them few.
#   * A full 128x64 frame is 1024 bytes and ~31 ms, not the ~9.5 ms some
#     comments in these projects quote. Nothing that repaints the whole
#     screen fits inside an 11.6 ms audio deadline.
#   * A text label is dear because it is WIDE. An 8-char terminalio label
#     is a 48x16 box, ~96 bytes, ~5 ms. A 6px gauge is 18 bytes and under
#     1 ms, which is why all twelve gauges of a GaugeCluster repaint in
#     less time than a single row of text.
#   * bitmap_label assigns text in ~4.2 ms against label's ~2.5, but label
#     is a TileGrid that dirties one area per changed GLYPH and costs MORE
#     RAM (1398 bytes against 1124). It loses on both counts here.
#   * String formatting is ~0.05 ms and vectorio geometry ~0.04 ms. Both
#     are free beside a label write; blaming "%" for a slow UI is wrong.
#   * Reassigning display.root_group does NOT mark the screen dirty, so a
#     scattered redraw cannot be collapsed into one full-frame blit.

import gc
import time

import adafruit_displayio_ssd1306
import board
import busio
import displayio
import i2cdisplaybus
import terminalio
import vectorio
from adafruit_display_text import bitmap_label, label

from synthtools import GaugeCluster

# pico_test_synth wiring; change these for another board.
i2c_scl_pin = board.GP19
i2c_sda_pin = board.GP18
DW, DH = 128, 64
I2C_HZ = 1_000_000

# audiomixer splits its buffer in two and one half plays while the other
# refills, so half the buffer is the deadline a main loop has to hit.
SAMPLE_RATE, CHANNELS, BUFFER_BYTES = 22050, 2, 2048
DEADLINE_MS = 1000.0 * (BUFFER_BYTES / 2) / (SAMPLE_RATE * CHANNELS * 2)

MS = 1000000.0
N = 20
fails = []


def ck(cond, msg):
    print(("  ok  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def timeit(n, fn):
    """Mean ms per call of fn(i)."""
    t0 = time.monotonic_ns()
    for i in range(n):
        fn(i)
    return (time.monotonic_ns() - t0) / n / MS


def split(prep, n=N):
    """Mean ms of prep(i) and of the refresh it makes necessary, apart.

    Apart because they are spent differently: prep is CPU in the VM and can
    be moved to another loop pass, refresh is I2C and cannot be interrupted.
    """
    tp = tr = pmax = rmax = 0
    for i in range(n):
        t0 = time.monotonic_ns()
        prep(i)
        t1 = time.monotonic_ns()
        display.refresh()
        t2 = time.monotonic_ns()
        tp += t1 - t0
        tr += t2 - t1
        pmax = max(pmax, t1 - t0)
        rmax = max(rmax, t2 - t1)
        time.sleep(0.03)
    return tp / n / MS, tr / n / MS, pmax / MS, rmax / MS


def row(name, prep, n=N):
    p, r, pm, rm = split(prep, n)
    print(
        "  %-22s prep %6.2f (max %6.2f)   refresh %6.2f (max %6.2f)   total %6.2f"
        % (name, p, pm, r, rm, p + r)
    )
    return p + r


displayio.release_displays()
i2c = busio.I2C(scl=i2c_scl_pin, sda=i2c_sda_pin, frequency=I2C_HZ)
display = adafruit_displayio_ssd1306.SSD1306(
    i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C),
    width=DW,
    height=DH,
    rotation=180,
    auto_refresh=False,
)
grp = displayio.Group()
display.root_group = grp
display.refresh()

print("audio deadline for reference: %.1f ms per pass" % DEADLINE_MS)

print()
print("--- 1  the primitives, one element changing ----------------------")
white = displayio.Palette(1)
white[0] = 0xFFFFFF
bl = bitmap_label.Label(terminalio.FONT, text=" " * 5, color=0xFFFFFF, x=2, y=5)
tl = label.Label(terminalio.FONT, text=" " * 5, color=0xFFFFFF, x=2, y=17)
rect = vectorio.Rectangle(pixel_shader=white, width=10, height=5, x=2, y=26)
for o in (bl, tl, rect):
    grp.append(o)
display.refresh()

print("  string format          %6.3f ms" % timeit(200, lambda i: "%5d" % (1000 + i)))
print(
    "  rect.width =           %6.3f ms" % timeit(200, lambda i: setattr(rect, "width", 10 + i % 2))
)
row("bitmap_label .text=", lambda i: setattr(bl, "text", "%5d" % (1000 + i % 2)))
row("label .text=", lambda i: setattr(tl, "text", "%5d" % (1000 + i % 2)))
row("rect.width + refresh", lambda i: setattr(rect, "width", 10 + i % 2))

print()
print("--- 2  refresh cost vs the NUMBER of dirty areas ----------------")
# The claim under test: eight small labels cost far more than one label
# eight times the size, because each is its own I2C addressing burst.
labs = []
for r in range(8):
    lb = bitmap_label.Label(terminalio.FONT, text=" " * 8, color=0xFFFFFF, x=64, y=5 + r * 7)
    labs.append(lb)
    grp.append(lb)
display.refresh()
time.sleep(0.2)
per_area = []
for k in (1, 2, 4, 8):

    def dirty(i, k=k):
        for r in range(k):
            labs[r].text = "%-8d" % (r * 10 + i % 2)

    p, r, _, _ = split(dirty, 10)
    per_area.append(r / k)
    print(
        "  %d label(s) dirty:      prep %6.2f   refresh %6.2f   (%5.2f ms per area)"
        % (k, p, r, r / k)
    )
ck(
    per_area[3] > 0.7 * per_area[0],
    "N areas cost ~N times one; nothing is amortised across them "
    "(8 areas cost %.2f ms each vs %.2f for 1)" % (per_area[3], per_area[0]),
)

print()
print("--- 2b  ...and with the SIZE of one area ------------------------")
# Separates the two costs section 2 cannot tell apart. One vectorio
# rectangle, one dirty area throughout, only its size changing. Fitting a
# line through these gives the per-area overhead (the intercept) and the
# per-byte rate (the slope), which is what decides whether a UI should aim
# for fewer elements or smaller ones.
band = vectorio.Rectangle(pixel_shader=white, width=8, height=8, x=0, y=0)
grp.append(band)
display.refresh()
time.sleep(0.2)
sizes = []
for w, h in ((8, 8), (32, 8), (64, 8), (128, 8), (128, 24), (128, 64)):
    band.height = h

    def grow(i, w=w):
        band.width = w - (i % 2)

    _, r, _, _ = split(grow, 10)
    # the panel is paged in 8-row bands, so a dirty rect costs its width
    # times its height rounded up to a multiple of 8
    nbytes = w * ((h + 7) // 8)
    sizes.append((nbytes, r))
    print(
        "  %3dx%-3d = %4d bytes:    refresh %6.2f ms   (%6.4f ms/byte)"
        % (w, h, nbytes, r, r / nbytes)
    )
grp.remove(band)
(b0, t0_), (b1, t1_) = sizes[0], sizes[-1]
slope = (t1_ - t0_) / (b1 - b0)
print("  => %.4f ms per byte, %.2f ms fixed per area" % (slope, t0_ - slope * b0))
print("  a full 128x64 frame is %d bytes, measured %.2f ms" % (sizes[-1][0], sizes[-1][1]))

print()
print("--- 3  can a scattered redraw be collapsed into one full frame? --")


# If it could, a UI that changes many elements at once would repaint the
# whole screen for the price of one area instead of N. It cannot.
def dirty8(i):
    for r in range(8):
        labs[r].text = "%-8d" % (r * 20 + i % 2)


_, r_scattered, _, _ = split(dirty8, 10)


def dirty8_then_reassign(i):
    dirty8(i)
    display.root_group = grp


_, r_reassigned, _, _ = split(dirty8_then_reassign, 10)
print("  8 areas, plain:        refresh %6.2f ms" % r_scattered)
print("  8 areas, root_group=:  refresh %6.2f ms" % r_reassigned)
bare = timeit(10, lambda i: (setattr(display, "root_group", grp), display.refresh()))
print("  root_group= alone:     %6.2f ms  (a real full frame is ~31, see 2b)" % bare)
ck(bare < 2.0, "reassigning root_group does not dirty anything (%.2f ms)" % bare)

print()
print("--- 4  does refresh() ever decline back-to-back? -----------------")
# It matters to anyone who clears a dirty flag after calling it: with
# target_frames_per_second defaulting to None there is no rate limit, so
# the return is always True and the flag is safe to clear. If that default
# ever changes, a UI that ignores the return silently drops repaints.
declined = 0
for i in range(60):
    bl.text = "%5d" % i
    if not display.refresh():
        declined += 1
print("  60 refreshes, no delay between: declined %d" % declined)
ck(declined == 0, "refresh() is not rate-limited by default (declined %d/60)" % declined)

print()
print("--- 5  RAM per label ---------------------------------------------")
for name, cls in (("bitmap_label", bitmap_label.Label), ("label", label.Label)):
    gc.collect()
    m0 = gc.mem_free()
    keep = [cls(terminalio.FONT, text=" " * 8, color=0xFFFFFF) for _ in range(10)]
    gc.collect()
    print("  %-14s %5d bytes each" % (name, (m0 - gc.mem_free()) // 10))
    del keep
gc.collect()

print()
print("--- 6  GaugeCluster, synthtools' own all-params display ----------")
for o in list(grp):
    grp.remove(o)
NG = 12
gauges = GaugeCluster(NG, x=1, y=45, width=6, height=18, xstride=2.625)
grp.append(gauges.gauges)
grp.append(gauges.select_lines)
for i in range(NG):
    gauges.set_gauge_val(i, 20 * i)
display.refresh()
time.sleep(0.2)

print(
    "  set_gauge_val alone    %6.3f ms"
    % timeit(200, lambda i: gauges.set_gauge_val(0, 100 + i % 2))
)
row("1 gauge + refresh", lambda i: gauges.set_gauge_val(0, 100 + i % 2))
row("2 gauges + refresh", lambda i: [gauges.set_gauge_val(g, 100 + i % 2) for g in (0, 1)])


def all_gauges(i):
    for g in range(NG):
        gauges.set_gauge_val(g, (g * 20 + i * 7) % 256)


row("all %d + refresh" % NG, all_gauges, 10)


def move_select(i):
    gauges.select_line(i % (NG // 2), False)
    gauges.select_line((i + 1) % (NG // 2), True)


row("select_line move", move_select)

# The documented contract: v is 0-255 and drives the inner rect's height.
inner = gauges.gauges[1]
gauges.set_gauge_val(0, 0)
empty_h = inner.height
gauges.set_gauge_val(0, 255)
full_h = inner.height
ck(full_h < empty_h, "255 shrinks the mask more than 0 does (%d < %d)" % (full_h, empty_h))
ck(gauges.get_gauge_val(0) == 255, "get_gauge_val round-trips")
gauges.select_line(0, False)
ck(gauges.select_lines[0].hidden, "select_line(i, False) hides it")
gauges.select_line(0, True)
ck(not gauges.select_lines[0].hidden, "select_line(i, True) shows it")

print()
print("FAILURES: %d" % len(fails))
for f in fails:
    print("  -", f)
print("DONE")
