# synthlib - a small patch-based synth library on top of synthio
# Layers: Patch (pure JSON-able data) -> compile at load_patch() -> cached
# natives used in the note-on path.
#
# This file MUST exist for `from synthlib import ...` to work.

from .patch import Patch, save_patches, load_patches
from .synth import Synth
from .subtractive import SubtractiveSynth

# wavetable needs the adafruit_wave library; don't break the whole package
# if it isn't installed. Import it directly if you want it:
#     from synthlib.wavetable import WavetableSynth
try:
    from .wavetable import WavetableSynth, Wavetable
except ImportError:
    pass
