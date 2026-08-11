# SPDX-FileCopyrightText: 2017 Scott Shawcroft, written for Adafruit Industries
# SPDX-FileCopyrightText: Copyright (c) 2024 Tod Kurt
#
# SPDX-License-Identifier: MIT
"""
`synth_tools`
================================================================================

CircuitPython helper library to do help doing synthio


* Author(s): Tod Kurt

Implementation Notes
--------------------

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https://circuitpython.org/downloads

* synthio : https://docs.circuitpython.org/en/latest/shared-bindings/synthio/

"""

# imports

from .patch import Patch, save_patches, load_patches
from .synth import Synth
from .subtractive_synth import SubtractiveSynth

# wavetable_synth needs the adafruit_wave library; don't break the whole
# package if it isn't installed. Import it directly if you want it:
#     from synth_tools.wavetable import Wavetable
#     from synth_tools.wavetable_synth import WavetableSynth
try:
    from .wavetable import Wavetable
    from .wavetable_synth import WavetableSynth
except ImportError:
    pass

__version__ = "0.0.0+auto.0"
__repo__ = "https://github.com/todbot/CircuitPython_Synth_Tools.git"
