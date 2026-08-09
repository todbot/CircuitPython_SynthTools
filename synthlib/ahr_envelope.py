# ahr_envelope.py - Attack-Release envelope for synthio, as a modulation
# SOURCE: it produces 0 -> amount and knows nothing about where that goes.
#
# Per voice, three objects:
#
#   pos = LFO(waveform = shared shape, rate = shared rate, once = True)
#   env = Math(CONSTRAINED_LERP, 0.0, depth, pos)      -> the output block
#         depth = the shared amount block, or PRODUCT(amount, gain)
#
# The LFO is only a *position*: it runs 0 -> 1 through a shared, shaped
# buffer, and CONSTRAINED_LERP decides what that position maps onto. So
# release is a matter of moving the endpoints -- NOT of swapping the
# waveform. That matters: synthio.LFO.waveform is read-only (verified on
# CircuitPython 10.3.0-alpha.4, rp2350), so an implementation that
# reassigns it raises
#   AttributeError: can't set attribute 'waveform'
# at every note-off. Mutating the buffer's contents in place is fine, and
# is documented synthio behaviour.
#
# --- why this is bigger than the tutorial's version -------------------
#
# todsynth/ahr_envelope.py in the synthio tutorial is the same
# CONSTRAINED_LERP idea, and it is the right size for a monosynth: one
# object per voice, writing plain floats into env.a / env.b at press. The
# cost of that is that every global parameter is O(polyphony) -- moving the
# envelope depth means looping over live voices and writing each one.
#
# This is the polyphonic version. ONE instance is a factory for many
# voices, and the things a knob touches are shared objects nested inside
# each voice's graph:
#
#   _amt      the depth, nested in every voice's `depth`
#   _rate_a   the attack rate, every voice's LFO rate
#   _rate_r   the release rate
#   _wave     the shape, rewritten in place under sounding voices
#
# so amount, attack, release and curve each reach every sounding voice --
# including ones already in release -- with a SINGLE write. That is the
# only reason for the extra indirection. The shared buffer also buys
# arbitrary integer curve exponents for free, where the tutorial's
# PRODUCT(lerp, lerp, 1) costs one Math per voice and only gives squared.

import synthio

from .blocks import scalar_block, product
from .waves import env_buffer, fill_env_rise


class AHREnvelope:
    """Shared-block attack/release envelope. One instance owns the shape
    buffer, the rate blocks and the depth block; make() hands out one small
    block graph per voice that reads them.

    Destination-agnostic on purpose -- the output is a plain 0 -> amount
    signal, so the same class drives a filter cutoff (add it to the cutoff
    bus) or, later, a pitch envelope (add it to the bend graph)."""

    def __init__(self, attack=0.05, release=0.4, amount=0.0, curve=1):
        self._attack = attack
        self._release = release
        self._curve = curve
        # Created ONCE and never replaced. Sounding voices hold references
        # to all of these, so identity has to survive patch reloads --
        # assigning a new object here would orphan the live ones.
        self._wave = env_buffer()
        self._rate_a = scalar_block(1.0)
        self._rate_r = scalar_block(1.0)
        self._amt = scalar_block(amount)
        self._refresh_shape()
        self._refresh_rates()

    # --- shape ----------------------------------------------------------

    def _refresh_shape(self):
        """Rewrite the shared shape in place. Voices already sounding pick
        this up immediately, because they read this very buffer."""
        fill_env_rise(self._wave, self._curve)

    def _refresh_rates(self):
        # the rise fills the whole buffer, so a rate is just 1/seconds --
        # no fraction to correct for
        self._rate_a.a = 1.0 / max(self._attack, 0.001)
        self._rate_r.a = 1.0 / max(self._release, 0.001)

    def configure(self, attack, release, amount, curve):
        """Set everything at once with a single shape rebuild. For patch
        loads; the individual properties are the knob path."""
        self._attack = attack
        self._release = release
        self._curve = curve
        self._amt.a = amount
        self._refresh_shape()
        self._refresh_rates()

    # --- live parameters, all O(1) --------------------------------------

    @property
    def attack(self):
        return self._attack

    @attack.setter
    def attack(self, v):
        # only a rate now: no shape rebuild, so this is cheap on a knob
        self._attack = v
        self._refresh_rates()

    @property
    def release(self):
        return self._release

    @release.setter
    def release(self, v):
        self._release = v
        self._refresh_rates()

    @property
    def curve(self):
        return self._curve

    @curve.setter
    def curve(self, v):
        # a switch, not a knob: rebuilds the shape, so it allocates
        self._curve = v
        self._refresh_shape()

    @property
    def amount(self):
        return self._amt.a

    @amount.setter
    def amount(self, v):
        # one write into the shared block, reaching every voice including
        # ones already in release (it stays live inside each voice's depth)
        self._amt.a = v

    # --- per-voice ------------------------------------------------------

    def make(self, gain=1.0):
        """One voice's envelope, or None when the depth is zero.

        Returns the CONSTRAINED_LERP block to add to a destination. It
        carries everything start_release() needs: the position LFO in `c`.

        `gain` is a per-voice depth scale -- a plain number, or a block
        (e.g. a velocity LERP) so whatever drives it stays live.

        Returning None when the amount is 0 is what makes the envelope cost
        literally nothing when switched off. The flip side: a voice pressed
        while amount was 0 has no envelope at all, so raising it mid-note
        only affects NEW notes.
        """
        if not self._amt.a:
            return None
        # A plain 1.0 means "nothing is scaling this", and the voice can use
        # the shared block directly -- one Math lighter in the common case.
        # A BLOCK is always wrapped, even if it happens to evaluate to 1.0
        # right now, because it can change while the voice sounds. Hence the
        # isinstance rather than a bare `gain == 1.0`: what a synthio block
        # does under `==` is not ours to assume.
        if isinstance(gain, (int, float)) and gain == 1.0:
            depth = self._amt
        else:
            depth = product(self._amt, gain)
        pos = synthio.LFO(waveform=self._wave, rate=self._rate_a, once=True)
        return synthio.Math(synthio.MathOperation.CONSTRAINED_LERP,
                            0.0, depth, pos)

    def start_release(self, env):
        """Send a voice's envelope into release. Call at note-off.

        Re-aims the same position LFO instead of swapping its waveform, so
        the fall starts wherever the attack actually got to and a key lifted
        mid-attack does not jump to full depth first. Continuity is
        structural: there is no gain to recompute and no base to restore,
        because the envelope's floor is simply 0.
        """
        env.a = env.value       # fall from here...
        env.b = 0.0             # ...back to nothing
        env.c.rate = self._rate_r
        env.c.retrigger()
