#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# run.sh -- render every case under a CircuitPython unix build, then analyze
# under desktop CPython. Writes tests/render/out/{*.wav,FINDINGS.md,metrics.json}.
#
#   sh tests/render/run.sh
#   MICROPYTHON=/path/to/micropython sh tests/render/run.sh
#   sh tests/render/run.sh --mp /path/to/micropython
#
# Requirements:
#   - a CircuitPython "unix" build with synthio + audiocore + ulab, built with
#     CIRCUITPY_AUDIOCORE_DEBUG=1 (the `coverage` variant); audiofilewriter is
#     NOT needed.
#   - a directory containing adafruit_wave.py (pure Python), via $ADAFRUIT_WAVE_DIR.

set -e
cd "$(dirname "$0")/../.."   # repo root

MP=${MICROPYTHON:-$HOME/projects/adafruit/circuitpython-claudetest/ports/unix/build-coverage/micropython}
case "$1" in
    --mp) MP="$2"; shift 2 ;;
esac
WAVE_LIB=${ADAFRUIT_WAVE_DIR:-$HOME/projects/adafruit/circuitpython-claudetest/frozen/Adafruit_CircuitPython_Wave}

if ! { [ -x "$MP" ] || command -v "$MP" >/dev/null 2>&1; }; then
    echo "no micropython at '$MP' -- set \$MICROPYTHON or pass --mp <path>" >&2
    exit 1
fi
if [ ! -f "$WAVE_LIB/adafruit_wave.py" ]; then
    echo "no adafruit_wave.py under '$WAVE_LIB' -- set \$ADAFRUIT_WAVE_DIR" >&2
    exit 1
fi

OUT=tests/render/out
mkdir -p "$OUT"

echo "check: Wavetable.set_wave_pos() correctness"
"$MP" tests/render/check_wavetable.py --wave-lib "$WAVE_LIB"

echo "check: WavetableSynth correctness"
"$MP" tests/render/check_wavetable_synth.py --wave-lib "$WAVE_LIB"

echo
echo "render: $MP"
"$MP" tests/render/render_chords.py --wave-lib "$WAVE_LIB" --outdir "$OUT" "$@"

echo
echo "analyze: $(command -v python3)"
python3 tests/render/analyze_renders.py --outdir "$OUT" --max-shape-thdn-db -50
