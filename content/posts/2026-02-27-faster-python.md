---
title: "Poor Python, Rich Python"
date: 2026-02-27T20:00:00
type: post
tags: [python, performance, benchmark, cython, rust, numba, numpy, mojo, codon, taichi]
draft: false
subtitle: "what Rich Dad Poor Dad didn't teach you about CPython"
description: "Python loses every public benchmark by 50-600x. I take the exact problems people use to dunk on Python, reproduce them, and climb every rung of the optimization ladder — from CPython version upgrades to Mojo. Real numbers, real code, real developer experience verdicts."
---

Poor Python said *"just write more Python, it's readable and that's what matters."*

Rich Python said *"understand why it's slow, then make it fast."*

This is a story about both. It starts with the exact benchmarks people use to dunk on Python, moves through the three reasons CPython actually is slow, and ends with a ladder of fixes — each rung trading more effort for more speed. I ran every benchmark myself on an Apple M4 Pro. Real code, real numbers, real developer experience verdicts.

The full code is at <a href="https://github.com/cemrehancavdar/faster-python-bench" target="_blank">faster-python-bench on GitHub</a>.

---

## The Report Card

Poor Python doesn't look at benchmarks. Rich Python does.

Every year, someone posts a benchmark showing Python is 100x slower than C, and the same argument plays out: one side says *"benchmarks don't matter, real apps are I/O bound,"* the other says *"just use a real language."* Both are wrong. Here's what the numbers actually say.

**The Computer Language Benchmarks Game** (<a href="https://benchmarksgame-team.pages.debian.net/benchmarksgame/" target="_blank">benchmarksgame</a>) — the oldest and most cited. CPython 3.13 on the official run:

<div class="bench-table">

| Benchmark | C gcc | CPython 3.13 | Ratio |
|---|---|---|---|
| n-body (50M) | 2.1s | 372s | **177x** |
| spectral-norm (5500) | 0.4s | 350s | **875x** |
| fannkuch-redux (12) | 2.1s | 311s | **148x** |
| mandelbrot (16000) | 0.9s | 183s | **203x** |
| binary-trees (21) | 1.0s | 33s | **33x** |

</div>

Poor Python sees these numbers and says *"benchmarks don't matter."*

Rich Python says *"let me understand why, and let me take those exact benchmarks and fix them."*

So that's what I did. I took two of the most-cited Benchmarks Game problems — **n-body** and **spectral-norm** — reproduced them on my machine, and ran every optimization approach I could find. Then I added a third benchmark — a JSON pipeline — to test something closer to real-world code.

---

## Why Python Is Slow

There are exactly three reasons. Everything else is a symptom.

### 1. Interpreted Bytecode

Python compiles `.py` to bytecode, then the CPython VM interprets it one instruction at a time. C and Rust compile to machine code that runs directly on the CPU. A `for` loop in C is a handful of CPU instructions. In Python it's hundreds — fetch bytecode, decode, dispatch to C function, handle the object protocol, update the instruction pointer, repeat. **Every single iteration.**

### 2. Everything Is an Object

In C, an integer is 4 bytes on the stack. In Python, it's a heap-allocated `PyObject`:

```
C int:        [    4 bytes    ]

Python int:   [ ob_refcnt  8B ]    reference count
              [ ob_type    8B ]    pointer to type object
              [ ob_size    8B ]    number of digits
              [ ob_digit   4B ]    the actual value
              ─────────────────
              = 28 bytes minimum
```

A simple `a + b` means: dereference two heap pointers, check both type pointers, dispatch to `int.__add__`, allocate a new `PyObject` for the result, update reference counts for all three objects. Every operation pays this "object tax."

### 3. The GIL

The Global Interpreter Lock means only one thread executes Python bytecode at a time. Your 16-core machine runs Python on one core. CPython 3.13 shipped experimental free-threaded mode (`--disable-gil`), but it's opt-in, breaks C extensions, and — as we'll see — makes single-threaded code slower.

---

## Rich Python's Playbook

### "Don't work harder, upgrade" — CPython Versions

Poor Python is still on 3.10 because *"it works fine."*

Rich Python checks the release notes.

<div class="bench-table">

| Version | N-body | vs 3.13 | Spectral-norm | vs 3.13 |
|---|---|---|---|---|
| CPython 3.10 | 1,672ms | 0.66x | 16,723ms | 0.81x |
| CPython 3.11 | 1,175ms | 0.94x | 13,272ms | 1.02x |
| CPython 3.13 | 1,105ms | 1.0x | 13,499ms | 1.0x |
| CPython 3.14t (free-threaded) | 1,534ms | 0.72x | 14,235ms | 0.95x |

</div>

The big story is **3.10 to 3.11**: a 1.42x speedup on n-body, for free. That's the <a href="https://docs.python.org/3/whatsnew/3.11.html" target="_blank">Faster CPython</a> project. After 3.11, it's a plateau. Free-threaded Python (3.14t) is **24-28% slower** on single-threaded code — the GIL removal adds overhead to every operation. (<a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/cpython-versions.md" target="_blank">Full version comparison</a>)

**Cost: changing your base image. Reward: up to 1.42x (3.10 to 3.11), then nothing.**

---

### "The best investment is free" — PyPy

Poor Python thinks CPython is the only Python.

Rich Python types `pypy3` instead of `python3`.

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.13 | 1,105ms | 13,499ms |
| PyPy | 98ms (**11x**) | 1,065ms (**13x**) |

</div>

PyPy traces your hot loops and generates native machine code. **Zero code changes.** Just a different interpreter. The catch: ecosystem compatibility. You can't use C extensions — numpy, orjson, most of the ML stack — unless they're specifically built for PyPy.

**Cost: switching interpreters. Reward: 11-13x if your code is pure Python.**

---

### "Assets put money in your pocket" — Numba

Poor Python rewrites the whole program.

Rich Python adds one decorator.

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.13 | 1,105ms | 13,499ms |
| Numba @njit | 22ms (**51x**) | 108ms (**125x**) |

</div>

Numba JIT-compiles decorated functions to machine code via LLVM:

```python
@njit(cache=True)
def _advance(dt, n, pos, vel, mass, pairs_i, pairs_j):
    for _ in range(n):
        for k in range(num_pairs):
            dx = pos[pairs_i[k], 0] - pos[pairs_j[k], 0]
            # ... same algorithm, numpy arrays instead of lists
```

One decorator, restructure data into numpy arrays, and you get **51-125x**. The catch: you're locked to numpy arrays and numeric types. Strings, dicts, classes — Numba can't touch them. It's a scalpel, not a saw.

**Cost: `@njit` + numpy arrays. Reward: 51-125x on numeric code.**

---

### "Mind your own business" — Cython

Poor Python writes Python and hopes it's fast enough.

Rich Python writes Python that compiles to C.

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.13 | 1,105ms | 13,499ms |
| Cython | 12ms (**93x**) | 149ms (**91x**) |

</div>

93x on n-body. Within 12% of Rust. But here's the thing Rich Python needs to know:

**Getting to 93x was a journey. My first version got 10.5x.** The difference? Landmines like `** 0.5` routing through Python's `pow()` instead of C's `sqrt()` (5x penalty), or precomputed pair arrays preventing the C compiler from unrolling loops (2x penalty). Nothing warns you. The code works, it's just 9x slower than it should be.

The full Cython story — every landmine and how to avoid them — is in <a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/cython-minefield.md" target="_blank">The Cython Minefield</a>.

**Cost: C knowledge in Python clothing. Reward: 91-93x when you avoid the landmines.**

---

### "The rich don't work for money" — The New Wave

Poor Python stays in the Python ecosystem.

Rich Python evaluates every tool that claims to make Python faster.

Three tools promise to compile Python (or Python-like code) to native machine code: **Codon**, **Mojo**, and **Taichi**. I tested all three.

<div class="bench-table">

| | N-body | Speedup | Spectral-norm | Speedup | The catch |
|---|---|---|---|---|---|
| Codon 0.19 | 47ms | **24x** | 101ms | **134x** | Own runtime, no stdlib, standalone binaries only |
| Mojo nightly | 15ms | **75x** | 116ms | **117x** | New language (pre-1.0), needs pixi, full rewrite required |
| Taichi 1.7 | 16ms | **70x** | 72ms | **187x** | `from __future__ import annotations` silently breaks it |

</div>

The numbers are real. The DX is rough. Codon can't import your existing code. Mojo is a new language wearing Python's clothes. Taichi has the best spectral-norm (187x) but surprising failure modes. None are drop-in. (<a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/new-wave-compilers.md" target="_blank">Full deep dive: code examples, DX verdicts, gotchas</a>)

---

### "Don't let money work against you" — Rust via PyO3

Poor Python rewrites everything in Rust because *"Rust is faster."*

Rich Python knows Rust is only worth it when it **owns the whole pipeline**.

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.13 | 1,105ms | 13,499ms |
| Rust (PyO3) | 10ms (**106x**) | 95ms (**142x**) |

</div>

106-142x. But **on n-body, Cython at 12ms vs Rust at 10ms is only a 1.2x difference**. Both compiled to native machine code. That remaining gap is compiler backend quality, not a fundamental language difference. The real Rust advantage shows on the JSON pipeline — when Rust owns the data flow end-to-end.

**Cost: learning Rust + PyO3. Reward: 106-142x on compute, and the ability to bypass Python's object system end-to-end.**

---

### "It's not about how much you make" — NumPy

Poor Python writes loops.

Rich Python writes one line.

<div class="bench-table">

| | Spectral-norm |
|---|---|
| CPython 3.13 | 13,499ms |
| NumPy | 21ms (**638x**) |

</div>

**638x.** Faster than Rust's 142x. On the same problem.

NumPy pre-computes the matrix once and delegates to BLAS (Apple Accelerate on macOS):

```python
a = build_matrix(n)
for _ in range(10):
    v = a.T @ (a @ u)
    u = a.T @ (a @ v)
```

NumPy beats Rust because it trades O(N) memory for O(N^2) memory — it stores the full 2000x2000 matrix (30MB), but then each matrix-vector multiply is a single call to hand-optimized BLAS with SIMD and multithreading. This is the lesson people miss when they say "Python is slow." Python the loop runner is slow. Python the orchestrator of C/Fortran libraries is as fast as anything.

**Cost: knowing numpy. Reward: 638x on vectorizable math.**

---

## When Benchmarks Meet Real Code

The Benchmarks Game problems are pure compute: tight loops, no I/O, no data structures beyond arrays. Most Python code looks nothing like that. So I built a third benchmark: load 100K JSON events, filter, transform, aggregate per user. Dicts, strings, datetime parsing — the kind of code that makes Numba useless and makes Cython fight the Python object system.

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.13 | 51ms | 1.0x | Nothing |
| Mypyc | 22ms | 2.3x | Type annotations |
| Rust (from JSON, serde) | 23ms | 2.2x | New language + bindings |
| Cython (fully optimized) | 14ms | 3.8x | Days of annotation work |

</div>

The ceiling is much lower. Why? The bottleneck is **Python dict access**, and every tool except Rust still goes through `PyDict_GetItem`. Even Cython's fully optimized version — with `@cython.cclass`, C arrays for counters, `@cython.cfunc` on every helper — still reads input dicts through the Python C API.

**Rust wins when it owns everything.** When Rust parses JSON directly with serde into typed structs, it never creates a Python dict. But when Rust starts from pre-parsed Python dicts, Cython actually beats it.

The pipeline benchmark is a reality check: on dict-heavy real-world code, the maximum speedup is 2-4x, not 50-100x. **The 100x speedups exist only when you can eliminate the Python object system entirely** — and most real code can't.

---

## The Full Report Card

### N-body (500K iterations, tight FP loops)

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.10 | 1,672ms | 0.66x | Old version |
| CPython 3.13 | 1,105ms | 1.0x | Nothing |
| CPython 3.14t | 1,534ms | 0.72x | GIL-free but slower single-thread |
| PyPy | 98ms | 11x | Ecosystem compatibility |
| Codon | 47ms | 24x | Separate runtime, no stdlib |
| Numba | 22ms | 51x | `@njit` + numpy arrays |
| Taichi | 16ms | 70x | `@ti.kernel` + Taichi fields |
| Mojo | 15ms | 75x | New language + toolchain |
| Cython | 12ms | 93x | C knowledge + landmines |
| Rust (PyO3) | 10ms | 106x | Learning Rust |

</div>

### Spectral-norm (N=2000, matrix-vector multiply)

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.10 | 16,723ms | 0.81x | Old version |
| CPython 3.13 | 13,499ms | 1.0x | Nothing |
| CPython 3.14t | 14,235ms | 0.95x | GIL-free but slower single-thread |
| PyPy | 1,065ms | 13x | Ecosystem compatibility |
| Numba | 108ms | 125x | `@njit` + numpy arrays |
| Codon | 101ms | 134x | Separate runtime, no stdlib |
| Mojo | 116ms | 117x | New language + toolchain |
| Rust (PyO3) | 95ms | 142x | Learning Rust |
| Cython | 149ms | 91x | C knowledge + landmines |
| Taichi | 72ms | 187x | `@ti.kernel` + Taichi fields |
| NumPy | 21ms | 638x | Knowing numpy + O(N^2) memory |

</div>

### JSON Pipeline (100K events, dict-heavy real-world code)

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.13 | 51ms | 1.0x | Nothing |
| Mypyc | 22ms | 2.3x | Type annotations |
| Rust (from JSON, owns pipeline) | 23ms | 2.2x | New language + bindings |
| Cython (fully optimized) | 14ms | 3.8x | Days of annotation work |

</div>

---

## What Rich Python Knows

**Upgrade first.** 3.10 to 3.11+ gives you 1.4x for free. After that, version upgrades don't move the needle.

**NumPy first.** If your problem is vectorizable, stop reading. `a.T @ (a @ u)` beat everything including Rust.

**Numba for numeric loops.** `@njit` gives you 50-125x with one decorator and honest error messages. The constraint is numpy-only data.

**Cython if you know C.** 91-93x is real, but the failure mode is silent slowness. If you don't know why `** 0.5` is different from `sqrt()`, Cython will punish you without telling you.

**Rust for pipeline ownership.** On pure compute, Cython gets within 12% of Rust. The real advantage is when Rust owns the data flow end-to-end — never creating Python objects.

**PyPy for pure Python.** 11-13x for zero code changes is remarkable. Use it when your code is pure Python with no C extension dependencies.

**Most code doesn't need any of this.** The pipeline benchmark — the most realistic of the three — topped out at 3.8x. If your hot path is `dict[str, Any]`, the answer might be "change the data structure," not "change the language." And if your code is I/O bound, none of this matters at all.

**<a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/profiling.md" target="_blank">Profile before you optimize.</a>** cProfile to find the function. line_profiler to find the line. Then pick the right tool.

**The effort curve is exponential.** PyPy (11x) costs a binary swap. Numba (51x) costs one decorator. Cython (93x) costs days and C knowledge. Rust (106x) costs learning a new language. The jump from 51x to 106x is a 2x improvement that costs 100x more effort.

Poor Python blames the language. Rich Python picks the right tool.
