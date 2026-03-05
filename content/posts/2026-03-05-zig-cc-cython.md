---
title: "pip install ziglang"
date: 2026-03-05T20:00:00
type: post
tags: [python, cython, zig, c, compiler, build]
draft: true
subtitle: "the C compiler you already have"
description: "You can pip install ziglang and immediately use it as a drop-in C compiler. No Xcode CLT version hell, no MSVC setup, no toolchain hunting. Here's how to use it to compile Cython extensions — and any other C project."
---

You need a C compiler. You're on Python. The usual path is: install Xcode Command Line Tools on Mac, hope the version matches what your package expects, fight it for 20 minutes, maybe succeed.

There's a shorter path: `pip install ziglang`.

---

## What's in the box

<a href="https://ziglang.org/" target="_blank">Zig</a> is a systems programming language, but it ships with a full C/C++ compiler toolchain built on Clang/LLVM. The Python package <a href="https://pypi.org/project/ziglang/" target="_blank">`ziglang`</a> bundles the entire Zig binary distribution. When you install it, the compiler is available as `python-zig` (not `zig` — more on that in a moment).

```
pip install ziglang
python-zig version
# 0.15.2
python-zig cc --version
# clang version 20.1.2
```

No system dependencies. No Xcode. No MSVC. Works on macOS, Linux, and Windows. Works inside virtualenvs and Docker containers with no extra setup.

`python-zig cc` is a full Clang frontend. It compiles C and C++ to native machine code, handles preprocessor directives, links object files — everything you'd expect from `gcc` or `clang`.

> **Why `python-zig` and not `zig`?** The `ziglang` PyPI package installs under the name `python-zig` to avoid colliding with a system-installed `zig` binary. If you want `zig` on your PATH, symlink it or use the system install.

---

## Compiling a Cython extension

Cython translates `.pyx` files into C, then expects you to compile that C into a shared library. Here's the full path using `python-zig cc`.

Take any Cython file:

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

**Step 2: Compile with python-zig cc**

You need the Python include path and the right flags for a shared library. On macOS, there's one extra required flag: `-undefined dynamic_lookup`. Python extensions are loaded dynamically — the Python symbols are resolved at load time by the interpreter, not at link time. Without this flag, the linker errors out on every single `_PyDict_New`, `_PyErr_SetString`, etc.

```bash
python-zig cc fast_math.c \
  -I$(python -c "import sysconfig; print(sysconfig.get_path('include'))") \
  -shared \
  -fPIC \
  -O2 \
  -undefined dynamic_lookup \
  -o fast_math.so
```

On Linux, `-undefined dynamic_lookup` is not needed — the linker handles it differently. The macOS requirement is a platform quirk, not a zig quirk; the same flag is required with `clang` or `gcc`.

**Step 3: Import it**

```python
import fast_math
print(fast_math.add(1.0, 2.0))  # 3.0
```

---

## The setup.py path — use zigcc instead

If you try `CC="python-zig cc" python setup.py build_ext --inplace`, you'll hit a crash. setuptools passes `-LModules/_hacl` (a relative path artifact from CPython's own build) to the linker, and `python-zig cc` segfaults on it.

This is a known class of problem with `zig cc` in real build systems — it doesn't silently ignore flags it doesn't understand, so stale or irrelevant linker args passed by `setuptools`/`cmake`/`cargo` cause failures.

That's exactly what <a href="https://pypi.org/project/zigcc/" target="_blank">`zigcc`</a> was built to solve. It's a thin Python wrapper that filters out problematic flags before passing them to `zig cc`:

```bash
pip install ziglang zigcc
```

Now the `CC=` path works:

```bash
CC="zigcc" CXX="zigcxx" python setup.py build_ext --inplace
```

`zigcc` maintains a blacklist of flags that are known to cause `zig cc` to fail — things like `-Wl,-dylib`, relative library paths, and flags with no zig equivalent. It also handles target triple conversion for cross-compilation with Rust and Go. Think of `ziglang` as the engine and `zigcc` as the adapter that makes it fit real build systems.

---

## Any C project

This isn't Cython-specific. For any C project:

```bash
pip install ziglang
python-zig cc myfile.c -o myprogram
```

Cross-compilation is where zig gets genuinely unusual. You can target a different platform from your current machine:

```bash
# compile for Linux x86_64, from macOS arm64
python-zig cc -target x86_64-linux-musl myfile.c -o myfile-linux-x64
```

That's something `gcc` and `clang` require separate toolchain installs to do. The entire target library is bundled in the single binary you got from PyPI.

---

## Why this matters in Python projects

The most common reason you need a C compiler in a Python project is native extensions — and Cython is the most common way to write them. The usual developer setup story for a Cython project is:

- macOS: install Xcode CLT (2GB download), pray the SDK version matches
- Linux: `apt install gcc` (fine, but not in every container)
- Windows: install Visual Studio Build Tools (multi-GB, confusing installer)

With `ziglang` and `zigcc` as dev dependencies, the story becomes the same command on every platform — no system compiler required, CI containers don't need `apt install build-essential`, Docker images stay smaller.

---

## Caveats worth knowing

**`ziglang` installs as `python-zig`, not `zig`.** This is intentional to avoid shadowing system installs. `zigcc` calls `zig` from PATH, so if you use `zigcc` you need either system zig or to have `python-zig` symlinked/aliased to `zig`.

**`zigcc` is a flag-filtering wrapper, not a bundler.** It depends on `zig` being on PATH separately. The two packages solve different problems: `ziglang` gives you the binary, `zigcc` makes it compatible with messy build systems.

**On macOS, `-undefined dynamic_lookup` is required for Python extensions.** This isn't zig-specific — it's how all Python extensions are linked on macOS. The manual `python-zig cc` command in this post includes it; `zigcc` + setuptools handles it automatically via the platform's distutils config.

**The `ziglang` PyPI package lags Zig releases slightly.** Check <a href="https://pypi.org/project/ziglang/#history" target="_blank">the release history</a> if you need a specific version.
