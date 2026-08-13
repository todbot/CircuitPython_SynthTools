# SPDX-FileCopyrightText: Copyright (c) 2023 Tod Kurt
# SPDX-License-Identifier: MIT

from collections import deque


class RollingAverage:
    """A fixed-size moving average, for smoothing/deadbanding noisy knob
    reads. update() pushes a new value onto a ``window_size``-deep deque and
    returns the mean of whatever is currently in it -- so the window is
    still filling for the first ``window_size`` calls."""

    def __init__(self, window_size):
        self.d = deque((), window_size)
        self.window_size = window_size

    def update(self, new_value):
        self.d.append(new_value)
        return sum(self.d) / self.window_size
