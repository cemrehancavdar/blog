---
title: "pip install ziglang"
date: 2026-03-05T20:00:00
type: post
tags: [python, cython, zig, c, compiler, build]
draft: true
subtitle: "the C compiler you already have"
description: "You can pip install ziglang and immediately use zig cc as a drop-in C compiler. No Xcode CLT version hell, no MSVC setup, no toolchain hunting. Here's how to use it to compile Cython extensions — and any other C project."
---

You need a C compiler. You're on Python. The usual path is: install Xcode Command Line Tools on Mac, hope the version matches what your package expects, fight it for 20 minutes, maybe succeed.

There's a shorter path: `pip install ziglang`.

---

## What's in the box

<a href="https://ziglang.org/" target="_blank">Zig</a> is a systems programming language, but it ships with a full C/C++ compiler toolchain — `zig cc` and `zig c++` — built on Clang/LLVM. The Python package <a href="https://pypi.org/project/ziglang/" target="_blank">`ziglang`</a> bundles the entire Zig binary distribution. When you install it, you get `zig` on your PATH via a thin wrapper.

```
pip install ziglang
zig version
# 0.14.0
```

That's it. No system dependencies. No Xcode. No MSVC. Works on macOS, Linux, and Windows. Works inside virtualenvs and Docker containers with no extra setup.

`zig cc` is a full Clang frontend. It compiles C and C++ to native machine code, handles preprocessor directives, links object files — everything you'd expect from `gcc` or `clang`. The only difference is you got it from PyPI.

---

## Compiling a Cython extension

Cython translates `.pyx` files into C, then expects you to compile that C into a shared library. The normal path goes through `setuptools` and whatever system compiler `distutils` finds. The `zig cc` path is more direct.

Take any Cython file. Here's a minimal one:

```python
# fast_math.pyx
def add(double a, double b) -> double:
    return a + b
```

**Step 1: Translate to C**

```bash
pip install cython
cython fast_math.pyx --output-file fast_math.c
```

**Step 2: Compile with zig cc**

You need two things: the Python include path and the right flags for a shared library.

```bash
# get the include path
python -c "import sysconfig; print(sysconfig.get_path('include'))"
# /path/to/your/python/include/python3.13
```

Then compile:

```bash
zig cc fast_math.c \
  -I$(python -c "import sysconfig; print(sysconfig.get_path('include'))") \
  -shared \
  -fPIC \
  -O2 \
  -o fast_math.so
```

**Step 3: Import it**

```python
import fast_math
print(fast_math.add(1.0, 2.0))  # 3.0
```

No `setup.py`. No `pyproject.toml`. No `python setup.py build_ext --inplace`. Just `zig cc` → `.so` → `import`.

---

## The setup.py path (when you want it)

If you're shipping a package or want to integrate with the normal Python build ecosystem, you can tell `setuptools` to use `zig cc` as the compiler:

```python
# setup.py
from setuptools import setup
from Cython.Build import cythonize

setup(
    name="fast_math",
    ext_modules=cythonize("fast_math.pyx"),
)
```

```bash
CC="zig cc" CXX="zig c++" python setup.py build_ext --inplace
```

The `CC` and `CXX` environment variables tell `distutils`/`setuptools` which compiler to invoke. `zig cc` accepts the same flags as `gcc`/`clang`, so it drops in without any changes to your build config.

---

## Any C project

This isn't Cython-specific. `zig cc` is a general C compiler. If you have a C project — a native extension, a small CLI tool, a library — the workflow is the same:

```bash
pip install ziglang
zig cc myfile.c -o myprogram
```

Or for a shared library:

```bash
zig cc mylib.c -shared -fPIC -o mylib.so
```

Cross-compilation is where `zig cc` gets genuinely unusual. You can target a different platform from your current machine:

```bash
# compile for Linux aarch64, from any host
zig cc -target aarch64-linux-musl myfile.c -o myfile-linux-arm64
```

That's something `gcc` and `clang` require separate toolchain installs to do. `zig cc` includes all targets in the single binary you got from PyPI.

---

## Why this matters in Python projects

The most common reason you need a C compiler in a Python project is native extensions — and Cython is the most common way to write them. The usual developer setup story for a Cython project is:

- macOS: install Xcode CLT (2GB download), pray the SDK version matches
- Linux: `apt install gcc` (fine, but not in every container)
- Windows: install Visual Studio Build Tools (multi-GB, confusing installer)

With `ziglang` in your `pyproject.toml` dev dependencies, the story becomes:

```
uv add --dev ziglang cython
CC="zig cc" python setup.py build_ext --inplace
```

Same command on every platform. No system compiler required. CI containers don't need `apt install build-essential`. Docker images stay smaller.

---

## Caveats

**It's not a system linker.** `zig cc` handles compilation and linking for self-contained binaries well, but complex link setups — system frameworks on macOS, intricate `.so` versioning — can hit edge cases. For simple extensions it works without issues.

**The `ziglang` PyPI package lags Zig releases slightly.** Check <a href="https://pypi.org/project/ziglang/#history" target="_blank">the release history</a> if you need a specific version.

**On macOS, you may still need the SDK headers for system libraries.** If your C code includes `<sys/types.h>` or other OS headers, those come from the macOS SDK, not from Zig. `zig cc` bundles libc headers but not the full Apple SDK. For Python extension compilation this is usually fine — the Python headers are what matters, and you get those from your Python install.

---

## The one-liner

```bash
pip install ziglang cython && cython mymodule.pyx && \
  zig cc mymodule.c \
    -I$(python -c "import sysconfig; print(sysconfig.get_path('include'))") \
    -shared -fPIC -O2 -o mymodule.so
```

A full Cython compilation pipeline, no system compiler required, from a single `pip install`.
