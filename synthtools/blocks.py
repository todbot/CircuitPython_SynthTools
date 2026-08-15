# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# blocks.py - tiny constructors for synthio's BlockInput graph.
#
# Its own module so synth.py and ahr_envelope.py can share these without a
# circular import (synth.py imports ahr_envelope).
#
# These exist so graph-building code reads as arithmetic instead of
# synthio.Math(synthio.MathOperation.X, ...) boilerplate, and so the
# operation names appear in exactly one place. Every argument may be a
# number OR another block -- that is the whole point.
#
# Plain functions rather than synthio's callable-MathOperation shorthand
# (MathOperation.SUM(a, b, c)): not worth depending on in a library that
# has to run on whatever CircuitPython build is on the board.

import synthio

_OP = synthio.MathOperation


def scalar_block(v):
    """A settable scalar as a synthio block: write .a to change it.

    This is the whole trick behind the O(1) parameter design: anywhere
    synthio takes a BlockInput, one of these can stand in for a number and
    stay writable afterwards, so a single write reaches every voice that
    nested it.
    """
    return synthio.Math(_OP.SUM, v, 0.0, 0.0)


def sum3(a, b=0.0, c=0.0):
    """a + b + c."""
    return synthio.Math(_OP.SUM, a, b, c)


def product(a, b, c=1.0):
    """a * b * c."""
    return synthio.Math(_OP.PRODUCT, a, b, c)


def lerp(a, b, t):
    """a*(1-t) + b*t, t unclamped."""
    return synthio.Math(_OP.LERP, a, b, t)


def constrained_lerp(a, b, t):
    """a*(1-t) + b*t with t clamped to 0..1.

    The one to reach for when t is a one-shot LFO used as a POSITION: it
    cannot overshoot past b if the LFO reads slightly beyond its last
    sample. See ahr_envelope.py and Synth's glide.
    """
    return synthio.Math(_OP.CONSTRAINED_LERP, a, b, t)


def clamp(x, lo, hi):
    """x limited to [lo, hi] -- the middle of three values IS a clamp, so
    this is one block rather than a MIN of a MAX."""
    return synthio.Math(_OP.MID, x, lo, hi)
