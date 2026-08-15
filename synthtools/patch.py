# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# patch.py - pure-data patch objects, trivially JSON serializable.
# Rule: only JSON-native types live here (str, int, float, bool, list).
# Never a synthio object, never a ulab array.

import json


class Patch:
    """A synth patch. Unknown kwargs land in __dict__ and round-trip
    through JSON untouched, so synth-type-specific fields (wave_file,
    wave_pos, ...) need no subclassing."""

    def __init__(self, **kw):
        self.name = "init"
        self.synth_type = "subtractive"  # dispatch hint for patch banks
        self.wave = "SAW"  # waveform name, see waves.py
        self.detune = 1.001  # osc2 freq ratio, 1.0 = single osc
        self.filt_type = "LPF"  # "LPF" | "HPF" | "BPF" | "NOTCH" | None
        self.filt_f = 2500  # filter cutoff in Hz
        self.filt_q = 1.1  # filter resonance
        # list, not tuple: JSON round-trips it as a list anyway, and a list
        # lets you set one stage in place (amp_env[0] = x) without rebuilding.
        self.amp_env = [0.01, 0.10, 0.8, 0.35]  # attack, decay, sustain, release
        self.vib_rate = 5.0  # Hz
        self.vib_depth = 0.0  # in bend units: 1.0 = one octave, 0.006 ~ 10 cents
        self.vib_delay = 0.0  # seconds for vibrato to fade in (0 = immediate)
        # Portamento. Only applies while the synth's `mono` is set; a
        # polyphonic synth ignores it. 0 = jump straight to pitch.
        self.glide_time = 0.0  # seconds to slide from the previous note
        # Pitch envelope, in the same bend units. Bends INTO the note from
        # penv_amount to true pitch, then on note-off drifts OUT to
        # penv_out_amount. Both amounts default to 0 = off, and a voice with
        # both off costs nothing.
        self.penv_amount = 0.0  # bend at note-on; + starts sharp, - flat
        self.penv_time = 0.10  # seconds to settle to true pitch
        self.penv_out_amount = 0.0  # bend drifted to after note-off
        self.penv_out_time = 0.20  # seconds for that drift
        # --- the four filter-cutoff modulations -----------------------
        # cutoff = filt_f + filt_lfo + fenv + velocity, summed in one
        # synthio block graph. See synth.py.
        # 1. filt_f above is the base.
        # 2. cyclic LFO, additive: filt_f is the floor, the LFO opens upward
        self.filt_lfo_rate = 0.5  # Hz
        self.filt_lfo_amount = 0  # Hz added above filt_f, 0..amount; 0 = off
        # 3. AHR envelope, added to the cutoff in Hz. amount 0 = off (and
        #    costs nothing: no per-voice blocks are created).
        self.fenv_amount = 0  # Hz of cutoff swing; negative sweeps down
        self.fenv_attack = 0.05  # seconds to reach full depth
        self.fenv_release = 0.40  # seconds to fall back to zero
        # Integer exponent on the envelope shape: 1 = linear, 2+ increasingly
        # curved. The attack rises fast and eases into the peak; the release
        # drops fast and tails off -- the conventional analog feel. Both come
        # from one shared buffer holding 1-(1-t)^curve, so they are linked:
        # see fill_env_rise() in waves.py for why the release decides.
        self.fenv_curve = 1
        # 4. Velocity. The units differ on purpose: filt_vel adds to a
        #    cutoff so it is in Hz, fenv_vel scales a depth so it is a
        #    0-1 fraction. Both default to "velocity changes nothing".
        self.filt_vel = 0  # Hz of cutoff at full velocity; negative
        #                       means hard playing CLOSES the filter
        self.fenv_vel = 0.0  # 0 = uniform depth, 1.0 = depth tracks velocity
        # setattr loop, not self.__dict__.update(kw): CircuitPython's
        # instance __dict__ is a read-only mapping and update() raises
        # TypeError. Reading it (dict(self.__dict__)) is fine.
        for k, v in kw.items():
            setattr(self, k, v)

    # --- dict / JSON round-trip -------------------------------------

    def to_dict(self):
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def to_json(self):
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, s):
        return cls(**json.loads(s))

    # --- filesystem helpers -----------------------------------------
    # note: writing to CIRCUITPY from code requires storage.remount()

    def save(self, filepath):
        with open(filepath, "w") as f:
            f.write(self.to_json())

    @classmethod
    def load(cls, filepath):
        with open(filepath) as f:
            return cls.from_json(f.read())

    def __repr__(self):
        return "Patch(%s)" % ", ".join("%s=%r" % (k, v) for k, v in sorted(self.__dict__.items()))


# --- simple patch banks: a JSON list of patch dicts -----------------


def save_patches(patches, filepath):
    """Write a list of Patch objects to filepath as one JSON array."""
    with open(filepath, "w") as f:
        json.dump([p.to_dict() for p in patches], f)


def load_patches(filepath):
    """Read a list of Patch objects back from a file written by
    save_patches()."""
    with open(filepath) as f:
        return [Patch.from_dict(d) for d in json.load(f)]
