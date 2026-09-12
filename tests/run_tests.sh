#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# Run the synthtools test suite under every interpreter available.
#
# There is no pytest here on purpose: the library targets CircuitPython, so
# the tests are plain scripts that exit non-zero on failure and can run on
# a bare MicroPython too.
#
#   sh tests/run_tests.sh
#
# CPython gives real numpy, so it is the tier that means anything numerically.
# MicroPython uses the pure-Python ulab fallback and is the tier that catches
# portability bugs.

cd "$(dirname "$0")/.." || exit 1

status=0

run() {
    interp="$1"
    file="$2"
    printf '\n=== %s %s ===\n' "$interp" "$file"
    if "$interp" "$file"; then
        :
    else
        echo "FAILED: $interp $file"
        status=1
    fi
}

if command -v python3 >/dev/null 2>&1; then
    run python3 tests/test_patch.py
    run python3 tests/test_env_shapes.py
    run python3 tests/test_wiring.py
    run python3 tests/test_fm_synth.py
    run python3 tests/test_swarm_synth.py
    run python3 tests/test_mono.py
    run python3 tests/test_audio_fx.py
    run python3 tests/test_arpeggiator.py
    run python3 tests/test_trig_sequencer.py
    run python3 tests/test_paramset.py
    run python3 tests/test_param_scaler.py
    run python3 tests/test_harmony.py
else
    echo "python3 not found, skipping the CPython tier"
    status=1
fi

if command -v micropython >/dev/null 2>&1; then
    run micropython tests/test_patch.py
    run micropython tests/test_env_shapes.py
    run micropython tests/test_wiring.py
    run micropython tests/test_fm_synth.py
    run micropython tests/test_swarm_synth.py
    run micropython tests/test_mono.py
    run micropython tests/test_audio_fx.py
    run micropython tests/test_arpeggiator.py
    run micropython tests/test_trig_sequencer.py
    run micropython tests/test_paramset.py
    run micropython tests/test_param_scaler.py
    run micropython tests/test_harmony.py
else
    printf '\nmicropython not found, skipping the portability tier.\n'
    printf 'Install it to catch the MicroPython-only bugs: brew install micropython\n'
fi

printf '\n'
if [ "$status" -eq 0 ]; then
    echo "ALL PASSED"
else
    echo "SOME TESTS FAILED"
fi
exit "$status"
