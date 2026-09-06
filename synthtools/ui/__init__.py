# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""
`synthtools.ui`
================================================================================

Front-panel helpers: knob takeover and a bar-graph display for boards with
two pots and a small screen.

Importing
---------

Lazy, for the same reason the top-level package is: ``GaugeCluster`` needs
``displayio`` and ``vectorio``, and a program that only wants
``ParamScaler`` should not pay for them. ``from synthtools.ui import
ParamScaler`` imports ``synthtools.ui.param_scaler`` and nothing else.

Do not re-export eagerly here. See the note in ``synthtools/__init__.py``:
measured on an rp2040, eager re-exports cost 52,784 bytes against 23,008
lazy, and importing a submodule runs this file either way.

"""

import sys

#: Public name -> the submodule that defines it.
_LAZY = {
    "GaugeCluster": "gauge_cluster",
    "ParamScaler": "param_scaler",
}

__all__ = tuple(sorted(_LAZY))


def __getattr__(name):
    """Import the submodule that defines ``name`` on first access (PEP 562)."""
    modname = _LAZY.get(name)
    if modname is None:
        raise AttributeError(name)
    full = __name__ + "." + modname
    if full not in sys.modules:
        __import__(full)
    return getattr(sys.modules[full], name)
