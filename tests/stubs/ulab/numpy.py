# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
"""ulab.numpy stub.

Two backends, picked automatically:

* **CPython** hands off to real numpy. That gives genuine float and int16
  semantics, which is what the numeric tests need.
  section 9 says to use real numpy for numeric questions, and that is how
  the int16 lerp overflow in section 8 was pinned down.

* **MicroPython** has no numpy, so we fall back to a small pure-Python
  wrapper implementing just the surface synthlib/waves.py uses. This is
  the tier that catches the portability class of bug

A ``list`` subclass does NOT work as the array type: MicroPython's
``list.__setitem__`` rejects a non-list right-hand side, so ``buf[:n] =
other_array`` fails. Hence the wrapper class below.

Known difference between the backends: real numpy silently *wraps* an
out-of-range int16 store, while ulab raises OverflowError. The fallback
raises, matching ulab. Tests therefore assert ranges explicitly rather
than relying on either behaviour.
"""

try:  # CPython
    from numpy import (  # noqa: F401
        array, zeros, ones, linspace, concatenate, sin, pi, frombuffer, int16,
    )
    BACKEND = "numpy"

except ImportError:  # MicroPython
    import math

    BACKEND = "pure"
    pi = math.pi

    class _DType:
        def __init__(self, name, lo=None, hi=None):
            self.name = name
            self.lo = lo
            self.hi = hi

        def __repr__(self):
            return self.name

    int16 = _DType("int16", -32768, 32767)
    float_ = _DType("float")

    def _values(x):
        if isinstance(x, ndarray):
            return x._d
        if isinstance(x, (list, tuple)):
            return list(x)
        return None

    class ndarray:
        """Minimal 1-D array: indexing, slice assignment, elementwise math."""

        def __init__(self, vals, dtype=None):
            self.dtype = dtype
            self._d = [self._cast(v) for v in vals]

        def _cast(self, v):
            d = self.dtype
            if d is not None and d.lo is not None:
                v = int(v)
                if v < d.lo or v > d.hi:
                    # ulab's behaviour, and the section 8 symptom
                    raise OverflowError("value must fit in 2 byte(s)")
                return v
            return float(v)

        def __len__(self):
            return len(self._d)

        def __iter__(self):
            return iter(self._d)

        def __getitem__(self, i):
            if isinstance(i, slice):
                return ndarray(self._d[i], self.dtype)
            return self._d[i]

        def __setitem__(self, i, v):
            vals = _values(v)
            if isinstance(i, slice):
                if vals is None:                     # scalar broadcast
                    idx = range(*i.indices(len(self._d)))
                    vals = [v] * len(idx)
                span = range(*i.indices(len(self._d)))
                if len(vals) != len(span):
                    raise ValueError("shape mismatch in slice assignment")
                for n, pos in enumerate(span):
                    self._d[pos] = self._cast(vals[n])
            else:
                self._d[i] = self._cast(v)

        def _binop(self, other, op):
            vals = _values(other)
            if vals is None:
                out = [op(a, other) for a in self._d]
            else:
                if len(vals) != len(self._d):
                    raise ValueError("shape mismatch")
                out = [op(a, b) for a, b in zip(self._d, vals)]
            return ndarray(out)          # arithmetic always widens to float

        def __mul__(self, o):
            return self._binop(o, lambda a, b: a * b)

        def __rmul__(self, o):
            return self.__mul__(o)

        def __add__(self, o):
            return self._binop(o, lambda a, b: a + b)

        def __radd__(self, o):
            return self.__add__(o)

        def __sub__(self, o):
            return self._binop(o, lambda a, b: a - b)

        def __repr__(self):
            return "array(%r, dtype=%s)" % (self._d, self.dtype)

    def array(vals, dtype=None):
        return ndarray(_values(vals) or list(vals), dtype)

    def zeros(n, dtype=None):
        return ndarray([0] * n, dtype)

    def ones(n, dtype=None):
        return ndarray([1] * n, dtype)

    def linspace(start, stop, num=50, dtype=None, endpoint=True):
        if num <= 0:
            return ndarray([], dtype)
        if num == 1:
            return ndarray([start], dtype)
        div = (num - 1) if endpoint else num
        step = (stop - start) / div
        out = [start + step * i for i in range(num)]
        if endpoint:
            out[-1] = stop        # exact, like numpy: float error must not creep in
        return ndarray(out, dtype)

    def concatenate(parts, dtype=None):
        out = []
        for p in parts:
            out.extend(_values(p))
        return ndarray(out, dtype or getattr(parts[0], "dtype", None))

    def sin(x):
        return ndarray([math.sin(v) for v in _values(x)])

    def frombuffer(buf, dtype=None):
        raise NotImplementedError("frombuffer: wavetable tests need real numpy")
