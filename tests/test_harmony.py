# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""harmony: scales, chords, and the degree-wrap arithmetic.

harmony.py imports nothing, so this runs on a bare interpreter and is a
portability canary alongside test_patch.py / test_paramset.py: the whole
reason Scale.degree() uses divmod is that a pad row indexes past the end
of the scale, and negative divmod has to wrap the same way on MicroPython.

    python3 tests/test_harmony.py
    micropython tests/test_harmony.py
"""

import sys

_D = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _D + "/../synthtools")  # direct: skips synthtools/__init__

from harmony import (  # noqa: E402
    CHORD_NAMES,
    CHORDS,
    DIATONIC_SHAPE_NAMES,
    DIATONIC_SHAPES,
    SCALE_NAMES,
    SCALES,
    Scale,
    chord,
    note_name,
)

fails = []


def ck(cond, msg):
    if not cond:
        fails.append(msg)


# --- the portability canary -------------------------------------------
# Python floors towards negative infinity, so divmod(-1, 7) == (-1, 6):
# degree(-1) is the top note of the octave below. MicroPython must agree.
ck(divmod(-1, 7) == (-1, 6), "negative divmod does not wrap: %r" % (divmod(-1, 7),))
ck(divmod(-8, 7) == (-2, 6), "negative divmod does not wrap over an octave")


# --- Scale.degree ----------------------------------------------------
s = Scale(60, "major")
ck(
    [s.degree(n) for n in range(8)] == [60, 62, 64, 65, 67, 69, 71, 72],
    "C major degrees 0..7 wrong: %r" % [s.degree(n) for n in range(8)],
)
ck(s.degree(7) == s.root + 12, "degree(size) is not the octave: %d" % s.degree(7))
ck(s.degree(-1) == 59, "degree(-1) is not the leading tone below: %d" % s.degree(-1))
ck(s.degree(14) == 84, "two octaves up wrong: %d" % s.degree(14))
ck(s[3] == s.degree(3), "__getitem__ disagrees with degree()")
ck(s.size == 7, "major scale size should be 7, got %d" % s.size)

# a pentatonic keeps climbing past its 5 notes
p = Scale(57, "minor_pentatonic")
ck(
    [p.degree(n) for n in range(6)] == [57, 60, 62, 64, 67, 69],
    "A minor pentatonic wrong: %r" % [p.degree(n) for n in range(6)],
)


# --- chromatic chord() --------------------------------------------------
ck(chord(60, "maj") == [60, 64, 67], "C maj wrong: %r" % chord(60, "maj"))
ck(chord(60, "min") == [60, 63, 67], "C min wrong: %r" % chord(60, "min"))
ck(chord(60, "dom7") == [60, 64, 67, 70], "C7 wrong: %r" % chord(60, "dom7"))
ck(chord(48, "maj9") == [48, 52, 55, 59, 62], "Cmaj9 wrong: %r" % chord(48, "maj9"))


# --- Scale.chord: diatonic quality falls out of the key --------------
c = Scale(60, "major")
ck(c.chord(0, "triad") == [60, 64, 67], "I is not major: %r" % c.chord(0, "triad"))
ck(c.chord(1, "triad") == [62, 65, 69], "ii is not minor: %r" % c.chord(1, "triad"))
ck(c.chord(6, "triad") == [71, 74, 77], "vii is not diminished-shaped")
ck(c.chord(4, "7th") == [67, 71, 74, 77], "V7 is not dominant-shaped: %r" % c.chord(4, "7th"))
ck(len(c.chord(0, "9th")) == 5, "9th is not 5 notes")
ck(c.chord(0, (0, 4)) == [60, 67], "explicit degree-offset shape ignored")
ck(c.chord(0, "spread")[-1] > c.chord(0, "spread")[0] + 12, "spread does not open past an octave")


# --- set_scale ------------------------------------------------------
q = Scale(60, "major")
q.set_scale("bogus_scale")
ck(q.name == "major" and q.steps == SCALES["major"], "unknown scale did not fall back to major")
q.set_scale((0, 3, 7))
ck(q.name == "custom" and q.steps == (0, 3, 7), "explicit offsets not accepted")
ck(q.degree(0) == 60 and q.degree(1) == 63 and q.degree(3) == 72, "custom scale degrees wrong")


# --- contains / snap --------------------------------------------------
cm = Scale(60, "major")
ck(cm.contains(64) and cm.contains(64 + 12) and cm.contains(64 - 24), "E should be in C major")
ck(not cm.contains(61) and not cm.contains(61 + 12), "C# should not be in C major")
ck(cm.snap(61) == 60, "snap C#4 -> C4 expected, got %d" % cm.snap(61))
ck(cm.snap(66) == 65, "snap F#4 -> F4 expected, got %d" % cm.snap(66))
ck(cm.snap(67) == 67, "snap of an in-scale note must be a no-op, got %d" % cm.snap(67))
ck(cm.snap(72) == 72, "snap of the octave must be a no-op, got %d" % cm.snap(72))


# --- note_name -----------------------------------------------------
ck(note_name(60) == "C4", "MIDI 60 is C4 here, got %s" % note_name(60))
ck(note_name(69) == "A4", "MIDI 69 is A4, got %s" % note_name(69))
ck(note_name(61, False) == "C#", "note_name without octave wrong: %s" % note_name(61, False))
ck(note_name(48) == "C3" and note_name(72) == "C5", "octave numbering off")


# --- table invariants -----------------------------------------------
for name, steps in SCALES.items():
    ck(isinstance(steps, tuple) and steps[0] == 0, "scale %s must be a tuple starting at 0" % name)
    ck(list(steps) == sorted(steps), "scale %s not ascending" % name)
    ck(all(0 <= x <= 11 for x in steps), "scale %s has an out-of-octave step" % name)
for name, ivals in CHORDS.items():
    ck(isinstance(ivals, tuple) and ivals[0] == 0, "chord %s must be a tuple starting at 0" % name)
for name, offs in DIATONIC_SHAPES.items():
    ck(isinstance(offs, tuple) and offs[0] == 0, "shape %s must be a tuple starting at 0" % name)

# The *_NAMES tuples are hand-written (MicroPython dict order is not
# stable) so a UI selector index means the same thing everywhere: check
# they cover their dicts exactly, and that the fixed order holds.
for names, table, what in (
    (SCALE_NAMES, SCALES, "SCALE_NAMES"),
    (CHORD_NAMES, CHORDS, "CHORD_NAMES"),
    (DIATONIC_SHAPE_NAMES, DIATONIC_SHAPES, "DIATONIC_SHAPE_NAMES"),
):
    ck(set(names) == set(table), "%s does not cover its dict exactly" % what)
    ck(len(names) == len(table), "%s has a duplicate or a gap" % what)
ck(SCALE_NAMES[0] == "major", "major must stay first in SCALE_NAMES (the default)")
ck(DIATONIC_SHAPE_NAMES[3] == "triad", "DIATONIC_SHAPE_NAMES order shifted")


if fails:
    print("FAIL (%d)" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_harmony: ok")
