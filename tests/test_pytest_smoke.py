# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""One real pytest item.

The shared Adafruit CI build action runs bare `python -m pytest`
whenever a tests/ directory exists, with no way to opt out. conftest.py
excludes the paths that were never meant to be pytest-collected
(examples/, tests/hw/), but pytest itself exits 5 ("no tests were
collected") if that leaves nothing to run -- so this file exists purely
to give it one real, passing item.

This project's actual test suite is plain scripts run via
`sh tests/run_tests.sh`; see tests/README.md. paramset.py is the one
module confirmed to need nothing but the stdlib (see CLAUDE.md), so it's
the only part of this package pytest can import without a synthio/ulab
stub -- everything else pulls in synth.py, which imports synthio.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "synthtools"))

from paramset import Param, ParamSet  # noqa: E402


def test_param_knob_to_val():
    p = Param("cutoff", 8000, 0, 9000, "%4d", "filt_frequency")
    assert p.knob_to_val(0.0) == 0
    assert p.knob_to_val(1.0) == 9000
    assert p.span == 9000


def test_paramset_json_round_trip():
    params = [
        Param("cutoff", 8000, 0, 9000, "%4d", "filt_frequency"),
        Param("envmod", 0.5, 0.0, 1.0, "%.2f", "filt_env_depth"),
    ]
    param_set = ParamSet(params, num_knobs=1)
    reloaded = ParamSet.load(ParamSet.dump(param_set))
    assert [p.name for p in reloaded] == [p.name for p in params]
    assert [p.val for p in reloaded] == [p.val for p in params]
