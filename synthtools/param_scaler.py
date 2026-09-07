# SPDX-FileCopyrightText: Copyright (c) 2024 Tod Kurt
# SPDX-License-Identifier: MIT
"""
`param_scaler`
================================================================================

`ParamScaler` attempts to solve the "knob pickup" problem when a control's
position does not match the Param position.

The scaler will increase/decrease its internal value relative to the change
of the incoming knob position and the amount of "runway" remaining on the
value. Once the knob reaches its max or min position, the value will
move in sync with the knob.  The value will always decrease/increase
in the same direction as the knob.
This mirrors how the Deluge synth's "SCALE" mode works.

The move is::

    knob rising:   val += knob_delta * (val_max - val) / (knob_max - knob_was)
    knob falling:  val += knob_delta * (val - val_min) / (knob_was - knob_min)

where ``knob_was`` is the position the knob moved FROM, not the one it
landed on. That is what makes the two converge: dividing by the runway the
knob had *before* the move gives a value change exactly equal to the knob
change whenever the two already match, for any size of step. Dividing by
the runway left *after* the move (which this did until it was fixed)
makes a matched knob overshoot instead: a 60-count turn from a matched
centre moved the value 114.

Part of synthtools.

"""

from micropython import const

knob_min, knob_max = const(0), const(255)
val_min, val_max = const(0), const(255)

#: How close the knob has to come to the value before the two are treated
#: as matched and lock to 1:1. Same 0-255 units as everything else.
MATCH_WINDOW = const(5)

#: Knob movement below this is treated as not having happened. A scaler is
#: driven by DELTAS, and a raw ADC never sits still, so without this the
#: noise alone drags the value across the range; see the class docstring.
#: Must be larger than whatever noise survives on your knob reading.
DEADBAND = const(1)


class ParamScaler:
    """
    ParamScaler will scale its value based on input knob position, always
    trying to 'do the right thing' no matter where the current value of
    the knob is in relation to its own value

    :param val: starting value, 0-255
    :param knob_pos: where the knob is now, 0-255. Movement is measured
        from here, so pass the real position rather than assuming zero.
    :param match_window: how close the knob must come to the value before
        it locks to 1:1 tracking.
    :param deadband: knob movement below this counts as no movement. See
        below: this is not optional on real hardware.

    **A deadband is required.**  The step is scaled
    by the runway on the side the knob moved TOWARD, so the two directions
    are not symmetric. With the value at 10 and the knob sitting at 200, a
    single count of noise upward moves the value +4.46 while a count
    downward moves it -0.05: 89:1. Symmetric ADC noise is therefore a
    RATCHET that walks the value onto the knob.
    The symptom is a value that "tracks the pots" on its own
    after a page change, when it should sit still until a pot is turned.

    The deadband must exceed the noise still present in the reading you
    pass in, so smooth the ADC before it gets here if your board is noisy.
    Movement under the deadband ACCUMULATES rather than being dropped, so
    turning slowly still works.
    """

    def __init__(self, val, knob_pos, match_window=MATCH_WINDOW, deadband=DEADBAND):
        """val and knob_pos range from 0-255, floating point"""
        self.val = val
        self.knob_pos_last = knob_pos
        self.match_window = match_window
        self.deadband = deadband
        self.knob_match = False

    def reset(self, val=None, knob_pos=None):
        """Reset the ParamScaler's value and knob_pos memory"""
        if val is not None:
            self.val = val
        if knob_pos is not None:
            self.knob_pos_last = knob_pos
        self.knob_match = False

    def update(self, knob_pos):
        """Update the ParamScaler's internal value based on new knob_pos"""
        knob_was = self.knob_pos_last
        knob_delta = knob_pos - knob_was

        # Has the knob actually moved? Checked FIRST, so a resting pot
        # neither ratchets the value nor jitters it once locked.
        # knob_pos_last is deliberately NOT updated here, so movement under
        # the deadband accumulates until it clears.
        if -self.deadband < knob_delta < self.deadband:
            return self.val

        self.knob_pos_last = knob_pos

        if self.knob_match:  # locked: the knob IS the value from here on
            self.val = knob_pos
            return knob_pos

        # Catch up when the knob comes close, but only if doing so does not
        # move the value AGAINST the way the knob is being turned. Snapping
        # unconditionally lets turning a knob down jerk the value up by as
        # much as match_window to meet it. Skipping the latch leaves the
        # proportional move below, which converges within a turn or two.
        if abs(knob_pos - self.val) < self.match_window and (
            (knob_pos - self.val) * knob_delta >= 0
        ):
            self.knob_match = True
            self.val = knob_pos
            return knob_pos

        # Runway is measured from knob_was, the position the knob moved FROM;
        # see the module docstring for why. A knob that did not move falls
        # through both branches and leaves the value alone.
        if knob_delta > 0:
            runway = knob_max - knob_was
            if runway > 0:
                self.val += knob_delta * (val_max - self.val) / runway
            else:  # knob was already against the top stop
                self.val = val_max
        elif knob_delta < 0:
            runway = knob_was - knob_min
            if runway > 0:
                self.val += knob_delta * (self.val - val_min) / runway
            else:  # knob was already against the bottom stop
                self.val = val_min

        # Exact for small steps, first-order for large ones, so a coarse
        # sweep can still land outside the range.
        self.val = min(max(self.val, val_min), val_max)
        return self.val
