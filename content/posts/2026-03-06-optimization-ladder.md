---
title: "The Optimization Ladder"
date: 2026-03-06T20:00:00
type: post
tags: [python, performance, benchmark, cython, rust, numba, numpy, mypyc, mojo, codon, taichi]
draft: false
subtitle: "every way to make Python fast, benchmarked"
description: "Python loses every public benchmark by 50-600x. I took the exact problems people use to dunk on Python and climbed every rung of the optimization ladder — from CPython version upgrades to Rust. Real numbers, real code, real effort costs."
---

Every year, someone posts a benchmark showing Python is 100x slower than C. The same argument plays out: one side says "benchmarks don't matter, real apps are I/O bound," the other says "just use a real language." Both are wrong.

I took two of the most-cited <a href="https://benchmarksgame-team.pages.debian.net/benchmarksgame/" target="_blank">Benchmarks Game</a> problems — **n-body** and **spectral-norm** — reproduced them on my machine, and ran every optimization tool I could find. Then I added a third benchmark — a JSON event pipeline — to test something closer to real-world code.

Same problems, same Apple M4 Pro, real numbers. The full code is at <a href="https://github.com/cemrehancavdar/faster-python-bench" target="_blank">faster-python-bench</a>.

Here's the starting point — CPython 3.13 on the official Benchmarks Game run:

<div class="bench-table">

| Benchmark | C gcc | CPython 3.13 | Ratio |
|---|---|---|---|
| n-body (50M) | 2.1s | 372s | **177x** |
| spectral-norm (5500) | 0.4s | 350s | **875x** |
| fannkuch-redux (12) | 2.1s | 311s | **148x** |
| mandelbrot (16000) | 0.9s | 183s | **203x** |
| binary-trees (21) | 1.0s | 33s | **33x** |

</div>

The question isn't whether Python is slow at computation. It is. The question is how much effort each fix costs and how far it gets you. That's the ladder.

---

## Why Python Is Slow

The usual suspects are the GIL, interpretation, and dynamic typing. All three matter, but none of them is the real story. The real story is that Python is designed to be *maximally dynamic* — you can monkey-patch methods at runtime, replace builtins, change a class's inheritance chain while instances exist — and that design makes it **fundamentally hard to optimize**.

A C compiler sees `a + b` between two integers and emits one CPU instruction. The Python VM sees `a + b` and has to ask: what is `a`? What is `b`? Does `a.__add__` exist? Has it been replaced since the last call? Did someone monkey-patch `int.__add__`? Every operation goes through this dispatch because the language *guarantees* you can change anything at any time.

The object overhead is where this shows up concretely. In C, an integer is 4 bytes on the stack. In Python:

```
C int:        [    4 bytes    ]

Python int:   [ ob_refcnt  8B ]    reference count
              [ ob_type    8B ]    pointer to type object
              [ ob_size    8B ]    number of digits
              [ ob_digit   4B ]    the actual value
              ─────────────────
              = 28 bytes minimum
```

4 bytes of number, 24 bytes of machinery to support dynamism. `a + b` means: dereference two heap pointers, check both type pointers, dispatch to `int.__add__`, allocate a new `PyObject` for the result, update reference counts for all three objects. One number isn't slow. Millions in a loop are.

The GIL (Global Interpreter Lock) gets blamed a lot, but it has **no impact on single-threaded performance** — it only matters when multiple CPU-bound threads compete for the interpreter. For the benchmarks in this post, the GIL is irrelevant. CPython 3.13 shipped experimental free-threaded mode (`--disable-gil`), but as we'll see, it actually makes single-threaded code *slower* because removing the GIL adds overhead to every reference count operation.

The interpretation overhead is real but is being actively addressed. CPython 3.11's <a href="https://docs.python.org/3/whatsnew/3.11.html" target="_blank">Faster CPython</a> project added adaptive specialization — the VM detects "hot" bytecodes and replaces them with type-specialized versions, skipping some of the dispatch. It helped (~1.4x). CPython 3.13 went further with an experimental <a href="https://docs.python.org/3/whatsnew/3.13.html#an-experimental-jit-compiler" target="_blank">copy-and-patch JIT compiler</a> — a lightweight JIT that stitches together pre-compiled machine code templates instead of generating code from scratch. It's not a full tracing JIT like V8 or PyPy; it's designed to be small and fast to start, avoiding the heavyweight JIT startup cost that has historically kept CPython from going this route. Early results are modest (single-digit percent improvements), but the infrastructure is now in place for more aggressive optimizations in future releases. JavaScript's V8 achieves much better JIT results, but V8 also had hundreds of engineers and a single-threaded execution model that makes optimization easier. (For more on the "why doesn't CPython JIT" question, see Anthony Shaw's <a href="https://tonybaloney.github.io/posts/why-is-python-so-slow.html" target="_blank">"Why is Python so slow?"</a>.)

So the picture is: **Python is slow because its dynamic design requires runtime dispatch on every operation.** The GIL, the interpreter, the object model — these are all consequences of that design choice. Each rung of the ladder removes some of this dispatch. The higher you climb, the more you bypass — and the more effort it costs.

---

## Rung 0: Upgrade CPython

**Cost: changing your base image. Reward: up to 1.4x.**

<div class="bench-table">

| Version | N-body | vs 3.13 | Spectral-norm | vs 3.13 |
|---|---|---|---|---|
| CPython 3.10 | 1,672ms | 0.66x | 16,723ms | 0.81x |
| CPython 3.11 | 1,175ms | 0.94x | 13,272ms | 1.02x |
| CPython 3.13 | 1,105ms | 1.0x | 13,499ms | 1.0x |
| CPython 3.14t (free-threaded) | 1,534ms | 0.72x | 14,235ms | 0.95x |

</div>

The story is **3.10 to 3.11**: a 1.42x speedup on n-body, for free. That's the <a href="https://docs.python.org/3/whatsnew/3.11.html" target="_blank">Faster CPython</a> project — adaptive specialization of bytecodes, inline caching, zero-cost exceptions. After 3.11, it's a plateau.

Free-threaded Python (3.14t) is **24-28% slower** on single-threaded code. The GIL removal adds overhead to every reference count operation. Worth it only if you have genuinely parallel CPU-bound threads. (<a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/cpython-versions.md" target="_blank">Full version comparison</a>)

This rung costs nothing. If you're still on 3.10, upgrade.

---

## Rung 1: PyPy

**Cost: switching interpreters. Reward: 11-13x.**

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.13 | 1,105ms | 13,499ms |
| PyPy | 98ms (**11x**) | 1,065ms (**13x**) |

</div>

PyPy traces your hot loops and generates native machine code. Zero code changes. Just a different interpreter.

The catch: ecosystem compatibility. If your project imports numpy, pandas, or anything with C extensions not built for PyPy, this rung doesn't exist. But for pure Python code — CLI tools, data transformers, text processors — PyPy is free speed.

---

## Rung 2: Mypyc

**Cost: type annotations you probably already have. Reward: 2.5-14x.**

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.13 | 1,105ms | 13,499ms |
| Mypyc | 442ms (**2.5x**) | 959ms (**14x**) |

</div>

Mypyc compiles type-annotated Python to C extensions using the same type analysis as mypy. No new syntax, no new language — just your existing typed Python, compiled ahead of time.

```python
# Already valid typed Python — mypyc compiles this to C
def advance(dt: float, n: int, bodies: list[Body], pairs: list[BodyPair]) -> None:
    dx: float
    dy: float
    dz: float
    dist_sq: float
    dist: float
    mag: float
    for _ in range(n):
        for (r1, v1, m1), (r2, v2, m2) in pairs:
            dx = r1[0] - r2[0]
            dy = r1[1] - r2[1]
            dz = r1[2] - r2[2]
            dist_sq = dx * dx + dy * dy + dz * dz
            dist = math.sqrt(dist_sq)
            mag = dt / (dist_sq * dist)
            # ...
```

The difference from the baseline: explicit type declarations on every local variable so mypyc can use C primitives instead of Python objects, and `math.sqrt` instead of `** -1.5` so the call compiles to C's `sqrt()`. That's it — no special decorators, no new build system beyond `mypycify()`.

The mypy project itself — ~100k+ lines of Python — achieved a <a href="https://github.com/mypyc/mypyc" target="_blank">4x end-to-end speedup</a> by compiling with mypyc. The official docs say "1.5x to 5x" for existing annotated code, "5x to 10x" for code tuned for compilation. The spectral-norm result (14x) lands above that range because the inner loop is pure arithmetic that mypyc compiles directly to C. On our dict-heavy JSON pipeline, mypyc hit 2.3x — closer to the expected floor.

The constraint: mypyc supports a subset of Python. Dynamic patterns like `**kwargs`, `getattr` tricks, and heavily duck-typed code won't compile. But if your code already passes mypy strict mode, mypyc is the lowest-effort compilation rung on the ladder.

---

## Rung 3: NumPy

**Cost: knowing NumPy. Reward: up to 638x.**

<div class="bench-table">

| | Spectral-norm |
|---|---|
| CPython 3.13 | 13,499ms |
| NumPy | 21ms (**638x**) |

</div>

638x. Faster than Rust's 142x on the same problem.

Spectral-norm is matrix-vector multiplication. NumPy pre-computes the matrix once and delegates to BLAS (Apple Accelerate on macOS):

```python
a = build_matrix(n)
for _ in range(10):
    v = a.T @ (a @ u)
    u = a.T @ (a @ v)
```

Each `@` is a single call to hand-optimized BLAS with SIMD and multithreading. NumPy trades O(N) memory for O(N^2) memory — it stores the full 2000x2000 matrix (30MB) — but the computation is done in compiled Fortran/C, not Python.

This is the lesson people miss when they say "Python is slow." Python the loop runner is slow. Python the orchestrator of compiled libraries is as fast as anything.

The constraint: your problem must fit vectorized operations. Element-wise math, matrix algebra, reductions — NumPy handles these. Irregular access patterns, conditionals per element, recursive structures — it doesn't.

---

## Rung 4: Numba

**Cost: `@njit` + restructuring data into NumPy arrays. Reward: 51-125x.**

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.13 | 1,105ms | 13,499ms |
| Numba @njit | 22ms (**51x**) | 108ms (**125x**) |

</div>

Numba JIT-compiles decorated functions to machine code via LLVM:

```python
@njit(cache=True)
def advance(dt, n, pos, vel, mass):
    for i in range(n):
        for j in range(i + 1, n):
            dx = pos[i, 0] - pos[j, 0]
            dy = pos[i, 1] - pos[j, 1]
            dz = pos[i, 2] - pos[j, 2]
            dist = sqrt(dx * dx + dy * dy + dz * dz)
            mag = dt / (dist * dist * dist)
            vel[i, 0] -= dx * mag * mass[j]
            # ...
```

One decorator. Restructure data into NumPy arrays. The constraint: Numba only understands NumPy arrays and numeric types. Strings, dicts, classes — it can't touch them. It's a scalpel, not a saw.

---

## Rung 5: Cython

**Cost: learning C's mental model, expressed in Python syntax. Reward: 91-93x.**

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.13 | 1,105ms | 13,499ms |
| Cython | 12ms (**93x**) | 149ms (**91x**) |

</div>

93x on n-body. Within 12% of Rust. But here's the thing about this rung:

**My first Cython n-body got 10.5x.** Same algorithm, same Cython, same compiler. The final version got 93x. The difference was three landmines, none of which produced warnings:

- `** 0.5` routes through Python's generic `pow()` instead of C's `sqrt()`. **5x penalty.** No error, no yellow line in the annotation report. The code works, it's just silently slow.
- Precomputed pair index arrays prevent the C compiler from unrolling the nested loop. **2x penalty.** The "clever" version is slower.
- Missing `@cython.cdivision(True)` inserts a zero-division check before every floating-point divide in the inner loop. Millions of branches that are never taken.

Cython's pitch is "just add types to Python." The reality is: learn C's mental model, express it in Python syntax, and use the annotation report (`cython -a`) to verify the compiler did what you think. The full story is in <a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/cython-minefield.md" target="_blank">The Cython Minefield</a>.

The reward is real — 93x, matching compiled languages. But the failure mode is silent. If you don't know why `** 0.5` is different from `sqrt()`, Cython will punish you without telling you.

---

## Rung 6: The New Wave

**Cost: new toolchains, rough edges, ecosystem gaps. Reward: 24-187x.**

Three tools promise to compile Python (or Python-like code) to native machine code. I tested all three.

<div class="bench-table">

| | N-body | Speedup | Spectral-norm | Speedup | The catch |
|---|---|---|---|---|---|
| Codon 0.19 | 47ms | **24x** | 101ms | **134x** | Own runtime, no stdlib, standalone binaries only |
| Mojo nightly | 15ms | **75x** | 116ms | **117x** | New language (pre-1.0), needs pixi, full rewrite required |
| Taichi 1.7 | 16ms | **70x** | 72ms | **187x** | `from __future__ import annotations` silently breaks it |

</div>

The numbers are real. The developer experience is rough. Codon can't import your existing code. Mojo is a new language wearing Python's clothes. Taichi has the best spectral-norm result (187x) but surprising failure modes — a standard Python import at the top of the file silently disables its compiler. (<a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/new-wave-compilers.md" target="_blank">Full deep dive with code and DX verdicts</a>)

None are drop-in. All are worth watching.

---

## Rung 7: Rust via PyO3

**Cost: learning Rust. Reward: 106-142x.**

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.13 | 1,105ms | 13,499ms |
| Rust (PyO3) | 10ms (**106x**) | 95ms (**142x**) |

</div>

The top of the ladder. But notice: on n-body, Cython at 12ms vs Rust at 10ms is only a 1.2x difference. Both compiled to native machine code. The remaining gap is compiler backend quality (LLVM vs GCC), not a fundamental language difference.

The real Rust advantage isn't raw speed — it's **pipeline ownership**. When Rust parses JSON directly with serde into typed structs, it never creates a Python dict. It bypasses the Python object system entirely. That matters more on the next benchmark.

---

## The Ceiling

The Benchmarks Game problems are pure compute: tight loops, no I/O, no data structures beyond arrays. Most Python code looks nothing like that. So I built a third benchmark: load 100K JSON events, filter, transform, aggregate per user. Dicts, strings, datetime parsing — the kind of code that makes Numba useless and makes Cython fight the Python object system.

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.13 | 51ms | 1.0x | Nothing |
| Mypyc | 22ms | 2.3x | Type annotations |
| Rust (from JSON, serde) | 23ms | 2.2x | New language + bindings |
| Cython (fully optimized) | 14ms | 3.8x | Days of annotation work |

</div>

The ceiling is 3.8x. Not 50x. Not 100x.

Why? The bottleneck is **Python dict access**. Every tool except Rust still goes through `PyDict_GetItem`. Even Cython's fully optimized version — with `@cython.cclass`, C arrays for counters, `@cython.cfunc` on every helper, direct CPython C-API calls (`PyList_GET_ITEM`, `PyDict_GetItem` with borrowed refs) — still reads input dicts through the Python C API.

Rust wins when it owns everything — parsing JSON directly with serde into typed structs, never creating a Python dict. But when Rust starts from pre-parsed Python dicts, Cython actually beats it.

**The 100x speedups exist only when you can eliminate the Python object system entirely.** Most real code — the kind with dicts, strings, and heterogeneous data — can't. The pipeline benchmark is a 2-4x problem, not a 100x problem. The code is at <a href="https://github.com/cemrehancavdar/faster-python-bench" target="_blank">faster-python-bench</a>.

---

## The Full Report Card

### N-body (500K iterations, tight floating-point loops)

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.10 | 1,672ms | 0.66x | Old version |
| CPython 3.13 | 1,105ms | 1.0x | Nothing |
| CPython 3.14t | 1,534ms | 0.72x | GIL-free but slower single-thread |
| Mypyc | 442ms | 2.5x | Type annotations |
| PyPy | 98ms | 11x | Ecosystem compatibility |
| Codon | 47ms | 24x | Separate runtime, no stdlib |
| Numba | 22ms | 51x | `@njit` + NumPy arrays |
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
| Mypyc | 959ms | 14x | Type annotations |
| PyPy | 1,065ms | 13x | Ecosystem compatibility |
| Numba | 108ms | 125x | `@njit` + NumPy arrays |
| Codon | 101ms | 134x | Separate runtime, no stdlib |
| Mojo | 116ms | 117x | New language + toolchain |
| Rust (PyO3) | 95ms | 142x | Learning Rust |
| Cython | 149ms | 91x | C knowledge + landmines |
| Taichi | 72ms | 187x | `@ti.kernel` + Taichi fields |
| NumPy | 21ms | 638x | Knowing NumPy + O(N^2) memory |

</div>

### JSON pipeline (100K events, dict-heavy real-world code)

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.13 | 51ms | 1.0x | Nothing |
| Mypyc | 22ms | 2.3x | Type annotations |
| Rust (from JSON, owns pipeline) | 23ms | 2.2x | New language + bindings |
| Cython (fully optimized) | 14ms | 3.8x | Days of annotation work |

</div>

---

## When to Stop Climbing

The effort curve is exponential. Mypyc (2.5-14x) costs type annotations. PyPy (11x) costs a binary swap. Numba (51x) costs one decorator. Cython (93x) costs days and C knowledge. Rust (106x) costs learning a new language. The jump from 51x to 106x is a 2x improvement that costs 100x more effort.

**Upgrade first.** 3.10 to 3.11 gives you 1.4x for free.

**Mypyc for typed codebases.** If your code already passes mypy strict, compile it. 2.5x on n-body, 14x on spectral-norm, for almost no work.

**NumPy for vectorizable math.** If your problem is matrix algebra or element-wise operations, stop reading. `a.T @ (a @ u)` beat everything including Rust.

**Numba for numeric loops.** `@njit` gives you 51-125x with one decorator and honest error messages.

**Cython if you know C.** 91-93x is real, but the failure mode is silent slowness.

**Rust for pipeline ownership.** On pure compute, Cython gets within 12% of Rust. The real advantage is when Rust owns the data flow end-to-end.

**PyPy for pure Python.** 11-13x for zero code changes is remarkable, if your dependencies support it.

**Most code doesn't need any of this.** The pipeline benchmark — the most realistic of the three — topped out at 3.8x. If your hot path is `dict[str, Any]`, the answer might be "change the data structure," not "change the language." And if your code is I/O bound, none of this matters at all.

<a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/profiling.md" target="_blank">Profile before you optimize.</a> `cProfile` to find the function. `line_profiler` to find the line. Then pick the right rung.
