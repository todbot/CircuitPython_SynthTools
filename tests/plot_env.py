"""ASCII-plot the AHR filter envelope over time, straight from the real buffer.

    python3 tests/plot_env.py
    python3 tests/plot_env.py 2            # just curve=2
    micropython tests/plot_env.py

Not a test -- a look at what the envelope actually does. It calls the REAL
synthlib.waves.fill_env_rise and evaluates the REAL block arithmetic that
AHREnvelope.make() / start_release() set up, so it cannot drift away from
what the synth plays:

    attack    env = depth * s(t)                LERP(0, depth, pos)
    release   env = V * (1 - s(t))              LERP(V, 0, pos), V = value at note-off

`s` is the shared shape buffer, sampled the way synthio samples an LFO
waveform. The release re-runs that SAME rising buffer forward -- it does not
play it backwards, and it is not a second, independently shaped curve. That
is why the buffer holds 1-(1-t)^curve rather than the more obvious t^curve:
it is the release that decides, since `V * (1 - s(t))` inverts whatever
shape s has. See synthlib/waves.py.
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/stubs")
sys.path.insert(0, _D + "/..")

from synthlib.waves import ENV_PEAK, env_buffer, fill_env_rise  # noqa: E402

WIDTH = 62          # columns for the whole attack+release timeline
HEIGHT = 15


def sample(buf, phase):
    """Read the shape at 0..1 the way synthio reads an LFO waveform."""
    if phase <= 0.0:
        return 0.0
    if phase >= 1.0:
        phase = 1.0
    return buf[int(phase * (len(buf) - 1))] / float(ENV_PEAK)


def trajectory(buf, attack_s, release_s, release_at, steps):
    """(time, value) pairs across attack then release, value in 0..1.

    `release_at` is the fraction of the attack completed when the key is
    lifted: 1.0 is a full attack, 0.4 releases mid-rise.
    """
    held = attack_s * release_at
    total = held + release_s
    pts = []
    v_at_release = sample(buf, release_at)      # what LERP(0, 1, pos) reads
    for i in range(steps):
        t = total * i / (steps - 1)
        if t < held:
            v = sample(buf, t / attack_s)       # env = depth * s(t)
        else:
            tau = (t - held) / release_s
            v = v_at_release * (1.0 - sample(buf, tau))   # env = V * (1 - s(t))
        pts.append((t, v))
    return pts, held, total


def plot(pts, held, total, title):
    grid = [[" "] * WIDTH for _ in range(HEIGHT)]
    for x in range(WIDTH):
        t, v = pts[x]
        row = int(round((1.0 - min(max(v, 0.0), 1.0)) * (HEIGHT - 1)))
        grid[row][x] = "#"
    split = int(round(held / total * (WIDTH - 1)))
    print(title)
    for r, line in enumerate(grid):
        if r == 0:
            lab = "1.0"
        elif r == HEIGHT - 1:
            lab = "0.0"
        elif r == HEIGHT // 2:
            lab = "0.5"
        else:
            lab = "   "
        # mark the note-off column wherever the trace does not already use it
        if line[split] == " ":
            line[split] = ":"
        print(" %s |%s" % (lab, "".join(line)))
    print("     +" + "-" * WIDTH)
    print("      %s^ note off%s0  %.2fs" % (" " * (split - 1), " " * 6, total))


def table(buf, label):
    print("  %s  release, as a fraction of the value at note-off:" % label)
    cells = []
    for tau in (0.1, 0.25, 0.5, 0.75, 0.9):
        cells.append("%.0f%%->%.2f" % (tau * 100, 1.0 - sample(buf, tau)))
    print("    " + "   ".join(cells))


def main():
    curves = [int(a) for a in sys.argv[1:]] or [1, 2, 3]
    attack_s, release_s = 0.30, 0.60
    buf = env_buffer()
    for curve in curves:
        fill_env_rise(buf, curve)
        print()
        print("=" * (WIDTH + 6))
        for release_at, note in ((1.0, "full attack"), (0.45, "released mid-rise")):
            pts, held, total = trajectory(buf, attack_s, release_s,
                                          release_at, WIDTH)
            plot(pts, held, total,
                 "fenv_curve=%d   attack %.2fs, release %.2fs   (%s)"
                 % (curve, attack_s, release_s, note))
            print()
        table(buf, "fenv_curve=%d" % curve)
        print("    a decay should be well under 0.50 by halfway; the shape this "
              "replaced\n    read 0.75 there at curve=2 -- it hung, then plunged.")


main()
