# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# This project has no pytest suite -- see tests/README.md. The real tests
# are plain scripts run via `sh tests/run_tests.sh`, deliberately runnable
# under a bare MicroPython too, which is incompatible with how pytest
# collects and executes test modules.
#
# The shared Adafruit CI build action runs bare `python -m pytest`
# whenever a tests/ directory exists at all, with no way to opt out or
# scope it -- so without this file, pytest recursively discovers and
# tries to *import* every test_*.py / *_test.py file in the whole repo:
#   - examples/*_test.py expect to be copied flat onto a CIRCUITPY drive
#     alongside their sibling modules, not run from this tree.
#   - tests/hw/test_device.py needs a real synthio -- it only runs on
#     actual hardware (see tests/README.md).
collect_ignore_glob = ["examples/*", "tests/hw/*"]
