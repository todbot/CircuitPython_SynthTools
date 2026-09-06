# pylint: disable=too-many-arguments, too-many-positional-arguments
# SPDX-FileCopyrightText: Copyright (c) 2023 Tod Kurt
# SPDX-License-Identifier: MIT
"""
``param_set.py``
================================================================================

``ParamSet`` is a collection of ``Param`` objects that track normalized
    knob positions, especially for the case when there are fewer knobs
    than params.

Each ``Param`` is a UI- and implementation-independent way of describing
    a named numerical parameter with a min/max, a display format, and
    (optionally) an object attribute that they represent.

20 May 2025 - @todbot / Tod Kurt

"""

import json


class Param:
    """Params are a UI- and implementation-independent way of describing
    a named numerical parameter with a min/max, a display format, and
    (optionally) an object attribute that they represent.
    """

    def __init__(self, name, val, vmin, vmax, fmt, objattr=None):
        self.name = name
        self.val = val
        self.vmin = vmin
        self.vmax = vmax
        self.fmt = fmt
        self.objattr = objattr

    def __str__(self):
        # fmt: off
        obstr = 'None' if self.objattr is None else "'%s'" % self.objattr
        return("Param('" + self.name + "'," + str(self.val) + "," +
               str(self.vmin) + "," + str(self.vmax) + ",'" + str(self.fmt) +
               "'," + obstr + ")")
        # fmt: on

    def __repr__(self):
        return self.__str__()

    @property
    def span(self):
        return self.vmax - self.vmin

    def knob_to_val(self, knobval):
        """Knobval ranges 0.0-1.0"""
        return self.vmin + (self.vmax - self.vmin) * knobval

    def update(self, new_knob_val):
        """Set a param val with a knob, bounded by the param's min/max attributes"""
        self.val = self.knob_to_val(new_knob_val)
        return self.val

    def apply_to_obj(self, o):
        """Apply a parameter to the given object"""
        if self.objattr:
            setattr(o, self.objattr, self.val)


class ParamSet:
    """ParamSet is a collection of Params that track normalized knob positions,
    especially for the case when there are fewer knobs than Params.
    """

    KNOB_PICKUP = 0
    KNOB_SCALE = 1
    KNOB_RELATIVE = 2

    def __init__(
        self,
        params,
        num_knobs,
        min_knob_change=0.05,
        knob_smooth=0.5,
        knob_mode=KNOB_PICKUP,
        knob_deadband=0.002,
    ):
        self.params = params
        self.knob_mode = knob_mode
        self.nparams = len(params)
        self.nknobs = num_knobs
        self.min_change = min_knob_change
        self.smoothing = knob_smooth
        # KNOB_SCALE only: knob movement, as a fraction of full travel,
        # below which nothing happens. A pot's ADC jitter is a real
        # movement to a delta-based mode, so without this a resting knob
        # rewrites its parameter on every single pass -- and writing
        # attack/decay/sustain/release rebuilds a synthio.Envelope and
        # pushes it to every sounding note. Measured jitter on a
        # pico_test_synth pot, already low-pass filtered, is ~0.0013.
        self.knob_deadband = knob_deadband
        self.nknobsets = self.nparams // self.nknobs
        self._idx = 0  # which knobset we're modifying
        self.is_tracking = [False] * self.nknobs
        # Where each knob was on the previous update. KNOB_SCALE needs it:
        # it works from how far the knob MOVED, which cannot be recovered
        # from the position alone. None until the first update_knobs(), so
        # the first call adopts the knobs rather than reading a move from
        # an assumed zero.
        self.knob_pos_last = None

    def next_knobset(self):
        self.idx = (self._idx + 1) % self.nknobsets  # calls def idx()
        return self._idx

    @property
    def idx(self):
        """Which knobset is currently being edited"""
        return self._idx

    @idx.setter
    def idx(self, i):
        """Set which knobset to edit, resets knob tracking"""
        if i != self._idx:
            self.is_tracking = [False] * self.nknobs  # reset tracking
        self._idx = i

    def update_knobs(self, new_knob_vals):
        if self.knob_mode == ParamSet.KNOB_PICKUP:
            self.update_knobs_pickup(new_knob_vals)
        elif self.knob_mode == ParamSet.KNOB_SCALE:
            self.update_knobs_scale(new_knob_vals)

    def update_knobs_pickup(self, new_knob_vals):
        """new_knob_vals is list of new knob vals, each 0.0-1.0"""
        for i in range(self.nknobs):
            param = self.params[(self._idx * self.nknobs) + i]
            new_val = param.knob_to_val(new_knob_vals[i])
            if self.is_tracking[i]:
                # only change param val if difference is big enough FIXME
                if abs(new_val - param.val) >= 0.1 * self.min_change * param.span:
                    param.val = new_val
            else:
                delta = param.val - new_val
                if abs(delta) < self.min_change * param.span:
                    self.is_tracking[i] = True

    def update_knobs_scale(self, new_knob_vals):
        """new_knob_val is list of new knob vals, each normalized 0.0-1.0

        Proportional ("scale") takeover, the same one ui/param_scaler.py
        implements: every turn moves the value, by the knob's movement
        scaled by the runway each has left, so the two converge and reach
        the ends together. Unlike PICKUP, a knob is never dead.

            knob rising:   val += dk * (vmax - val) / (1 - k_was)
            knob falling:  val += dk * (val - vmin) / k_was

        ``k_was`` is where the knob moved FROM, and dividing by ITS runway
        is what makes a matched knob track exactly 1:1 at any step size.

        Movement smaller than ``knob_deadband`` is ignored, because a
        delta-based mode cannot tell pot jitter from a real turn; see the
        constructor. It accumulates rather than being discarded, so a slow
        turn still registers.

        This used to be wrong in a way worth naming, since the shape of
        the bug is easy to reintroduce: it had no memory of the previous
        knob position, and used knob-minus-value in place of the knob's
        movement. That is a distance, not a delta, so a mismatched value
        crept toward the knob on its own while the pot sat still, and
        could move against the direction the knob was turned.
        """
        # First call: adopt the knob positions without moving anything.
        if self.knob_pos_last is None:
            self.knob_pos_last = list(new_knob_vals)
            return

        for i in range(self.nknobs):
            param = self.params[(self._idx * self.nknobs) + i]
            knob = new_knob_vals[i]
            knob_was = self.knob_pos_last[i]
            knob_delta = knob - knob_was
            if -self.knob_deadband < knob_delta < self.knob_deadband:
                # Deliberately leave knob_pos_last alone, so movement
                # under the deadband ACCUMULATES until it clears rather
                # than being dropped -- otherwise a slow turn is silently
                # thrown away one sample at a time.
                continue
            self.knob_pos_last[i] = knob

            new_val = param.knob_to_val(knob)
            # Once the knob has caught up, it stays 1:1. is_tracking is
            # the same latch PICKUP uses, and idx's setter clears it on a
            # page turn for both modes.
            if self.is_tracking[i]:
                param.val = new_val
                continue
            # Catch up when the knob comes close -- but only if that does
            # not move the value AGAINST the way the knob is turning. An
            # unconditional latch means turning a knob down can jerk the
            # value up by as much as the match window to meet it.
            if abs(new_val - param.val) < self.min_change * param.span and (
                (new_val - param.val) * knob_delta >= 0
            ):
                self.is_tracking[i] = True
                param.val = new_val
                continue

            if knob_delta > 0:
                runway = 1.0 - knob_was
                if runway > 0:
                    param.val += knob_delta * (param.vmax - param.val) / runway
                else:  # knob was already at the top stop
                    param.val = param.vmax
            elif knob_delta < 0:
                runway = knob_was
                if runway > 0:
                    param.val += knob_delta * (param.val - param.vmin) / runway
                else:  # knob was already at the bottom stop
                    param.val = param.vmin

            # Exact for small steps, first-order for large ones, so a
            # coarse sweep can still land outside the range.
            param.val = min(max(param.val, param.vmin), param.vmax)

    def apply_params(self, obj):
        """Apply all params to given object"""
        for i in range(self.nparams):
            self.params[i].apply_to_obj(obj)

    def apply_knobset(self, obj):
        """Apply all vals in a knobset to given object"""
        for i in range(self.nknobs):
            self.params[(self._idx * self.nknobs) + i].apply_to_obj(obj)

    def param_for_name(self, name):
        for p in filter(lambda p: p.name == name, self.params):
            return p
        return None

    # fmt: off
    def __str__(self):
        return("ParamSet(nknobs="+str(self.nknobs) + ", " +
               "nknobsets="+str(self.nknobsets) +
               ", params="+str(self.params)+")")
    # fmt: on

    @staticmethod
    def load(dumpstr):
        dumpobj = json.loads(dumpstr)
        newparams = [Param(**d) for d in dumpobj["params"]]
        return newparams

    @staticmethod
    def dump(paramset):
        dumpobj = {"params": [p.__dict__ for p in paramset.params]}
        return json.dumps(dumpobj)


# simple test

if __name__ == "__main__":
    myparams = [
        Param("cutoff", 8000, 0, 9000, "%4d", "filt_frequency"),
        Param("envmod", 0.5, 0.0, 1.0, "%.2f", "filt_env_depth"),
        Param("resq", 8000, 0, 9000, "%4d", "resonance"),
        Param("decay", 0.5, 0.0, 1.0, "%.2f", "decay"),
    ]

    param_set = ParamSet(myparams, num_knobs=2)

    print("param_set:", param_set)
