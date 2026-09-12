Simple test
------------

Simple bass synth showing Patch and SubtractiveSynth

.. literalinclude:: ../examples/synthtools_simpletest.py
    :caption: examples/synthtools_simpletest.py
    :linenos:

Synth filter envelope demo
--------------------------

Show how to use Synth's complex filter envelope using AHREnvelope

.. literalinclude:: ../examples/synthinst_fenv_demo.py
    :caption: examples/synthtools_fenv_demo.py
    :linenos:

Synth pitch modulation demo
---------------------------

Show how to use Synth's pitch modulation features

.. literalinclude:: ../examples/synthinst_pitch_demo.py
    :caption: examples/synthtools_pitch_demo.py
    :linenos:

Wavetable synth demo
--------------------

Demonstrate Wavetable use with an LFO on wave position

.. literalinclude:: ../examples/synthtools_wavetable_simple.py
    :caption: examples/synthtools_wavetable_simple.py
    :linenos:

Swarm synth demo
----------------

Like the Dewanatron Swarmatron: eight oscillators on one pitch, pulled apart
and back under a held drone.

.. literalinclude:: ../examples/synthtools_swarm_demo.py
    :caption: examples/synthtools_swarm_demo.py
    :linenos:
       

FM synth demo
-------------

A bright DX-style FM bell using FMSynth, with a live fm_ratio / fm_index sweep

.. literalinclude:: ../examples/synthtools_fm_demo.py
    :caption: examples/synthtools_fm_demo.py
    :linenos:

Acid bassline demos: filter/envelope/decay, accent/slide, fx
------------------------------------------------------------

Monophonic TB-303-style bassline using BasslineSynth, sweeping filter
cutoff, envelope depth (envmod), decay time, and the oscillator waveform

.. literalinclude:: ../examples/synthtools_bassline_filter_demo.py
    :caption: examples/synthtools_bassline_filter_demo.py
    :linenos:

The same bassline, sweeping the two per-step 303 flags: accent and slide

.. literalinclude:: ../examples/synthtools_bassline_accent_demo.py
    :caption: examples/synthtools_bassline_accent_demo.py
    :linenos:

The same bassline again, through BasslineSynth's owned effects chain:
an extra filter stage, distortion, and a tempo-synced echo

.. literalinclude:: ../examples/synthtools_bassline_fx_demo.py
    :caption: examples/synthtools_bassline_fx_demo.py
    :linenos:

Harmony demo
------------

Walk scales and play diatonic chords with harmony.Scale, cycling through a
short chord progression

.. literalinclude:: ../examples/synthtools_harmony_demo.py
    :caption: examples/synthtools_harmony_demo.py
    :linenos:

 
