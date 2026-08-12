#!/bin/sh
# Run the synth_tools test suite under every interpreter available.
#
# There is no pytest here on purpose: the library targets CircuitPython, so
# the tests are plain scripts that exit non-zero on failure and can run on
# a bare MicroPython too.
#
#   sh tests/run_tests.sh
#
# CPython gives real numpy, so it is the tier that means anything numerically.
# MicroPython uses the pure-Python ulab fallback and is the tier that catches
# the portability bugs in CLAUDE-synthlib.md section 7.

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
    run python3 tests/test_arpeggiator.py
else
    echo "python3 not found, skipping the CPython tier"
    status=1
fi

if command -v micropython >/dev/null 2>&1; then
    run micropython tests/test_patch.py
    run micropython tests/test_env_shapes.py
    run micropython tests/test_wiring.py
    run micropython tests/test_arpeggiator.py
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
