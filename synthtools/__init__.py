# SPDX-FileCopyrightText: 2017 Scott Shawcroft, written for Adafruit Industries
# SPDX-FileCopyrightText: Copyright (c) 2024 Tod Kurt
#
# SPDX-License-Identifier: MIT
"""
`synthtools`
================================================================================

CircuitPython helper library to do help doing synthio


* Author(s): Tod Kurt

Implementation Notes
--------------------

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https://circuitpython.org/downloads

* synthio : https://docs.circuitpython.org/en/latest/shared-bindings/synthio/

Importing
---------

Names are resolved LAZILY: ``from synthtools import Patch`` imports
``synthtools.patch`` and nothing else. Only the styles you actually name get
loaded, so adding a synth style to this library costs nothing to anyone who
does not use it.

That matters on a microcontroller. Re-exporting eagerly (the ordinary
desktop pattern of ``from .bassline_synth import BasslineSynth`` at module
level) pulled in EVERY module on any touch of the package, measured at
52,784 bytes of a Pico's ~137 KB free RAM, and it could not be dodged from
the call site: importing a submodule runs this file first either way. Do not
reintroduce eager re-exports here.

Anything not listed below is still importable by its module path::

    from synthtools.waves import get_wave
    from synthtools.step_sequencer import StepSequencer
"""

import sys

__version__ = "0.0.0+auto.0"
__repo__ = "https://github.com/todbot/CircuitPython_SynthTools.git"

#: Public name -> the submodule that defines it. Every entry is loaded on
#: first use and cached by the import system, never at package import.
_LAZY = {
    "EffectsChain": "audio_fx",
    "set_drive": "audio_fx",
    "sync_delay": "audio_fx",
    "tracking_filter": "audio_fx",
    "BasslineSynth": "bassline_synth",
    "FMSynth": "fm_synth",
    "GaugeCluster": "gauge_cluster",
    "ParamScaler": "param_scaler",
    "Patch": "patch",
    "load_patches": "patch",
    "save_patches": "patch",
    "SubtractiveSynth": "subtractive_synth",
    "SwarmSynth": "swarm_synth",
    "Synth": "synth",
    # These two additionally need adafruit_wave. Asking for one without it
    # raises ImportError naming adafruit_wave, rather than the name simply
    # not existing.
    "Wavetable": "wavetable",
    "WavetableSynth": "wavetable_synth",
}

__all__ = tuple(sorted(_LAZY))


def __getattr__(name):
    """Import the submodule that defines ``name`` on first access (PEP 562).

    Verified on CircuitPython 10.3.0-alpha.3 as well as CPython and
    MicroPython. Note the import must be spelled as an absolute
    ``__import__`` of the dotted path: ``from . import <mod>`` re-enters
    this function on MicroPython (a package-attribute lookup) and
    recurses into AttributeError.
    """
    modname = _LAZY.get(name)
    if modname is None:
        raise AttributeError(name)
    full = __name__ + "." + modname
    if full not in sys.modules:
        __import__(full)
    return getattr(sys.modules[full], name)
