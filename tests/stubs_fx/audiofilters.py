# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""Minimal audiofilters stub: enough to check chain wiring and that the
filter stages are handed a TUPLE of biquads. No DSP.

Kept out of tests/stubs/ on purpose, so every other test still runs with
audiofilters absent, which is the path most CircuitPython builds take.
"""


class DistortionMode:
    CLIP = "CLIP"
    LOFI = "LOFI"
    OVERDRIVE = "OVERDRIVE"
    WAVESHAPE = "WAVESHAPE"


class _Effect:
    def __init__(self, **kw):
        # setattr loop, not self.__dict__.update(kw): the instance __dict__
        # is a read-only mapping on CircuitPython/MicroPython
        for k, v in kw.items():
            setattr(self, k, v)
        self.source = None

    def play(self, source):
        self.source = source


class Filter(_Effect):
    pass


class Distortion(_Effect):
    pass
