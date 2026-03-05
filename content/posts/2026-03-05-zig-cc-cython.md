---
title: "pip install ziglang"
date: 2026-03-05T20:00:00
type: post
tags: [python, cython, zig, c, compiler, build]
draft: true
subtitle: "the C compiler you already have"
description: "You can uv add ziglang and immediately use it as a drop-in C compiler. No Xcode CLT version hell, no MSVC setup, no toolchain hunting. Here's how to use it to compile Cython extensions — and what that compilation pipeline actually looks like."
---

You need a C compiler. You're on Python. The usual path is: install Xcode Command Line Tools on Mac, hope the version matches what your package expects, fight it for 20 minutes, maybe succeed.

There's a shorter path: `uv add ziglang`.

---

## What's in the box

<a href="https://ziglang.org/" target="_blank">Zig</a> is a systems programming language, but it ships with a full C/C++ compiler toolchain built on Clang/LLVM. The Python package <a href="https://pypi.org/project/ziglang/" target="_blank">`ziglang`</a> bundles the entire Zig binary distribution. When you install it, the compiler is available as `python-zig`.

```
uv add ziglang
uv run python-zig version
# 0.15.2
uv run python-zig cc --version
# clang version 20.1.2
```

No system dependencies. No Xcode. No MSVC. Works on macOS, Linux, and Windows. Works inside virtualenvs and Docker containers with no extra setup.

> **Why `python-zig` and not `zig`?** The `ziglang` PyPI package installs under the name `python-zig` to avoid colliding with a system-installed `zig` binary.

---

## Cython's compilation pipeline

Cython is a compiler, not an interpreter. It takes `.pyx` files — Python with optional static type annotations — and produces native C extension modules. Understanding the pipeline is the key to understanding where `python-zig cc` fits.

```
fast_math.pyx
     │
     │  cython (transpiler)
     ▼
fast_math.c          ← generated C, ~2000 lines for a trivial file
     │
     │  C compiler (gcc / clang / python-zig cc)
     ▼
fast_math.so         ← shared library, loadable by Python
     │
     │  import fast_math
     ▼
Python module
```

The Cython transpiler step is pure Python — no compiler needed. The C compiler step is where you normally need a system toolchain. That's the step `python-zig cc` replaces.

### What Cython actually does to your code

The more type information you give Cython, the less it has to go through the Python object system. Here's the same function at three levels:

```python
# Level 1: plain Python function — Cython compiles this but gets no speedup
def add(a, b):
    return a + b
```

```python
# Level 2: typed arguments — Cython generates direct C arithmetic, no PyObject overhead
def add(double a, double b) -> double:
    return a + b
```

```python
# Level 3: cdef function — not callable from Python, pure C calling convention
cdef double add(double a, double b):
    return a + b
```

Level 2 is the sweet spot for extension modules: callable from Python, but the hot path runs as C. The generated C for level 2 looks roughly like this (simplified):

```c
static PyObject *__pyx_pw_9fast_math_1add(PyObject *self, PyObject *args) {
    double a, b;
    // unpack Python args into C doubles
    if (!PyArg_ParseTuple(args, "dd", &a, &b)) return NULL;
    // the actual computation: pure C, no Python overhead
    double result = a + b;
    // box the result back into a Python float
    return PyFloat_FromDouble(result);
}
```

The argument unpacking and result boxing happen once per call. The computation itself — `a + b` — is a single CPU instruction. That's the Cython deal: you pay Python overhead at the boundary, you pay nothing inside.

A more realistic example with a tight loop — the kind Cython is actually for:

```python
# nbody_step.pyx
import cython
from libc.math cimport sqrt

@cython.boundscheck(False)
@cython.wraparound(False)
def advance(double dt, int n,
            double[:, :] pos,    # typed memoryview — direct C array access
            double[:, :] vel,
            double[:] mass):
    cdef int i, j
    cdef double dx, dy, dz, dist, mag

    for i in range(n):
        for j in range(i + 1, n):
            dx = pos[i, 0] - pos[j, 0]
            dy = pos[i, 1] - pos[j, 1]
            dz = pos[i, 2] - pos[j, 2]
            dist = sqrt(dx*dx + dy*dy + dz*dz)
            mag = dt / (dist * dist * dist)

            vel[i, 0] -= dx * mass[j] * mag
            vel[j, 0] += dx * mass[i] * mag
            # ...
```

`cdef` variables are C locals. `double[:, :]` is a typed memoryview — Cython accesses it as a raw C pointer, no `PyObject_GetItem` calls. `from libc.math cimport sqrt` links to C's `sqrt` directly, skipping Python's `math.sqrt` dispatch. This is the code that gets ~90x over CPython.

---

## Compiling it with python-zig cc

**Step 1: Translate to C**

```bash
uv add cython ziglang
uv run cython nbody_step.pyx --output-file nbody_step.c
```

The `--annotate` flag is worth knowing: `uv run cython nbody_step.pyx --annotate` produces an HTML file highlighting every line by how much Python overhead remains. Yellow lines call into the Python C API. White lines are pure C. If your hot loop is yellow, you're leaving performance on the table.

**Step 2: Compile with python-zig cc**

```bash
uv run python-zig cc nbody_step.c \
  -I$(uv run python -c "import sysconfig; print(sysconfig.get_path('include'))") \
  -shared \
  -fPIC \
  -O2 \
  -undefined dynamic_lookup \
  -o nbody_step.so
```

Flags explained:
- `-I$(...)` — Python's header files (`Python.h`, `numpy/arrayobject.h`, etc.)
- `-shared -fPIC` — produce a shared library, not an executable
- `-O2` — optimization level; Cython's generated C benefits significantly from this
- `-undefined dynamic_lookup` — macOS only: Python symbols resolve at load time, not link time. On Linux this flag is not needed.

**Step 3: Import it**

```python
import numpy as np
import nbody_step

pos = np.array([[...]], dtype=np.float64)
vel = np.array([[...]], dtype=np.float64)
mass = np.array([...], dtype=np.float64)

nbody_step.advance(0.01, len(mass), pos, vel, mass)
```

No `setup.py`. No `pyproject.toml`. No `python setup.py build_ext --inplace`. Cython to C to `.so` in two commands.

---

## The pyproject.toml path — use zigcc

For a real package you want a proper build, and you want `CC=` to work. If you try `CC="python-zig cc"`, setuptools passes `-LModules/_hacl` (a relative path from CPython's own build) to the linker and `python-zig cc` segfaults on it.

This is a known class of problem: `zig cc` doesn't silently ignore flags it doesn't understand. <a href="https://pypi.org/project/zigcc/" target="_blank">`zigcc`</a> is a thin wrapper that filters them out:

```bash
uv add --dev ziglang zigcc
```

```toml
# pyproject.toml
[build-system]
requires = ["setuptools", "cython"]
build-backend = "setuptools.backends.legacy:build"

[tool.setuptools.ext-modules]
# setuptools picks up Extension objects from setup.py
```

```python
# setup.py
from setuptools import setup
from Cython.Build import cythonize

setup(ext_modules=cythonize("nbody_step.pyx", compiler_directives={
    "boundscheck": False,
    "wraparound": False,
    "cdivision": True,
}))
```

```bash
CC="zigcc" CXX="zigcxx" uv run python setup.py build_ext --inplace
```

`zigcc` blacklists the problematic flags and passes everything else through to `zig cc`. The `compiler_directives` in `cythonize()` are worth setting for production: `boundscheck=False` removes array index checks, `wraparound=False` removes negative index handling, `cdivision=True` uses C division semantics — together they can double the speed of tight loops.

---

## Why this matters

The usual developer setup story for a Cython project:

- macOS: install Xcode CLT (2GB), pray the SDK version matches your Python build
- Linux: `apt install gcc python3-dev` (manageable, but not in every container)
- Windows: install Visual Studio Build Tools (multi-GB, confusing installer)

With `ziglang` and `zigcc` as dev dependencies, the story is `uv sync` on every platform. No system compiler. CI containers don't need `apt install build-essential`. The build is reproducible across machines because the compiler version is pinned in `uv.lock`.

---

## Caveats

**`ziglang` installs as `python-zig`, not `zig`.** `zigcc` calls `zig` from PATH, so pairing them requires either system zig or a `python-zig` alias.

**`zigcc` is a flag-filtering wrapper, not a bundler.** `ziglang` gives you the binary. `zigcc` makes it compatible with real build systems. They solve different problems.

**On macOS, `-undefined dynamic_lookup` is required for Python extensions.** Not a zig quirk — the same flag is required with `clang`. `zigcc` + setuptools handles it automatically. The manual `python-zig cc` command requires it explicitly.

**If your Cython extension uses NumPy, add the NumPy include path:**

```bash
uv run python-zig cc nbody_step.c \
  -I$(uv run python -c "import sysconfig; print(sysconfig.get_path('include'))") \
  -I$(uv run python -c "import numpy; print(numpy.get_include())") \
  -shared -fPIC -O2 -undefined dynamic_lookup \
  -o nbody_step.so
```
