# code.py - synth_tools instrument demo for RP2040-class boards, CircuitPython 10+
import time
import board
import synthio
import audiomixer
import audiopwmio  # or audiobusio for I2S

from synth_tools import Patch, SubtractiveSynth
# from synth_tools.wavetable_synth import WavetableSynth   # needs adafruit_wave

# --- audio setup ---------------------------------------------------------
audio = audiopwmio.PWMAudioOut(board.GP10)
# audio = audiobusio.I2SOut(bit_clock=board.GP11, word_select=board.GP12,
#                           data=board.GP10)
mixer = audiomixer.Mixer(sample_rate=44100, channel_count=1,
                         buffer_size=2048)  # bigger buffer = fewer glitches
audio.play(mixer)
synth_engine = synthio.Synthesizer(sample_rate=44100)
mixer.voice[0].play(synth_engine)
mixer.voice[0].level = 0.75

# --- a patch, and a synth to put it on -----------------------------------
patch = Patch(name="fat bass", wave="SAW", detune=1.004,
              filt_type="LPF", filt_f=800, filt_q=1.4,
              amp_env=[0.01, 0.1, 0.7, 0.4],
              vib_rate=5.5, vib_depth=0.0,
              # AHR filter envelope: cutoff swings 800 -> 3800 Hz and back
              fenv_amount=3000, fenv_attack=0.02, fenv_release=0.30,
              # a slow cyclic wobble on top of it (0 = off)
              filt_lfo_rate=0.4, filt_lfo_amount=0)

synth = SubtractiveSynth(synth_engine, patch)

# JSON round-trip (saving to CIRCUITPY needs storage.remount from boot.py):
patch_json = patch.to_json()
print("patch as json:", patch_json)
patch2 = Patch.from_json(patch_json)

# swap in a wavetable synth on the same engine like this:
# wt_patch = Patch(synth_type="wavetable", wave_file="/wav/BRAIDS02.WAV",
#                  wave_pos=0, filt_type="LPF", filt_f=4000)
# synth = WavetableSynth(synth_engine, wt_patch)

# --- play: arpeggio with a live filter sweep -----------------------------
arp = (36, 39, 43, 48)
i = 0
sweep = 0
while True:
    synth.note_on(arp[i % len(arp)], velocity=110)
    time.sleep(0.11)
    synth.note_off(arp[i % len(arp)])
    time.sleep(0.02)
    i += 1

    # live filter sweep: one write into a shared block, O(1) in polyphony.
    # deadband it -- a jittery pot otherwise writes on every single frame.
    sweep = (sweep + 7) % 100
    new_f = 400 + 30 * sweep
    if abs(new_f - synth.filt_f) > 5:
        synth.filt_f = new_f

    if i % 32 == 0:  # flip waveforms now and then
        synth.wave = "SQU" if synth.wave == "SAW" else "SAW"

    # all O(1), all reach sounding voices:
    #   synth.vib_depth = 0.006        # ~10 cents of vibrato
    #   synth.fenv_amount = 2000       # filter envelope depth in Hz
    #   synth.fenv_attack = 0.01       # a rate write, cheap on a knob
    #   synth.filt_lfo_amount = 600    # cyclic cutoff wobble, Hz
    #   synth.filt_vel = -1500         # hard playing CLOSES the filter
    #   synth.pitch_bend(0.05)

    # NOTE none of the above touched `patch` -- knob turns are live state
    # only. To keep them, snapshot first:
    #   synth.save_patch().save("/my_patch.json")
    # and reloading the old patch is therefore a revert:
    #   synth.load_patch(patch2)
