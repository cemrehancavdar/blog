---
title: "pip install ziglang"
date: 2026-03-05T20:00:00
type: post
tags: [python, cython, zig, c, compiler, build]
draft: false
subtitle: "to compile cython anywhere"
description: "Someone opened a PR on my Cython project. Closed it because the cloud environment didn't have gcc. That sent me down a rabbit hole: zig as a Python dependency, flag filtering, and compiler flags I never wanted to know about."
---

I built <a href="https://github.com/cemrehancavdar/marimo-cython" target="_blank">marimo-cython</a>, Cython inside <a href="https://marimo.io" target="_blank">marimo</a> notebooks. A few days later, <a href="https://github.com/koaning" target="_blank">Vincent Warmerdam</a> (one of my favorite YouTubers, he runs <a href="https://www.youtube.com/@calmcode-io" target="_blank">calmcode</a>) opened <a href="https://github.com/cemrehancavdar/marimo-cython/pull/1" target="_blank">a PR</a> to add a "Open in molab" badge. molab is marimo's <a href="https://molab.marimo.io" target="_blank">cloud notebook platform</a>.

Then he closed his own PR:

> Ah wait, nevermind, it seems we don't have gcc on molab containers by default.

Right. Cython compiles Python to C, then you need a C compiler to turn that C into a `.so` file. No gcc, no Cython. The whole point of marimo-cython (write Cython in a notebook and run it) doesn't work if the environment can't compile C.

---

## The idea

<a href="https://ziglang.org/" target="_blank">Zig</a> is a systems programming language, but the important part for this story is that it ships with a full C/C++ compiler toolchain built on Clang/LLVM. And the <a href="https://pypi.org/project/ziglang/" target="_blank">`ziglang`</a> PyPI package bundles the entire Zig binary distribution.

```
uv add ziglang
uv run python-zig cc --version
# clang version 20.1.2
```

A C compiler. As a Python dependency. Installed with `uv add`. Lives in the venv. No system packages, no Xcode, no `apt install build-essential`.

So the plan was simple: add `ziglang` as a dependency, set `CC="python-zig cc"`, and the molab notebook compiles Cython extensions without gcc. Should take about 20 minutes.

---

## Fixing the lightbulb

There's <a href="https://www.youtube.com/watch?v=5W4NFcamRhM" target="_blank">a scene in Malcolm in the Middle</a> where Hal goes to fix a lightbulb, but the shelf is in the way, so he has to fix the shelf, but the screw is stripped, so he needs to get a new one, but the drawer is broken, and so on, each fix revealing the next problem. That's what happened.

**Step 1: just use `zig cc` directly**

```
CC="python-zig cc" uv run python setup.py build_ext --inplace
```

Crash. On macOS, Python's build system passes `-bundle` to the linker. `zig cc` silently ignores it and produces an executable instead of a shared library. It also passes `-LModules/_hacl`, a relative path baked into `sysconfig` from CPython's own build. Apple's clang ignores the missing directory. `zig cc` does not. And `-Wl,-headerpad,0x40` crashes the zig 0.15.x linker outright.

OK, so raw `zig cc` doesn't work. Surely someone's solved this.

**Step 2: find `zigcc` on PyPI**

There's a package called <a href="https://pypi.org/project/zigcc/" target="_blank">`zigcc`</a>, a wrapper that filters out problematic flags. Exactly what I need.

Except it's archived. And it has a bug: it drops any argument *containing* the substring `-x`. On Linux x86_64, the output path often includes `linux-x86_64`, which matches. So `zigcc` drops the output file argument and the build silently produces nothing.

OK, I'll write my own.

**Step 3: write a wrapper, fix macOS**

Started with the `-bundle` problem: rewrite it to `-shared`, same output format Python expects. Build runs further. Now `-LModules/_hacl` crashes it, drop it. Now `-Wl,-headerpad,0x40` crashes it.

Is `-headerpad` safe to drop? I built the same extension with Apple ld (which honors the flag) and with zig ld (which doesn't). Compared the Mach-O headers with `otool -l`:

```
# Apple ld
sizeofcmds 1576

# zig ld
sizeofcmds 1576
```

Identical. The flag does nothing in practice for Python extensions. Drop it.

macOS works.

**Step 4: try Linux, try OpenMP**

Linux had its own set of flags (`-Wl,--exclude-libs`, `-Wl,-Bsymbolic-functions`) none of which zig's linker supports. More drops, more checking whether the drops are safe. They are, for normal extension builds. Linux works too.

I packaged the whole thing as <a href="https://pypi.org/project/zig-cc-python/" target="_blank">`zig-cc-python`</a>.

Then I tried OpenMP. Worked on Linux. On macOS, `prange` loops silently returned wrong results. zig cc compiled the code without actually emitting the parallel runtime calls. No fix. Moved on.

---

## The payoff

Eight flags. The entire wrapper is ~80 lines of Python. That's what took days. It's harder when you're not sure you know what you're doing.

The <a href="https://github.com/cemrehancavdar/marimo-cython/pull/1" target="_blank">PR</a> that started this works now. Here's <a href="https://molab.marimo.io/notebooks/nb_4AMe9xM8Pxp5sLnxHk6mwo" target="_blank">a marimo notebook compiling Cython on molab</a>, no gcc, no system compiler, just Python packages.

---

## What I learned

A C compiler is a huge piece of machinery. Swapping one in isn't like swapping a JSON library. The build system, the platform linker, and decades of accumulated flags all assume a specific compiler. I got basic Cython extensions working, but that's a narrow slice. I couldn't get OpenMP to work on macOS. I haven't tested C++ heavily, or cross-compilation, or extensions that link against system libraries in unusual ways. There are probably flags I haven't hit yet.

The wrapper is <a href="https://pypi.org/project/zig-cc-python/" target="_blank">on PyPI</a> and <a href="https://github.com/cemrehancavdar/zig-cc-python" target="_blank">on GitHub</a>. Some findings and a thin wrapper to save the next person from the same debugging. If you hit something it doesn't handle, <a href="https://github.com/cemrehancavdar/zig-cc-python/issues" target="_blank">open an issue</a>.

Oh, and while I was deep in linker flags and `otool` output, Vincent asked the marimo engineers to just <a href="https://github.com/cemrehancavdar/marimo-cython/pull/1#issuecomment-4003847281" target="_blank">add gcc to the molab containers</a>. The original notebook already works now.

I know <a href="https://youtu.be/5W4NFcamRhM?si=WnGo_XEfuLJ_bWAU&t=38" target="_blank">what this looks like</a>.
