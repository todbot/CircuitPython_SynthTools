Introduction
============


.. image:: https://readthedocs.org/projects/circuitpython-synthtools/badge/?version=latest
    :target: https://circuitpython-synthtools.readthedocs.io/
    :alt: Documentation Status



.. image:: https://img.shields.io/discord/327254708534116352.svg
    :target: https://adafru.it/discord
    :alt: Discord


.. image:: https://github.com/todbot/CircuitPython_SynthTools/workflows/Build%20CI/badge.svg
    :target: https://github.com/todbot/CircuitPython_SynthTools/actions
    :alt: Build Status


.. image:: https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json
    :target: https://github.com/astral-sh/ruff
    :alt: Code Style: Ruff

CircuitPython library with tools for making synths with synthio

This library is a collection of tools derived from my many years of playing
with CircuitPython, ``synthio``, and building synthesizers in general.
Concepts pulled from these projects and others:

- `CircuitPython Synthio Tutorial <https://todbot.github.io/CircuitPython_Synthio_Tutorial/>`_
- `circuitpython synthio tricks <https://github.com/todbot/circuitpython-synthio-tricks>`_
- `pico_test_synth <https://github.com/todbot/pico_test_synth>`_
- `picotouch_synth <https://github.com/todbot/picotouch_synth>`_
- `picostepseq <https://github.com/todbot/picostepseq>`_

Dependencies
=============
This driver depends on:

* `Adafruit CircuitPython <https://github.com/adafruit/circuitpython>`_

Please ensure all dependencies are available on the CircuitPython filesystem.
This is easily achieved by downloading
`the Adafruit library and driver bundle <https://circuitpython.org/libraries>`_
or individual libraries can be installed using
`circup <https://github.com/adafruit/circup>`_.


Installing to a Connected CircuitPython Device with Circup
==========================================================

Make sure that you have ``circup`` installed in your Python environment.
Install it with the following command if necessary:

.. code-block:: shell

    pip3 install circup

With ``circup`` installed and your CircuitPython device connected use the
following command to install:

.. code-block:: shell

    circup install synthtools

Or the following command to update an existing version:

.. code-block:: shell

    circup update

Usage Example
=============

.. code-block:: python

    import time
    from synth_setup import synth as engine
    from synthtools import Patch, SubtractiveSynth

    patch1 = Patch(name="fat bass", wave="ASAW", detune=1.004,
                   filt_type="LPF", filt_f=800, filt_q=1.4,
                   amp_env=[0.01, 0.1, 0.8, 0.4],
                   vib_rate=5.5, vib_depth=0.0,
                   # AHR filter envelope: cutoff swings 800 -> 3800 Hz and back
                   fenv_amount=3000, fenv_attack=0.02, fenv_release=0.30,
                   # a slow cyclic wobble on top of it (0 = off)
                   filt_lfo_rate=0.4, filt_lfo_amount=0.3)
    synth = SubtractiveSynth(engine, patch1)
    arp = (36, 39, 43, 48)
    i = 0
    sweep = 0
    while True:
        synth.note_on(arp[i % len(arp)], velocity=110)
        time.sleep(0.11)
        synth.note_off(arp[i % len(arp)])
        time.sleep(0.02)
        i += 1
        if i % 32 == 0:  # flip waveforms now and then
            synth.wave = "ASQU" if synth.wave == "ASAW" else "ASAW"


What's Included
===============

* ``Synth`` -- synth engine base: shared voice, patch, and modulation handling,
  with ``mono`` mode for a single-voice synth with ``glide_time``  portamento
* ``SubtractiveSynth`` -- subtractive two-oscillator synth w/ detune
* ``FMSynth`` -- two-operator phase-modulation voice: a carrier waveform
  pre-rendered from ``sin(theta + fm_index*sin(fm_ratio*theta))``.
  ``fm_ratio`` must be an integer; ``fm_index`` is PM depth in radians,
  0 = plain single-oscillator. (Not a live audio-rate bend modulator --
  synthio's Math/LFO blocks only update every 256 samples, too slow for
  that; see the module docstring for why.)
* ``WavetableSynth`` -- wavetable-playback with adjustable wave_pos
* ``BasslineSynth`` -- TB-303-style acid bassline: monophonic, one
  oscillator, a decay-only filter sweep, per-step slide and accent. Can
  own its own filter/distortion/echo effects chain via ``fx_*`` patch
  fields
* ``EffectsChain`` -- a generic post-synth effects chain: add, insert, or
  remove any ``audiofilters``/``audiodelays`` effect and it stays wired.
  ``tracking_filter()`` builds extra filter stages that follow the synth's
  own cutoff and resonance for a steeper slope (needs ``audiofilters`` in
  the build)
* ``Patch`` -- inert, JSON-able patch data; save/load with
  ``save_patches()`` / ``load_patches()``
* ``Wavetable`` -- loads a wavetable WAV file and lerps between frames
* ``AHREnvelope`` -- shared-block attack/release envelope, used for both
  the filter and pitch envelopes
* ``Waves`` -- waveform factory (saw, square, sine, triangle, noise, and
  "analog" variants)
* ``Arpeggiator`` / ``StepSequencer`` / ``TrigSequencer`` -- poll-based
  sequencers with on/off callbacks
* ``Param`` / ``ParamSet`` -- knob-pickup and scaling for UIs with fewer
  knobs than parameters
* ``ParamScaler`` -- proportional ("scale") knob takeover for a single
  control, when you are not using ``ParamSet``
* ``GaugeCluster`` -- a bar-graph display of a parameter page
* ``Glider`` -- a standalone pitch-slide block for hand-built
  ``synthio.Note`` graphs (the engines above have their own portamento,
  via ``mono`` + ``glide_time``)
* ``RollingAverage`` -- moving-average smoothing for noisy knob reads

Documentation
=============
API documentation for this library can be found on `Read the Docs <https://circuitpython-synthtools.readthedocs.io/>`_.

For information on building library documentation, please check out
`this guide <https://learn.adafruit.com/creating-and-sharing-a-circuitpython-library/sharing-our-docs-on-readthedocs#sphinx-5-1>`_.

Contributing
============

Contributions are welcome! Please read our `Code of Conduct
<https://github.com/todbot/CircuitPython_SynthTools/blob/HEAD/CODE_OF_CONDUCT.md>`_
before contributing to help this project stay welcoming.
